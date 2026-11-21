"""PricePulse API (FastAPI). Run:  uvicorn app.main:app --port 8000"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import data as D, db, model as mdl, rl, sim
from .cache import cache
from .engine import PricingEngine, Settings
from .kafka_stream import kafka_manager
from .stream import DemandStream

STATIC_DIR = Path(os.environ.get("PRICEPULSE_STATIC", Path(__file__).resolve().parent.parent / "static"))


class Store:
    """All live, in-memory application state (persisted to SQLite where it matters)."""

    def __init__(self):
        self.lock = threading.RLock()
        self.settings = Settings()
        self.stream = DemandStream()
        self.rng = np.random.default_rng(123)
        self.state: dict[str, dict] = {}
        self.rl_results: dict[str, dict] = {}
        self.backtest: dict | None = None
        self.flash_active: set[str] = set()
        self.dirty: set[str] = set()
        self.version = 0
        self._cache: tuple | None = None

    # ------------------------------------------------------------------ setup
    def init(self):
        db.conn()
        bundle = mdl.load()
        catalog = D.make_catalog()
        self.hist = D.make_history(catalog)
        if bundle is None or len(bundle["catalog"]) != len(catalog):
            bundle = mdl.train(catalog, self.hist)
        self.engine = PricingEngine(bundle)
        saved = db.load_state()
        rng = np.random.default_rng(77)
        for sku, c in self.engine.catalog.iterrows():
            if sku in saved:
                r = saved[sku]
                self.state[sku] = dict(current_price=r["current_price"], stock=r["stock"], comp_price=r["comp_price"])
            else:
                self.state[sku] = dict(current_price=float(c.ref_price), stock=float(round(c.capacity * rng.uniform(0.12, 0.95))),
                                       comp_price=float(round(c.ref_comp)))
                db.save_state(sku, *self.state[sku].values())
            self.stream.backfill(sku, self._rate(c), self.rng)

    @staticmethod
    def _rate(c) -> float:  # baseline order rate per 5 minutes for the demo stream
        return 1.5 + 0.12 * float(c.base_demand_est)

    def reset(self):
        db.reset()
        self.state.clear(); self.flash_active.clear(); self.dirty.clear(); self.rl_results.clear()
        self.backtest = None
        self.stream = DemandStream()
        self.settings = Settings()
        self.init()
        self.version += 1

    # ------------------------------------------------------------------ helpers
    def flash(self, sku):
        return self.stream.status(sku)

    def rec_state(self, sku, flash: dict | None = None, customer_segment: str | None = None):
        st = self.state[sku]
        f = flash or self.flash(sku)
        return dict(sku=sku, current_price=st["current_price"], comp_price=st["comp_price"], stock=st["stock"],
                    flash_mult=f["multiplier"], flash_ratio=f["ratio"], customer_segment=customer_segment or "Standard")

    def recommend_all(self):
        key = (self.version, tuple(sorted(self.settings.to_dict().items())), int(time.time() / 3))
        if self._cache and self._cache[0] == key:
            return self._cache[1]
        flashes = {s: self.flash(s) for s in self.state}
        recs = self.engine.recommend_many([self.rec_state(s, flashes[s]) for s in self.state], date.today(), self.settings)
        out = {r["sku"]: r for r in recs}
        self._cache = (key, out)
        cache.set("recommendations_summary", {s: r["recommended_price"] for s, r in out.items()}, ex=10)
        return out

    def apply_price(self, sku, price, reason, source):
        with self.lock:
            st = self.state[sku]
            old = st["current_price"]
            if abs(price - old) < 1e-9:
                return False
            st["current_price"] = float(price)
            db.log_price_change(sku, old, price, reason, source)
            db.save_state(sku, st["current_price"], st["stock"], st["comp_price"])
            cache.set(f"sku_price:{sku}", st["current_price"])
            kafka_manager.emit_price_change(sku, old, price, reason, source)
            if abs(price / old - 1) >= 0.10:
                db.log_alert("warning", sku, "large_price_change",
                             f"{self.name(sku)}: price moved {((price / old - 1) * 100):+.1f}% (₹{old:,.0f} -> ₹{price:,.0f})")
            self.version += 1
            return True

    def name(self, sku):
        return self.engine.catalog.loc[sku, "name"]

    def set_state(self, sku, comp_price=None, stock=None):
        with self.lock:
            st = self.state[sku]
            c = self.engine.catalog.loc[sku]
            if comp_price is not None:
                old = st["comp_price"]
                st["comp_price"] = float(comp_price)
                ch = comp_price / old - 1
                if abs(ch) >= 0.05:
                    db.log_alert("info", sku, "competitor_move",
                                 f"Competitor {'cut' if ch < 0 else 'raised'} price on {self.name(sku)} by {abs(ch) * 100:.1f}% (₹{comp_price:,.0f})")
                self.dirty.add(sku)
            if stock is not None:
                st["stock"] = float(max(stock, 0))
                if st["stock"] == 0:
                    db.log_alert("critical", sku, "stockout", f"Stock-out: {self.name(sku)}")
                elif st["stock"] / max(c.base_demand_est, 0.1) < 3:
                    db.log_alert("warning", sku, "low_stock", f"Low stock: {self.name(sku)} has {st['stock']:.0f} units left")
                self.dirty.add(sku)
            db.save_state(sku, st["current_price"], st["stock"], st["comp_price"])
            self.version += 1


store = Store()


# ---------------------------------------------------------------------- background loops
async def traffic_loop():
    skus = list(store.state)
    rates = np.array([store._rate(store.engine.catalog.loc[s]) / 300 for s in skus])
    while True:
        await asyncio.sleep(1)
        counts = store.rng.poisson(rates)
        for i in np.nonzero(counts)[0]:
            store.stream.add(skus[i], int(counts[i]))


async def market_loop():
    """Mock competitor price feed: a few SKUs move every few seconds."""
    skus = list(store.state)
    while True:
        await asyncio.sleep(6)
        for sku in store.rng.choice(skus, size=3, replace=False):
            c = store.engine.catalog.loc[sku]
            cur = store.state[sku]["comp_price"]
            new = float(np.clip(cur * (1 + store.rng.normal(0, 0.025)), c.ref_price * 0.8, c.ref_price * 1.25))
            store.set_state(sku, comp_price=round(new))


async def auto_loop():
    while True:
        await asyncio.sleep(3)
        try:
            for sku in store.state:  # detect flash-sale transitions
                f = store.flash(sku)
                if f["flash"] and sku not in store.flash_active:
                    store.flash_active.add(sku); store.dirty.add(sku)
                    db.log_alert("critical", sku, "flash_sale",
                                 f"Flash sale detected on {store.name(sku)}: {f['window_orders']} orders in 5 min (x{f['ratio']:.1f} baseline)")
                elif not f["flash"] and sku in store.flash_active:
                    store.flash_active.discard(sku); store.dirty.add(sku)
                    db.log_alert("info", sku, "flash_end", f"Demand spike on {store.name(sku)} has cooled down")
            if store.settings.auto_mode and store.dirty:
                skus = list(store.dirty); store.dirty.clear()
                recs = store.engine.recommend_many([store.rec_state(s) for s in skus], date.today(), store.settings)
                for r in recs:
                    if abs(r["change_pct"]) >= 1.0:
                        store.apply_price(r["sku"], r["recommended_price"], "auto-reprice: " + "; ".join(
                            f"{s['name']} ₹{s['price']:,.0f}" for s in r["steps"][1:4]), "auto")
            elif not store.settings.auto_mode:
                store.dirty.clear()
        except Exception as e:  # keep the loop alive
            print("auto_loop error:", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init()
    tasks = [asyncio.create_task(f()) for f in (traffic_loop, market_loop, auto_loop)]
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="PricePulse", version="1.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------- schemas
class SettingsIn(BaseModel):
    objective: str | None = Field(None, pattern="^(balanced|growth|revenue|profit)$")
    comp_weight: float | None = Field(None, ge=0, le=1)
    min_margin: float | None = Field(None, ge=0, le=0.6)
    max_price_ratio: float | None = Field(None, ge=1.0, le=2.5)
    max_step: float | None = Field(None, ge=0.01, le=0.5)
    auto_mode: bool | None = None


class StateIn(BaseModel):
    comp_price: float | None = Field(None, gt=0)
    stock: float | None = Field(None, ge=0)


class ApplyIn(BaseModel):
    price: float | None = Field(None, gt=0)


class OrderIn(BaseModel):
    sku: str
    qty: int = Field(1, ge=1, le=1000)


class FlashIn(BaseModel):
    sku: str
    orders: int = Field(45, ge=5, le=500)


class BacktestIn(BaseModel):
    days: int = Field(30, ge=7, le=90)
    objective: str | None = Field(None, pattern="^(balanced|growth|revenue|profit)$")
    seed: int = 11


def sku_or_404(sku: str):
    if sku not in store.state:
        raise HTTPException(404, f"Unknown SKU {sku}")
    return sku


def product_view(sku, rec=None, fl=None):
    c = store.engine.catalog.loc[sku]
    st = store.state[sku]
    rec = rec or store.recommend_all()[sku]
    fl = fl or store.flash(sku)
    return dict(sku=sku, name=c["name"], category=c.category, cost=float(c.cost), ref_price=float(c.ref_price),
                current_price=st["current_price"], comp_price=st["comp_price"], stock=st["stock"],
                capacity=float(c.capacity), days_of_cover=rec["days_of_cover"],
                recommended_price=rec["recommended_price"], change_pct=rec["change_pct"],
                margin_pct=round((st["current_price"] - c.cost) / st["current_price"] * 100, 1),
                est_elasticity=rec["est_elasticity"], flash=fl["flash"], flash_ratio=fl["ratio"])


# ---------------------------------------------------------------------- routes
@app.get("/api/health")
def health():
    return dict(status="ok", skus=len(store.state), model_trained_at=store.engine.metrics["trained_at"],
                cache=cache.status(), kafka=kafka_manager.status(),
                time=datetime.now().isoformat(timespec="seconds"))


@app.get("/api/settings")
def get_settings():
    return store.settings.to_dict()


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(store.settings, k, v)
    if store.settings.auto_mode:
        store.dirty.update(store.state)
    store.version += 1
    return store.settings.to_dict()


@app.get("/api/products")
def products(category: str | None = None, q: str | None = None):
    recs = store.recommend_all()
    out = []
    for sku in store.state:
        v = product_view(sku, recs[sku])
        if category and v["category"] != category:
            continue
        if q and q.lower() not in (v["name"] + v["sku"]).lower():
            continue
        out.append(v)
    return dict(categories=list(D.CATEGORIES), customer_segments=list(D.CUSTOMER_SEGMENTS), products=out)


@app.get("/api/products/{sku}")
def product_detail(sku: str, segment: str | None = Query(None)):
    sku_or_404(sku)
    fl = store.flash(sku)
    rec = store.engine.recommend(store.rec_state(sku, fl, customer_segment=segment), date.today(), store.settings)
    c = store.engine.catalog.loc[sku]
    h = store.hist[store.hist.sku == sku].tail(90)
    return dict(
        product=product_view(sku, rec, fl), recommendation=rec, stream=fl,
        customer_segments=list(D.CUSTOMER_SEGMENTS),
        current_segment=segment or "Standard",
        history=[dict(date=str(r.date), price=r.price, comp_price=r.comp_price, units=int(r.units)) for r in h.itertuples()],
        truth=dict(true_elasticity=round(float(c.true_elasticity), 2),
                   note="Ground truth is only known because the data is synthetic."),
        price_log=db.query("SELECT ts,old_price,new_price,reason,source FROM price_changes WHERE sku=? ORDER BY id DESC LIMIT 15", (sku,)),
    )


@app.get("/api/products/{sku}/demand-curve")
def demand_curve(sku: str):
    sku_or_404(sku)
    rec = store.engine.recommend(store.rec_state(sku), date.today(), store.settings)
    return dict(curve=store.engine.demand_curve(store.rec_state(sku), date.today(), store.settings),
                current=rec["current_price"], recommended=rec["recommended_price"], floor=rec["floor"], ceiling=rec["ceiling"])


@app.post("/api/products/{sku}/recommend")
def recommend_with(sku: str, body: SettingsIn | None = None, segment: str | None = Query(None)):
    sku_or_404(sku)
    s = Settings(**store.settings.to_dict())
    if body:
        for k, v in body.model_dump(exclude_none=True).items():
            setattr(s, k, v)
    return store.engine.recommend(store.rec_state(sku, customer_segment=segment), date.today(), s)


@app.post("/api/products/{sku}/apply")
def apply(sku: str, body: ApplyIn | None = None):
    sku_or_404(sku)
    rec = store.engine.recommend(store.rec_state(sku), date.today(), store.settings)
    price = body.price if body and body.price else rec["recommended_price"]
    source = "manual" if body and body.price else "recommendation"
    changed = store.apply_price(sku, float(price), "manual override" if source == "manual" else
                                "applied recommendation: " + "; ".join(f"{s['name']} ₹{s['price']:,.0f}" for s in rec["steps"][:4]), source)
    return dict(changed=changed, price=store.state[sku]["current_price"])


@app.post("/api/products/{sku}/state")
def set_product_state(sku: str, body: StateIn):
    sku_or_404(sku)
    store.set_state(sku, body.comp_price, body.stock)
    return store.state[sku]


@app.get("/api/competitors/{sku}")
def competitor_api(sku: str):
    """Mock of the external competitor-price API the engine integrates with."""
    sku_or_404(sku)
    return dict(sku=sku, competitor="MarketRival", price=store.state[sku]["comp_price"], currency="INR",
                updated_at=datetime.now().isoformat(timespec="seconds"))


@app.post("/api/reprice")
def reprice(apply: bool = True):
    recs = store.recommend_all().values()
    n = 0
    for r in recs:
        if apply and abs(r["change_pct"]) >= 0.5:
            n += store.apply_price(r["sku"], r["recommended_price"], "bulk reprice", "bulk")
    return dict(applied=n)


@app.post("/api/orders")
def order(body: OrderIn):
    sku_or_404(body.sku)
    st = store.state[body.sku]
    sold = min(body.qty, st["stock"])
    store.stream.add(body.sku, int(body.qty))
    kafka_manager.emit_order(body.sku, int(body.qty))
    store.set_state(body.sku, stock=st["stock"] - sold)
    return dict(sold=sold, stock=store.state[body.sku]["stock"], status=store.flash(body.sku))


@app.post("/api/stream/flash")
def trigger_flash(body: FlashIn):
    sku_or_404(body.sku)
    now = time.time()
    for t in now - store.rng.uniform(0, 90, body.orders):
        store.stream.add(body.sku, 1, float(t))
    return store.flash(body.sku)


@app.get("/api/stream/status")
def stream_status():
    rows = []
    for sku in store.state:
        f = store.flash(sku)
        rows.append(dict(f, name=store.name(sku), category=store.engine.catalog.loc[sku, "category"]))
    rows.sort(key=lambda r: -r["ratio"])
    return dict(window_seconds=300, slide_seconds=60, trigger_ratio=3.0, min_orders=10, rows=rows,
                active=sum(r["flash"] for r in rows))


@app.get("/api/stream/{sku}/timeline")
def stream_timeline(sku: str):
    sku_or_404(sku)
    return dict(timeline=store.stream.timeline(sku, 30), status=store.flash(sku))


@app.get("/api/alerts")
def alerts(limit: int = Query(30, le=200)):
    return db.query("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,))


@app.get("/api/price-changes")
def price_changes(limit: int = Query(30, le=200)):
    rows = db.query("SELECT * FROM price_changes ORDER BY id DESC LIMIT ?", (limit,))
    for r in rows:
        r["name"] = store.name(r["sku"])
    return rows


@app.get("/api/dashboard")
def dashboard():
    eng = store.engine
    skus = list(store.state)
    day = date.today()
    cur = np.array([store.state[s]["current_price"] for s in skus])
    comp = [store.state[s]["comp_price"] for s in skus]
    stock = np.array([store.state[s]["stock"] for s in skus])
    cat = eng.catalog.loc[skus]
    ref = cat.ref_price.values
    u_cur = np.minimum(eng.predict_units(skus, cur, comp, day), stock)
    u_ref = np.minimum(eng.predict_units(skus, ref, comp, day), stock)
    rev_c, rev_r = (cur * u_cur).sum(), (ref * u_ref).sum()
    pr_c, pr_r = ((cur - cat.cost.values) * u_cur).sum(), ((ref - cat.cost.values) * u_ref).sum()
    recs = store.recommend_all()
    since = time.time() - 86400
    n_changes = db.query("SELECT COUNT(*) n FROM price_changes WHERE ts>?", (since,))[0]["n"]
    low = [s for s in skus if recs[s]["days_of_cover"] < 3]
    by_cat = {}
    for s, rv in zip(skus, cur * u_cur):
        by_cat[cat.loc[s, "category"]] = by_cat.get(cat.loc[s, "category"], 0) + float(rv)
    return dict(
        skus=len(skus), est_daily_revenue=round(float(rev_c)), est_daily_revenue_static=round(float(rev_r)),
        revenue_uplift_pct=round(float((rev_c / rev_r - 1) * 100), 2), profit_uplift_pct=round(float((pr_c / pr_r - 1) * 100), 2),
        price_changes_24h=int(n_changes), flash_active=len(store.flash_active), low_stock=len(low),
        low_stock_skus=[dict(sku=s, name=store.name(s), cover=recs[s]["days_of_cover"]) for s in low[:6]],
        pending_recommendations=sum(1 for r in recs.values() if abs(r["change_pct"]) >= 1),
        revenue_by_category=[dict(category=k, revenue=round(v)) for k, v in by_cat.items()],
        backtest=store.backtest["summary"] if store.backtest else None, settings=store.settings.to_dict(),
        note="Uplift figures compare today's live prices with static reference prices using the demand model.")


@app.post("/api/simulate/backtest")
def backtest(body: BacktestIn):
    s = Settings(**store.settings.to_dict())
    if body.objective:
        s.objective = body.objective
    store.backtest = sim.run_backtest(store.engine, body.days, s, seed=body.seed)
    return store.backtest


@app.get("/api/simulate/backtest")
def last_backtest():
    return store.backtest or {}


@app.get("/api/model/metrics")
def model_metrics():
    imp = sorted(store.engine.importance.items(), key=lambda kv: -kv[1])
    rf_imp = sorted(getattr(store.engine, "rf_importance", {}).items(), key=lambda kv: -kv[1])
    c = store.engine.catalog
    return dict(
        metrics=store.engine.metrics,
        importance=[dict(feature=k, importance=round(v, 4)) for k, v in imp],
        rf_importance=[dict(feature=k, importance=round(v, 4)) for k, v in rf_imp],
        elasticity=[dict(sku=s, name=r["name"], estimated=round(float(r.est_elasticity), 2), truth=round(float(r.true_elasticity), 2))
                    for s, r in c.iterrows()],
        params=dict(
            algorithm="XGBoost (monotone constraints on price and competitor price)",
            baseline_algorithm="RandomForestRegressor (Weeks 1-2 baseline)",
            features=mdl.FEATURES,
        ),
    )


@app.post("/api/model/retrain")
def retrain():
    bundle = mdl.train(D.make_catalog(), store.hist)
    store.engine.set_bundle(bundle)
    store.version += 1
    return bundle["metrics"]


@app.post("/api/rl/{sku}/train")
def rl_train(sku: str, episodes: int = Query(800, ge=100, le=5000), algo: str = Query("dqn")):
    sku_or_404(sku)
    res = rl.train(store.engine.catalog.loc[sku], episodes, algo=algo)
    store.rl_results[sku] = res
    return rl_view(sku)


@app.get("/api/rl/{sku}")
def rl_view(sku: str):
    sku_or_404(sku)
    r = store.rl_results.get(sku)
    if not r:
        return {}
    st = store.state[sku]
    rec = rl.recommend(r, store.engine.catalog.loc[sku], st["stock"], st["comp_price"])
    ml = store.engine.recommend(store.rec_state(sku), date.today(), store.settings)
    return dict({k: v for k, v in r.items() if k != "Q"}, rl_recommendation=rec, ml_recommendation=ml["recommended_price"],
                current_price=st["current_price"])


@app.post("/api/reset")
def reset_demo():
    store.reset()
    return dict(status="reset")


if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")

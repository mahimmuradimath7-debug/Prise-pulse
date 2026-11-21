"""Market simulator: back-test static pricing vs PricePulse on the hidden ground-truth demand."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
from scipy.stats import poisson

from .data import true_demand, seasonal_mult
from .engine import PricingEngine, Settings


def run_backtest(engine: PricingEngine, days: int = 30, settings: Settings | None = None, seed: int = 11,
                 start: date | None = None) -> dict:
    s = settings or Settings()
    rng = np.random.default_rng(seed)
    cat = engine.catalog.reset_index(drop=True)
    n = len(cat)
    start = start or date.today()
    ref, cost = cat.ref_price.values, cat.cost.values
    base, el = cat.base_demand.values, cat.true_elasticity.values
    ref_comp, cap = cat.ref_comp.values, cat.capacity.values

    # competitor price path (shared by both arms)
    comp_ratio = np.empty((n, days))
    comp_ratio[:, 0] = rng.uniform(0.95, 1.05, n)
    for t in range(1, days):
        comp_ratio[:, t] = np.clip(comp_ratio[:, t - 1] + rng.normal(0, 0.025, n), 0.82, 1.2)

    stock = {"static": cap.copy(), "dynamic": cap.copy()}
    price_dyn = ref.copy()
    series = {k: dict(revenue=[], profit=[], stockouts=[], lost=[]) for k in stock}
    per_sku = {k: dict(revenue=np.zeros(n), profit=np.zeros(n)) for k in stock}

    for d in range(days):
        day = start + timedelta(days=d)
        comp = ref * comp_ratio[:, d]
        seas = np.array([seasonal_mult(c, day) for c in cat.category])
        states = [dict(sku=cat.sku[i], current_price=float(price_dyn[i]), comp_price=float(comp[i]),
                       stock=float(stock["dynamic"][i])) for i in range(n)]
        recs = engine.recommend_many(states, day, s)
        price_dyn = np.array([r["recommended_price"] for r in recs])
        u = rng.random(n)  # common random numbers: both arms face the same demand shocks
        for arm, price in (("static", ref), ("dynamic", price_dyn)):
            lam = true_demand(base, ref, el, price, comp, ref_comp, seas)
            demand = poisson.ppf(u, lam)
            sold = np.minimum(demand, stock[arm])
            lost = demand - sold
            stock[arm] = stock[arm] - sold
            rev, prof = sold * price, sold * (price - cost)
            series[arm]["revenue"].append(float(rev.sum()))
            series[arm]["profit"].append(float(prof.sum()))
            series[arm]["stockouts"].append(int((lost > 0).sum()))
            series[arm]["lost"].append(float(lost.sum()))
            per_sku[arm]["revenue"] += rev
            per_sku[arm]["profit"] += prof
            if d % 7 == 6:  # weekly replenishment up to capacity (same policy for both arms)
                stock[arm] = cap.copy()

    def tot(arm, k):
        return float(np.sum(series[arm][k]))

    res = {}
    for k in ("revenue", "profit"):
        a, b = tot("static", k), tot("dynamic", k)
        res[k] = dict(static=round(a), dynamic=round(b), uplift_pct=round((b / a - 1) * 100, 2))
    so_a, so_b = tot("static", "stockouts"), tot("dynamic", "stockouts")
    res["stockout_sku_days"] = dict(static=int(so_a), dynamic=int(so_b),
                                    reduction_pct=round((1 - so_b / so_a) * 100, 2) if so_a else 0.0)
    lo_a, lo_b = tot("static", "lost"), tot("dynamic", "lost")
    res["lost_units"] = dict(static=round(lo_a), dynamic=round(lo_b))

    cum = lambda x: np.cumsum(x).round().tolist()
    daily = [dict(day=(start + timedelta(days=i)).isoformat(),
                  static_revenue=round(series["static"]["revenue"][i]), dynamic_revenue=round(series["dynamic"]["revenue"][i]),
                  static_cum=cum(series["static"]["revenue"])[i], dynamic_cum=cum(series["dynamic"]["revenue"])[i],
                  static_stockouts=series["static"]["stockouts"][i], dynamic_stockouts=series["dynamic"]["stockouts"][i])
             for i in range(days)]
    cats = {}
    for c in cat.category.unique():
        m = (cat.category == c).values
        a, b = per_sku["static"]["revenue"][m].sum(), per_sku["dynamic"]["revenue"][m].sum()
        pa, pb = per_sku["static"]["profit"][m].sum(), per_sku["dynamic"]["profit"][m].sum()
        cats[c] = dict(revenue_uplift_pct=round((b / a - 1) * 100, 2), profit_uplift_pct=round((pb / pa - 1) * 100, 2))
    return dict(days=days, start=start.isoformat(), objective=s.objective, skus=n, summary=res, daily=daily,
                by_category=[dict(category=k, **v) for k, v in cats.items()],
                note="Simulation on synthetic data: both policies face identical demand shocks and replenishment. "
                     "Treat uplift as a validation of the pipeline, not a forecast of real-world gains.")

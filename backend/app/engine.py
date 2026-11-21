"""Pricing engine: ML optimisation + competitor blending + inventory/flash rules + guardrails."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date

import numpy as np
import pandas as pd

from . import data as D, model as mdl

GRID_N = 48


@dataclass
class Settings:
    objective: str = "balanced"      # balanced | growth | revenue | profit
    comp_weight: float = 0.30        # 30% competitor, 70% ML model (as in the project brief)
    min_margin: float = 0.08         # never price below cost / (1 - min_margin)
    max_price_ratio: float = 1.35    # cap vs reference price
    max_step: float = 0.15           # max change per update vs current price
    auto_mode: bool = False

    def to_dict(self):
        return asdict(self)


def rnd(p: float) -> float:
    return float(round(p) if p >= 100 else round(p, 1))


class PricingEngine:
    def __init__(self, bundle: dict):
        self.set_bundle(bundle)

    def set_bundle(self, bundle):
        self.model = bundle["model"]
        self.rf_model = bundle.get("rf_model")
        self.catalog: pd.DataFrame = bundle["catalog"].set_index("sku", drop=False)
        self.metrics = bundle["metrics"]
        self.importance = bundle["importance"]
        self.rf_importance = bundle.get("rf_importance", {})

    # ---------------------------------------------------------------- forecasting
    def predict_units(self, skus, price, comp, day: date) -> np.ndarray:
        rows = self.catalog.loc[list(skus)].reset_index(drop=True)
        X = mdl.build_frame(rows, price, comp, day)
        return np.expm1(self.model.predict(X)).clip(min=0.01)

    def bounds(self, sku: str, s: Settings):
        c = self.catalog.loc[sku]
        lo = c.cost / (1 - s.min_margin)
        hi = c.ref_price * s.max_price_ratio
        return float(lo), float(max(hi, lo * 1.05))

    # ---------------------------------------------------------------- recommend
    def recommend_many(self, states: list[dict], day: date, s: Settings) -> list[dict]:
        """states: [{sku, current_price, comp_price, stock, flash_mult(optional), flash_ratio(optional)}]"""
        if not states:
            return []
        sk, prices, comps, spans = [], [], [], []
        grids = []
        for st in states:
            lo, hi = self.bounds(st["sku"], s)
            grid = np.linspace(lo, hi, GRID_N)
            grids.append(grid)
            allp = np.append(grid, st["current_price"])
            spans.append((len(prices), len(prices) + len(allp)))
            prices.extend(allp)
            comps.extend([st["comp_price"]] * len(allp))
            sk.extend([st["sku"]] * len(allp))
        units_all = self.predict_units(sk, prices, comps, day)
        prices = np.asarray(prices)

        out, finals = [], []
        for st, grid, (a, b) in zip(states, grids, spans):
            c = self.catalog.loc[st["sku"]]
            u = units_all[a:b - 1]
            u_cur = float(units_all[b - 1])
            stock = max(float(st["stock"]), 0.0)
            sold = np.minimum(u, stock)
            rev, prof = grid * sold, (grid - c.cost) * sold
            sold_cur = min(u_cur, stock)
            rev_cur, prof_cur = st["current_price"] * sold_cur, (st["current_price"] - c.cost) * sold_cur
            if s.objective == "revenue":
                score = rev
            elif s.objective == "profit":
                score = prof
            elif s.objective == "growth":
                # maximise revenue while keeping profit at least at today's level
                feasible = prof >= prof_cur * 0.99
                score = np.where(feasible, rev, -1e18 + prof)
            else:
                score = 0.5 * rev / max(rev_cur, 1e-6) + 0.5 * prof / max(abs(prof_cur), 1e-6)
            p_ml = float(grid[int(np.argmax(score))])
            steps = [dict(name="ML optimum", price=rnd(p_ml),
                          note=f"Best price on a {GRID_N}-point grid for the '{s.objective}' objective")]

            comp = float(st["comp_price"])
            p1 = (1 - s.comp_weight) * p_ml + s.comp_weight * comp
            steps.append(dict(name="Competitor blend", price=rnd(p1),
                              note=f"{round((1 - s.comp_weight) * 100)}% model + {round(s.comp_weight * 100)}% competitor price (₹{rnd(comp):,})"))

            # Customer segment personalization (Project Brief: "Customer segments")
            seg_name = st.get("customer_segment") or "Standard"
            seg_info = D.CUSTOMER_SEGMENTS.get(seg_name, D.CUSTOMER_SEGMENTS["Standard"])
            p_seg = p1 * float(seg_info["multiplier"])
            if seg_name != "Standard":
                steps.append(dict(name=f"Customer segment ({seg_name})", price=rnd(p_seg),
                                  note=f"{seg_info['description']} (x{seg_info['multiplier']:.2f})"))

            u1 = float(np.interp(p_seg, grid, u))
            cover = stock / max(u1, 0.1)
            if cover < 3:
                adj = min(0.08, (3 - cover) / 3 * 0.08)
                note = f"Only {cover:.1f} days of stock left - nudge price up {adj * 100:.1f}%"
            elif cover > 30:
                adj = -min(0.08, (cover - 30) / 60 * 0.08)
                note = f"{cover:.0f} days of stock on hand - nudge price down {abs(adj) * 100:.1f}%"
            else:
                adj, note = 0.0, f"{cover:.0f} days of cover - no adjustment"
            p2 = p_seg * (1 + adj)
            steps.append(dict(name="Inventory rule", price=rnd(p2), note=note))

            fm = float(st.get("flash_mult", 1.0) or 1.0)
            p3 = p2 * fm
            steps.append(dict(name="Flash-sale multiplier", price=rnd(p3),
                              note=(f"Demand spike x{st.get('flash_ratio', 0):.1f} detected - emergency x{fm:.2f}"
                                    if fm > 1 else "No demand spike")))

            lo, hi = self.bounds(st["sku"], s)
            cur = float(st["current_price"])
            lo2 = max(lo, cur * (1 - s.max_step))
            hi2 = min(hi * (1.15 if fm > 1 else 1.0), cur * (1 + s.max_step))
            if lo2 > hi2:
                lo2 = hi2 = min(max(cur, lo), hi * 1.15)
            p4 = rnd(float(np.clip(p3, lo2, hi2)))
            steps.append(dict(name="Guardrails", price=p4,
                              note=f"Floor ₹{rnd(lo):,} (min margin {s.min_margin * 100:.0f}%), max step ±{s.max_step * 100:.0f}%"))
            finals.append(p4)
            out.append(dict(sku=st["sku"], current_price=cur, recommended_price=p4, ml_price=rnd(p_ml), steps=steps,
                            floor=rnd(lo), ceiling=rnd(hi), days_of_cover=round(cover, 1), stock=stock,
                            comp_price=comp, flash_mult=fm, objective=s.objective, customer_segment=seg_name,
                            _cur=(sold_cur, rev_cur, prof_cur), _grid=(grid, u)))

        u_final = self.predict_units([o["sku"] for o in out], finals, comps_of(states), day)
        for o, st, uf in zip(out, states, u_final):
            c = self.catalog.loc[st["sku"]]
            stock = max(float(st["stock"]), 0.0)
            sold_f = min(float(uf), stock)
            sold_c, rev_c, prof_c = o.pop("_cur")
            grid, u = o.pop("_grid")
            p = o["recommended_price"]
            ea, eb = p * 0.92, p * 1.08
            ua, ub = np.interp([ea, eb], grid, u)
            local_el = float((np.log(ub) - np.log(ua)) / (np.log(eb) - np.log(ea))) if ua > 0 and ub > 0 else 0.0
            o.update(
                change_pct=round((p / o["current_price"] - 1) * 100, 2),
                exp_units_current=round(sold_c, 2), exp_units_recommended=round(sold_f, 2),
                exp_revenue_current=round(rev_c, 2), exp_revenue_recommended=round(p * sold_f, 2),
                exp_profit_current=round(prof_c, 2), exp_profit_recommended=round((p - c.cost) * sold_f, 2),
                est_elasticity=round(float(c.est_elasticity), 2), local_elasticity=round(local_el, 2),
            )
        return out

    def recommend(self, st: dict, day: date, s: Settings) -> dict:
        return self.recommend_many([st], day, s)[0]

    def demand_curve(self, st: dict, day: date, s: Settings, n: int = 40):
        sku = st["sku"]
        c = self.catalog.loc[sku]
        lo, hi = self.bounds(sku, s)
        lo, hi = lo * 0.98, hi * 1.02
        grid = np.linspace(lo, hi, n)
        u = self.predict_units([sku] * n, grid, [st["comp_price"]] * n, day)
        stock = max(float(st["stock"]), 0.0)
        sold = np.minimum(u, stock)
        return [dict(price=round(float(p), 2), units=round(float(x), 2), revenue=round(float(p * y), 2),
                     profit=round(float((p - c.cost) * y), 2)) for p, x, y in zip(grid, u, sold)]


def comps_of(states):
    return [st["comp_price"] for st in states]

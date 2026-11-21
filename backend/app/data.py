"""Synthetic marketplace data for PricePulse.

A hidden "ground truth" demand function generates 12 months of sales history.
The ML layer never sees the true parameters - it has to learn price elasticity,
competitor effects and seasonality from the history, exactly like in production.
The same ground truth is later used as the market simulator for back-testing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import date, timedelta

SEED = 42
N_SKUS = 60
HISTORY_DAYS = 365

# price range (INR), margin range, own-price elasticity, base units/day, name pool
CATEGORIES = {
    "Electronics": dict(price=(1500, 80000), margin=(0.18, 0.32), elast=(-2.6, -1.5), demand=(3, 14),
                        names=["Wireless Earbuds", "Smart Watch", "Bluetooth Speaker", "4K Action Camera", "Gaming Mouse",
                               "Mechanical Keyboard", "Power Bank 20000mAh", "Tablet 10in", "Noise-Cancel Headphones", "Webcam Full HD"]),
    "Fashion": dict(price=(400, 6000), margin=(0.35, 0.55), elast=(-2.4, -1.6), demand=(8, 30),
                    names=["Running Shoes", "Denim Jacket", "Cotton Kurta", "Leather Wallet", "Sunglasses",
                           "Backpack 30L", "Formal Shirt", "Sneakers Classic", "Hoodie Fleece", "Analog Watch"]),
    "Home": dict(price=(300, 15000), margin=(0.25, 0.42), elast=(-1.8, -1.0), demand=(5, 22),
                 names=["Air Fryer 4L", "Cotton Bedsheet Set", "LED Floor Lamp", "Mixer Grinder", "Memory Foam Pillow",
                        "Storage Organiser", "Robot Vacuum", "Electric Kettle", "Cookware Set", "Wall Clock"]),
    "Beauty": dict(price=(150, 2500), margin=(0.45, 0.65), elast=(-1.6, -0.8), demand=(12, 45),
                   names=["Vitamin C Serum", "Sunscreen SPF50", "Matte Lipstick", "Hair Dryer", "Face Wash Gel",
                          "Beard Trimmer", "Perfume 100ml", "Moisturiser Cream", "Kajal Pencil", "Hair Oil 200ml"]),
    "Grocery": dict(price=(50, 800), margin=(0.12, 0.25), elast=(-1.0, -0.4), demand=(30, 120),
                    names=["Basmati Rice 5kg", "Cold Pressed Oil 1L", "Filter Coffee 500g", "Almonds 500g", "Green Tea 100 bags",
                           "Peanut Butter 1kg", "Oats 1kg", "Masala Chai Pack", "Honey 500g", "Muesli 750g"]),
    "Sports": dict(price=(300, 9000), margin=(0.30, 0.48), elast=(-2.0, -1.2), demand=(5, 20),
                   names=["Yoga Mat", "Dumbbell Set 20kg", "Cricket Bat", "Football Size 5", "Resistance Bands",
                          "Skipping Rope", "Badminton Racquet", "Fitness Tracker", "Cycling Helmet", "Gym Gloves"]),
}
CAT_CODE = {c: i for i, c in enumerate(CATEGORIES)}
CROSS_ELASTICITY = 0.45  # demand rises when the competitor is more expensive

# Customer segments and willingness-to-pay multipliers (as specified in Project Brief)
CUSTOMER_SEGMENTS = {
    "Standard": dict(multiplier=1.00, elasticity_factor=1.00, description="General marketplace buyers with standard price sensitivity"),
    "Price-Sensitive": dict(multiplier=0.94, elasticity_factor=1.35, description="Bargain hunters and coupon-driven buyers (higher price elasticity)"),
    "Loyal": dict(multiplier=0.97, elasticity_factor=0.85, description="Repeat subscribers/members receiving exclusive pricing retention discounts"),
    "VIP": dict(multiplier=1.06, elasticity_factor=0.65, description="High-LTV premium shoppers with lower price sensitivity"),
}


def is_festival(d: date) -> bool:
    md = (d.month, d.day)
    return ((10, 18) <= md <= (11, 12)) or (md >= (12, 24)) or ((1, 13) <= md <= (1, 16)) or (md == (8, 15)) or ((11, 24) <= md <= (11, 29))


def seasonal_mult(category: str, d: date) -> float:
    """Ground-truth seasonality (calendar effect on demand)."""
    m = 1.0
    if is_festival(d):
        m *= 1.45 if category in ("Electronics", "Fashion", "Home") else 1.25
    wk = 1.0 + (0.22 if category == "Fashion" else 0.12) * (d.weekday() >= 5)
    m *= wk
    month_curve = {"Sports": {1: 1.15, 2: 1.1, 5: 0.9, 6: 0.85}, "Beauty": {12: 1.1, 2: 1.12}, "Home": {4: 1.1, 5: 1.12}}
    m *= month_curve.get(category, {}).get(d.month, 1.0)
    return m


def true_demand(base, ref_price, elast, price, comp, ref_comp, seasonal):
    """Expected units/day. Works with scalars or numpy arrays."""
    return base * (price / ref_price) ** elast * (comp / ref_comp) ** CROSS_ELASTICITY * seasonal


def make_catalog(n: int = N_SKUS, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    cats = list(CATEGORIES)
    for i in range(n):
        cat = cats[i % len(cats)]
        cfg = CATEGORIES[cat]
        lo, hi = cfg["price"]
        ref = float(np.exp(rng.uniform(np.log(lo), np.log(hi))))
        ref = round(ref / 10) * 10 - 1 if ref > 200 else round(ref)
        margin = rng.uniform(*cfg["margin"])
        cost = round(ref * (1 - margin), 2)
        name = cfg["names"][(i // len(cats)) % len(cfg["names"])]
        brand = ["Nova", "Zenith", "Aura", "Kite", "Orbit", "Pixel", "Maple", "Terra", "Vega", "Lumen"][rng.integers(0, 10)]
        rows.append(dict(
            sku=f"PP-{1001 + i}", name=f"{brand} {name}", category=cat, cat_code=CAT_CODE[cat],
            ref_price=float(ref), cost=float(cost),
            true_elasticity=float(rng.uniform(*cfg["elast"])),
            base_demand=float(rng.uniform(*cfg["demand"])),
            ref_comp=float(ref * rng.uniform(0.96, 1.06)),
            capacity=0.0,
        ))
    df = pd.DataFrame(rows)
    df["capacity"] = (df["base_demand"] * 9).round().clip(lower=40)
    return df


def _walk(rng, n, lo, hi, step):
    x = np.empty(n)
    x[0] = rng.uniform(lo + 0.15 * (hi - lo), hi - 0.15 * (hi - lo))
    for t in range(1, n):
        x[t] = np.clip(x[t - 1] + rng.normal(0, step), lo, hi)
    return x


def make_history(catalog: pd.DataFrame, days: int = HISTORY_DAYS, seed: int = SEED) -> pd.DataFrame:
    """One row per SKU per day: own price, competitor price, units sold."""
    rng = np.random.default_rng(seed + 1)
    today = date.today()
    dates = [today - timedelta(days=days - i) for i in range(days)]
    recs = []
    for _, s in catalog.iterrows():
        price_ratio = _walk(rng, days, 0.80, 1.22, 0.025)
        comp_ratio = _walk(rng, days, 0.84, 1.18, 0.02) * (s.ref_comp / s.ref_price)
        for t, d in enumerate(dates):
            price = s.ref_price * price_ratio[t]
            comp = s.ref_price * comp_ratio[t]
            lam = true_demand(s.base_demand, s.ref_price, s.true_elasticity, price, comp, s.ref_comp,
                              seasonal_mult(s.category, d))
            units = rng.poisson(lam)
            recs.append((s.sku, d, round(price, 2), round(comp, 2), int(units)))
    return pd.DataFrame(recs, columns=["sku", "date", "price", "comp_price", "units"])

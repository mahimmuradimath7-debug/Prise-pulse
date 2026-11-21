"""Demand model: per-SKU elasticity estimation + XGBoost demand forecaster.

Step 1  log-log regression per SKU -> estimated price elasticity (interpretable)
Step 2  XGBoost on price/competitor/calendar features with monotone constraints
        (higher own price never raises demand, higher competitor price never lowers it)
"""
from __future__ import annotations

import time
from datetime import date

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestRegressor
from pathlib import Path

from .data import is_festival

ARTIFACT = Path(__file__).resolve().parent.parent / "artifacts" / "demand_model.joblib"

FEATURES = ["price_ratio", "comp_ratio", "ref_price", "cost_ratio", "cat_code", "est_elasticity",
            "base_demand", "dow", "month", "dayofyear", "is_weekend", "is_festival"]
MONOTONE = {"price_ratio": -1, "comp_ratio": 1}


def date_feats(d: date) -> dict:
    return dict(dow=d.weekday(), month=d.month, dayofyear=d.timetuple().tm_yday,
                is_weekend=int(d.weekday() >= 5), is_festival=int(is_festival(d)))


def estimate_elasticities(catalog: pd.DataFrame, hist: pd.DataFrame) -> pd.DataFrame:
    """OLS of log(units) on log price ratio, log competitor ratio + calendar controls."""
    out = {}
    ref = catalog.set_index("sku")
    for sku, g in hist.groupby("sku"):
        r = ref.loc[sku]
        d = pd.to_datetime(g["date"])
        X = np.column_stack([
            np.ones(len(g)),
            np.log(g["price"].values / r.ref_price),
            np.log(g["comp_price"].values / r.ref_comp),
            (d.dt.dayofweek >= 5).astype(float).values,
            np.array([float(is_festival(x.date())) for x in d]),
        ])
        y = np.log(g["units"].values + 0.5)
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        out[sku] = (float(np.clip(beta[1], -4.5, -0.1)), float(g["units"].mean()))
    cat = catalog.copy()
    cat["est_elasticity"] = cat["sku"].map(lambda s: out[s][0])
    cat["base_demand_est"] = cat["sku"].map(lambda s: out[s][1])
    return cat


def build_frame(cat_rows: pd.DataFrame, price, comp, day: date) -> pd.DataFrame:
    """cat_rows: catalog rows (already repeated to align with price/comp arrays)."""
    price = np.asarray(price, dtype=float)
    comp = np.asarray(comp, dtype=float)
    n = len(price)
    df = pd.DataFrame({
        "price_ratio": price / cat_rows["ref_price"].values,
        "comp_ratio": comp / cat_rows["ref_price"].values,
        "ref_price": cat_rows["ref_price"].values,
        "cost_ratio": cat_rows["cost"].values / cat_rows["ref_price"].values,
        "cat_code": cat_rows["cat_code"].values,
        "est_elasticity": cat_rows["est_elasticity"].values,
        "base_demand": cat_rows["base_demand_est"].values,
    })
    for k, v in date_feats(day).items():
        df[k] = v
    return df[FEATURES]


def _train_rf(X, y, n_estimators=100):
    """Random Forest regressor baseline (Weeks 1-2 requirement from project brief)."""
    m = RandomForestRegressor(n_estimators=n_estimators, max_depth=8, min_samples_leaf=4, n_jobs=2, random_state=7)
    m.fit(X, y)
    return m


def _train_xgb(X, y, n_estimators=450):
    mono = "(" + ",".join(str(MONOTONE.get(f, 0)) for f in FEATURES) + ")"
    m = xgb.XGBRegressor(n_estimators=n_estimators, max_depth=6, learning_rate=0.05, subsample=0.85,
                         colsample_bytree=0.85, min_child_weight=3, monotone_constraints=mono,
                         tree_method="hist", n_jobs=2, random_state=7)
    m.fit(X, y)
    return m


def _hist_frame(catalog, hist):
    c = catalog.set_index("sku")
    rows = c.loc[hist["sku"].values].reset_index()
    df = pd.DataFrame({
        "price_ratio": hist["price"].values / rows["ref_price"].values,
        "comp_ratio": hist["comp_price"].values / rows["ref_price"].values,
        "ref_price": rows["ref_price"].values,
        "cost_ratio": rows["cost"].values / rows["ref_price"].values,
        "cat_code": rows["cat_code"].values,
        "est_elasticity": rows["est_elasticity"].values,
        "base_demand": rows["base_demand_est"].values,
    })
    d = pd.to_datetime(hist["date"])
    df["dow"] = d.dt.dayofweek.values
    df["month"] = d.dt.month.values
    df["dayofyear"] = d.dt.dayofyear.values
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    df["is_festival"] = [int(is_festival(x.date())) for x in d]
    return df[FEATURES]


def train(catalog: pd.DataFrame, hist: pd.DataFrame, holdout_days: int = 60):
    """Train, evaluate on the last `holdout_days`, then refit on everything."""
    t0 = time.time()
    cat = estimate_elasticities(catalog, hist)
    hist = hist.sort_values(["date", "sku"]).reset_index(drop=True)
    X = _hist_frame(cat, hist)
    y = np.log1p(hist["units"].values)
    cutoff = sorted(hist["date"].unique())[-holdout_days]
    tr = (hist["date"] < cutoff).values
    actual = hist["units"].values[~tr]

    # Baseline 1: Naive SKU historical mean
    sku_mean = hist[tr].groupby("sku")["units"].mean()
    base_pred = hist[~tr]["sku"].map(sku_mean).values
    baseline_mae = float(np.mean(np.abs(base_pred - actual)))

    # Baseline 2: Random Forest Regressor (Weeks 1-2 Project Brief requirement)
    m_rf_eval = _train_rf(X[tr], y[tr])
    pred_rf = np.expm1(m_rf_eval.predict(X[~tr])).clip(min=0)
    rf_mae = float(np.mean(np.abs(pred_rf - actual)))
    rf_metrics = dict(
        mae=round(rf_mae, 2),
        rmse=round(float(np.sqrt(np.mean((pred_rf - actual) ** 2))), 2),
        wmape=round(float(np.abs(pred_rf - actual).sum() / max(actual.sum(), 1)), 3),
        r2=round(float(1 - ((actual - pred_rf) ** 2).sum() / ((actual - actual.mean()) ** 2).sum()), 3),
        target_met=bool(rf_mae < 8.0),
    )

    # Primary Model: XGBoost Regressor with Monotone Constraints (Week 3 Project Brief requirement)
    m_eval = _train_xgb(X[tr], y[tr])
    pred = np.expm1(m_eval.predict(X[~tr])).clip(min=0)
    mae = float(np.mean(np.abs(pred - actual)))
    xgb_metrics = dict(
        mae=round(mae, 2),
        rmse=round(float(np.sqrt(np.mean((pred - actual) ** 2))), 2),
        wmape=round(float(np.abs(pred - actual).sum() / max(actual.sum(), 1)), 3),
        r2=round(float(1 - ((actual - pred) ** 2).sum() / ((actual - actual.mean()) ** 2).sum()), 3),
        target_met=bool(mae < 8.0),
    )

    metrics = dict(
        mae=mae,
        rmse=xgb_metrics["rmse"],
        wmape=xgb_metrics["wmape"],
        r2=xgb_metrics["r2"],
        baseline_mae=baseline_mae,
        holdout_days=holdout_days, train_rows=int(tr.sum()), test_rows=int((~tr).sum()),
        models=dict(
            random_forest=rf_metrics,
            xgboost=xgb_metrics,
        ),
        rf_mae=rf_metrics["mae"],
        xgb_mae=xgb_metrics["mae"],
    )
    metrics["mae_improvement_vs_baseline"] = 1 - metrics["mae"] / metrics["baseline_mae"]
    metrics["mae_improvement_vs_rf"] = max(0.0, (rf_mae - mae) / max(rf_mae, 1e-6))
    model = _train_xgb(X, y)
    rf_model = _train_rf(X, y)
    imp = dict(zip(FEATURES, [float(v) for v in model.feature_importances_]))
    rf_imp = dict(zip(FEATURES, [float(v) for v in rf_model.feature_importances_]))
    # elasticity quality: estimated vs ground truth (only possible because data is synthetic)
    el = cat[["sku", "est_elasticity", "true_elasticity"]]
    metrics["elasticity_mae_vs_truth"] = float(np.mean(np.abs(el.est_elasticity - el.true_elasticity)))
    metrics["trained_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    metrics["train_seconds"] = round(time.time() - t0, 1)
    bundle = dict(model=model, rf_model=rf_model, catalog=cat, metrics=metrics, importance=imp, rf_importance=rf_imp)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, ARTIFACT)
    return bundle


def load():
    if ARTIFACT.exists():
        try:
            return joblib.load(ARTIFACT)
        except Exception:
            return None
    return None

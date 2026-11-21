import os, tempfile
os.environ["PRICEPULSE_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
from fastapi.testclient import TestClient
from app.main import app


def test_end_to_end():
    with TestClient(app) as c:
        assert c.get("/api/health").json()["status"] == "ok"
        prods = c.get("/api/products").json()["products"]
        assert len(prods) >= 50
        sku = prods[0]["sku"]
        d = c.get(f"/api/products/{sku}").json()
        rec = d["recommendation"]
        assert rec["floor"] <= rec["recommended_price"] <= rec["ceiling"] * 1.16
        assert len(rec["steps"]) == 5
        curve = c.get(f"/api/products/{sku}/demand-curve").json()["curve"]
        assert curve[0]["units"] >= curve[-1]["units"]          # demand falls as price rises (monotone model)
        assert c.post(f"/api/products/{sku}/apply").status_code == 200
        f = c.post("/api/stream/flash", json={"sku": sku, "orders": 60}).json()
        assert f["flash"] and f["multiplier"] > 1
        assert c.get("/api/dashboard").json()["skus"] == len(prods)
        bt = c.post("/api/simulate/backtest", json={"days": 7}).json()
        assert "revenue" in bt["summary"]
        r = c.post(f"/api/rl/{sku}/train?episodes=200").json()
        assert r["eval"]["rl_reward"] > 0
        # Test Customer Segmentation
        d_seg = c.get(f"/api/products/{sku}?segment=Price-Sensitive").json()
        assert len(d_seg["recommendation"]["steps"]) == 6
        assert any("Customer segment" in s["name"] for s in d_seg["recommendation"]["steps"])

        # Test Model Benchmark (Random Forest vs XGBoost)
        model_m = c.get("/api/model/metrics").json()
        assert model_m["metrics"]["mae"] < 8
        assert "models" in model_m["metrics"]
        assert "random_forest" in model_m["metrics"]["models"]
        assert "xgboost" in model_m["metrics"]["models"]

        # Test Deep Q-Network (DQN) RL Agent
        r_dqn = c.post(f"/api/rl/{sku}/train?episodes=200&algo=dqn").json()
        assert r_dqn["algo"] == "dqn"
        assert r_dqn["eval"]["rl_reward"] > 0

        c.post("/api/reset")

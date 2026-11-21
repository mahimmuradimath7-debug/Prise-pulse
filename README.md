# PricePulse: Adaptive Dynamic Pricing & Revenue Optimization Engine

Full-stack implementation of **Project 2** from the *AI Internship Master Portfolio 2026-2027*.
A FastAPI + XGBoost/Random Forest backend, an interactive React dashboard, and a Streamlit dashboard that recommend, explain, and apply product prices in real time.

---

## Quick Start

### Option A: One Command (FastAPI + React Dashboard)

```bash
./run.sh          # Windows: run.bat
```
Open **http://localhost:8000**. Interactive API documentation is available at **http://localhost:8000/docs**.

### Option B: Streamlit Dashboard (Project Brief Specification)

```bash
streamlit run streamlit_app.py
```
Open **http://localhost:8501** for the interactive Streamlit dashboard featuring model benchmarking, customer segmentation, demand curves, and Deep Q-Learning agent training.

### Option C: Docker (Full Stack)

```bash
docker compose up --build
```
For production deployment with Redis and Kafka:
```bash
docker compose -f deploy/aws/docker-compose.prod.yml up --build
```

### Option D: 1-Click Free Cloud Hosting via GitHub (Render / Railway)

Connect your GitHub repository to [Render.com](https://render.com) or [Railway.app](https://railway.app):
1. Sign in to **Render.com** with GitHub.
2. Click **New +** -> **Web Service** -> select `Prise-pulse`.
3. Choose **Docker** environment (it auto-detects `render.yaml` and `Dockerfile`).
4. Click **Deploy Web Service**. You will receive a live public URL (e.g. `https://prise-pulse.onrender.com`).

### Option E: Development Mode (Hot-Reload React UI)

```bash
cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000  # Terminal 1
cd frontend && npm install && npm run dev                                       # Terminal 2 -> http://localhost:5173
npm run build                                                                   # Rebuilds bundle into backend/static
```

Tests: `cd backend && pytest -v`

---

## Features & Project Brief Compliance

| Feature / Brief Item | Implementation in PricePulse | Status |
|---|---|:---:|
| **Random Forest Regressor (Weeks 1-2)** | Evaluated on holdout set (`MAE ~4.98`, `R² 0.93`); displayed side-by-side in Model Benchmark | ✅ Implemented |
| **XGBoost Regressor (Week 3)** | Demand model with monotone constraints on own price (-1) and competitor price (+1). Holdout `MAE ~4.35` (Target `< 8` met) | ✅ Implemented |
| **Price Elasticity Modeling** | Per-SKU log-log OLS regression estimating elasticity curves against ground truth | ✅ Implemented |
| **Competitor Price Integration** | Simulated live competitor feed + `GET /api/competitors/{sku}` with configurable 70/30 blending | ✅ Implemented |
| **Customer Segmentation** | Personalized segment multipliers: `Standard` (1.0x), `Price-Sensitive` (0.94x), `Loyal` (0.97x), `VIP` (1.06x) | ✅ Implemented |
| **Sliding-Window Aggregation** | 5-minute windows sliding every 1 minute (`stream.py`) with spike detection | ✅ Implemented |
| **Flash-Sale Detection & Multiplier** | Real-time spike detection ($\ge 3\times$ baseline) applying up to $1.25\times$ emergency surge pricing | ✅ Implemented |
| **Inventory-Based Guardrails** | Short cover (< 3 days) raises price up to +8%; excess stock (> 30 days) discounts up to -8% | ✅ Implemented |
| **Deep Q-Learning (DQN) RL Agent** | Continuous-state 2-layer Neural Network with Experience Replay and Target Network (`rl.py`) | ✅ Implemented |
| **Dashboards** | Both **React + Recharts** (served on `:8000`) and **Streamlit** (`streamlit_app.py` on `:8501`) | ✅ Implemented |
| **Redis Caching** | Transparent Redis caching with automatic in-memory fallback (`cache.py`) | ✅ Implemented |
| **Event Streaming (Kafka / MSK)** | Kafka event producer & consumer for real-time order stream (`kafka_stream.py`) | ✅ Implemented |
| **Apache Flink CEP** | Production Flink stream processing script with Complex Event Processing (`streaming/flink_pricing_job.py`) | ✅ Implemented |
| **AWS Cloud Deployment** | AWS SAM template (Lambda + API Gateway + S3 + CloudWatch alarms) and EC2 script in `deploy/aws/` | ✅ Implemented |

---

## How a Price is Produced (`backend/app/engine.py`)

1. **ML Optimum**: XGBoost forecasts units for 48 candidate prices; the best one for the chosen objective wins (`balanced`, `growth`, `revenue`, or `profit`). Monotone constraints guarantee demand never rises with own price.
2. **Competitor Blend**: 70% model + 30% competitor price (configurable).
3. **Customer Segment Personalization**: Custom price adjustments based on customer segment (`Standard`, `Price-Sensitive`, `Loyal`, `VIP`).
4. **Inventory Rule**: Under 3 days of stock cover raises price up to +8%; over 30 days lowers price up to -8%.
5. **Flash-Sale Multiplier**: Up to $1.25\times$ when order velocity $\ge 3\times$ baseline.
6. **Guardrails**: Margin floor (min margin rule), price ceiling, and maximum step limit per update.

---

## Project Structure

```
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI REST endpoints, background loops, lifespan
│   │   ├── model.py           # Random Forest baseline + XGBoost monotone demand model
│   │   ├── engine.py          # Multi-step dynamic pricing logic and guardrails
│   │   ├── data.py            # Synthetic market catalog, seasonality, customer segments
│   │   ├── stream.py          # 5-min sliding window aggregator & flash detector
│   │   ├── rl.py              # Deep Q-Network (DQN) & Tabular Q-learning agents
│   │   ├── cache.py           # Redis caching with in-memory fallback
│   │   ├── kafka_stream.py    # Apache Kafka / Amazon MSK event streaming
│   │   ├── lambda_handler.py  # Serverless AWS Lambda handler (Mangum)
│   │   └── db.py              # SQLite price changes, state, and alert logs
│   ├── static/                # Prebuilt React dashboard (served by FastAPI)
│   └── tests/test_api.py      # End-to-end pytest suite
├── frontend/                  # React 18 + Vite + Recharts source code
├── deploy/aws/
│   ├── template.yaml          # AWS SAM Serverless template (Lambda + API Gateway + S3 + CloudWatch)
│   ├── ec2-setup.sh           # AWS EC2 t2.micro automated setup script
│   └── docker-compose.prod.yml# Full production stack (PricePulse + Redis + Kafka + Zookeeper)
├── streaming/
│   └── flink_pricing_job.py   # Apache Flink CEP job for sub-second flash sale detection
├── streamlit_app.py           # Streamlit interactive dashboard (as requested in Project Brief)
├── Dockerfile                 # Multi-stage production container
└── run.sh / run.bat           # One-command execution scripts
```

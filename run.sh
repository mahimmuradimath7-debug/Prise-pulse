#!/usr/bin/env bash
# One-command start (Linux / macOS). Needs Python 3.10+. Node is NOT required: the built UI is bundled.
set -e
cd "$(dirname "$0")/backend"
if [ ! -d .venv ]; then
  echo ">> Creating virtual environment and installing dependencies (first run only)..."
  python3 -m venv .venv
  . .venv/bin/activate
  pip install --upgrade pip -q
  pip install -r requirements.txt -q
else
  . .venv/bin/activate
fi
echo ">> PricePulse running at http://localhost:8000   (API docs: http://localhost:8000/docs)"
exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

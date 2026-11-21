@echo off
REM One-command start (Windows). Needs Python 3.10+. Node is NOT required.
cd /d "%~dp0backend"
if not exist .venv (
  echo ^>^> Creating virtual environment and installing dependencies (first run only)...
  python -m venv .venv
  call .venv\Scripts\activate.bat
  python -m pip install --upgrade pip -q
  pip install -r requirements.txt -q
) else (
  call .venv\Scripts\activate.bat
)
echo ^>^> PricePulse running at http://localhost:8000   (API docs: http://localhost:8000/docs)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

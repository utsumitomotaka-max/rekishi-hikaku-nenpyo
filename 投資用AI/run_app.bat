@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check -r requirements.txt
)
start "" /b cmd /c "ping -n 6 127.0.0.1 >nul & start http://localhost:8501"
.venv\Scripts\python.exe -m streamlit run app.py --server.headless true

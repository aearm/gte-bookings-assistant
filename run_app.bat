@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo The app is not installed yet. Double-click setup.bat first.
    pause
    exit /b 1
)
rem Already running (e.g. started automatically with Windows)? Just open it.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue) { Start-Process http://localhost:8501; exit 0 } else { exit 1 }"
if %errorlevel%==0 exit /b 0
call .venv\Scripts\activate
echo Starting Bookings Assistant... your browser will open. Keep this window open while using the app.
streamlit run app.py

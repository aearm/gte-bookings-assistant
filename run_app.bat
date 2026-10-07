@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\activate.bat (
    echo The app is not installed yet. Double-click setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate
echo Starting Bookings Assistant... your browser will open. Keep this window open while using the app.
streamlit run app.py

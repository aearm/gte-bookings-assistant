@echo off
rem Opens Bookings Assistant in the browser, starting it first if it isn't running.
rem   run_app.bat           the app (http://localhost:8600)
rem   run_app.bat classic   the previous app (Streamlit, http://localhost:8501)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
    echo The app is not installed yet. Double-click setup.bat first.
    pause
    exit /b 1
)
rem numpy's maths library would reserve ~30 MB per CPU core for maths the app never does
set OPENBLAS_NUM_THREADS=1
if /i "%~1"=="classic" goto classic
.venv\Scripts\python.exe start_api.py --open
exit /b %errorlevel%

:classic
rem Already running (e.g. started automatically with Windows)? Just open it.
powershell -NoProfile -Command "if (Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue) { Start-Process http://localhost:8501; exit 0 } else { exit 1 }"
if %errorlevel%==0 exit /b 0
call .venv\Scripts\activate
echo Starting Bookings Assistant... your browser will open. Keep this window open while using the app.
streamlit run app.py

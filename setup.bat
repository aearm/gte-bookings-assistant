@echo off
rem Windows setup: double-click this file - nothing to answer. It installs everything the app needs
rem (Python if missing, libraries, ADOMD.NET, the web app), creates a desktop shortcut, starts the app
rem with Windows and opens it in the browser. No admin rights needed. Safe to run again to repair or update.
rem Options (from a command prompt): -NoStart, -NoAutostart, -Classic (the previous app).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1" %*
if errorlevel 1 (
    pause
    exit /b 1
)
echo.
echo This window closes by itself in 20 seconds.
"%SystemRoot%\System32\timeout.exe" /t 20 >nul

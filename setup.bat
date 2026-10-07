@echo off
rem Windows setup: double-click this file. It installs everything the app needs
rem (Python if missing, libraries, ADOMD.NET) and creates a desktop shortcut.
rem No admin rights needed. Safe to run again to repair or update.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup_windows.ps1"
pause

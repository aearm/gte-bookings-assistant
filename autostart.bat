@echo off
rem Start Bookings Assistant automatically in the background.
rem   autostart.bat              when you sign in to Windows
rem   autostart.bat -AtStartup   when the computer starts (asks for your Windows password once)
rem   autostart.bat -Remove      stop starting automatically
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart.ps1" %*
pause

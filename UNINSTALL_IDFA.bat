@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall.ps1" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%

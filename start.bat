@echo off
REM ===========================================================================
REM  Legacy launcher - kept so existing shortcuts and docs keep working.
REM  All logic now lives in start_windows.bat; this file only delegates.
REM ===========================================================================
echo Redirecting to start_windows.bat...
echo.
call "%~dp0start_windows.bat"

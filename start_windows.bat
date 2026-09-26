@echo off
setlocal enabledelayedexpansion

REM ===========================================================================
REM  Intelligent Digital Forensic AI Assistant - Windows launcher
REM
REM  Starts Ollama, the FastAPI backend and the Vite frontend, waits for each
REM  port to bind, and prints the tail of each log if something failed.
REM
REM  Every service runs in its own window AND tees to logs\ so that failures
REM  are visible even when the window is not.
REM ===========================================================================

REM Always run from the repository root, whatever the caller's CWD was.
cd /d "%~dp0"

set "ROOT=%CD%"
set "VENV_PY=%ROOT%\venv\Scripts\python.exe"
set "FE_DIR=%ROOT%\frontend"
set "VITE=%FE_DIR%\node_modules\.bin\vite.cmd"
set "LOGDIR=%ROOT%\logs"

if not exist "%LOGDIR%" mkdir "%LOGDIR%" >nul 2>&1

echo Starting Intelligent Digital Forensic AI Assistant (Windows)...
echo.

set "MISSING=0"

REM --- 1. Ollama -----------------------------------------------------------
REM Ollama on Windows usually auto-starts as a desktop app. Launching a second
REM "ollama serve" against a live port only prints "address already in use".
call :isListening 11434
if "%ERRORLEVEL%"=="0" (
    echo [ok]   Ollama already listening on 11434 - not starting another.
) else (
    where ollama >nul 2>&1
    if errorlevel 1 (
        echo [WARN] ollama is not on PATH. Install it from https://ollama.com
        echo        or start it by hand, otherwise AI queries will fail.
    ) else (
        echo [....] Starting Ollama on 11434...
        start "IDFA Ollama" cmd /c "ollama serve > ""%LOGDIR%\ollama.log"" 2>&1"
    )
)

REM --- 2. Backend ----------------------------------------------------------
echo.
if exist "%VENV_PY%" (
    echo [....] Starting backend on 8000...
    REM All paths below are RELATIVE on purpose. The parent already did
    REM "cd /d %~dp0" and the child inherits that CWD, so no path needs
    REM quoting. Nesting quotes inside cmd /c "..." makes "start" mangle
    REM them - it turned the python path into a script argument and gave
    REM "SyntaxError: Non-UTF-8 code ... in python.exe".
    REM "python -m uvicorn" is used rather than activate.bat + uvicorn: it does
    REM not depend on activation PATH munging and works even if AutoRun is off.
    start "IDFA Backend" cmd /c "set PYTHONPATH=.&&venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 > logs\backend.log 2>&1"
) else (
    echo [FAIL] Virtual environment not found:
    echo        %VENV_PY%
    echo        Run setup_windows.bat first.
    set "MISSING=1"
)

REM --- 3. Frontend ---------------------------------------------------------
echo.
if exist "%VITE%" (
    echo [....] Starting frontend on 3000...
    start "IDFA Frontend" cmd /c "cd /d frontend && node_modules\.bin\vite.cmd > ..\logs\frontend.log 2>&1"
) else (
    echo [FAIL] Frontend dependencies missing: %VITE%
    echo        Run setup_windows.bat, or: cd frontend ^&^& npm install
    echo        Use npm, not yarn. The global yarn 1.x on Windows cannot
    echo        resolve vite and dies with "vite is not recognized".
    set "MISSING=1"
)

if "%MISSING%"=="1" goto :summary

REM --- 4. Wait for the ports to bind ---------------------------------------
echo.
echo Waiting for services to bind their ports...
set /a TRIES=0
set "READY="

:wait
set /a TRIES+=1
if !TRIES! gtr 30 goto :summary
set "READY="
call :isListening 8000
if "%ERRORLEVEL%"=="0" set "READY=!READY!8000 "
call :isListening 3000
if "%ERRORLEVEL%"=="0" set "READY=!READY!3000 "
if "!READY!"=="8000 3000 " goto :summary
REM "ping" is used as the sleep: unlike "timeout" it does not need a console
REM stdin, so it still works when output is redirected to a file or pipe.
ping -n 2 127.0.0.1 >nul
goto :wait

:summary
echo.
echo ------------------------------------------------------------------
if "!READY!"=="8000 3000 " (
    echo All services are up.
) else (
    if "%MISSING%"=="0" echo WARNING: not every service came up. Detected: !READY!
    echo.
    echo Last lines of each log ^(folder: logs^):
    for %%L in (backend frontend) do (
        if exist "%LOGDIR%\%%L.log" (
            echo.
            echo --- %%L.log ---
            powershell -NoProfile -Command "Get-Content -Tail 12 '%LOGDIR%\%%L.log'" 2>nul
        )
    )
)
echo.
echo   Frontend:  http://localhost:3000
echo   Backend:   http://localhost:8000
echo   API docs:  http://localhost:8000/docs
echo   Health:    http://localhost:8000/api/status
echo.
echo   The dev server is pinned to port 3000 in frontend\vite.config.js. If
echo   3000 is busy Vite falls back to 5173 - use the URL printed in the
echo   IDFA Frontend window, not the one above.
echo.
pause
exit /b 0

REM ---------------------------------------------------------------------------
REM  :isListening <port>   ERRORLEVEL 0 if something is listening on that port.
REM  Uses netstat, not PowerShell: it is far cheaper to poll in a loop.
REM ---------------------------------------------------------------------------
:isListening
netstat -ano | findstr "LISTENING" | findstr /C:":%~1 " >nul 2>&1
exit /b %ERRORLEVEL%

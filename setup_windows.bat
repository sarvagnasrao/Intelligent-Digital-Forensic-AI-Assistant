@echo off
setlocal EnableDelayedExpansion

echo.
echo ======================================================
echo    Intelligent Digital Forensic AI Assistant Setup (Windows)
echo ======================================================
echo.

:: 1. Prerequisites check
echo [1/6] Checking prerequisites...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python 3 is not installed or not in your PATH.
    echo Please install Python 3 from python.org and try again.
    exit /b 1
) else (
    echo [OK] Python found.
)

node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Node.js is not installed or not in your PATH.
    echo Please install Node.js from nodejs.org and try again.
    exit /b 1
) else (
    echo [OK] Node.js found.
)

ollama --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Ollama is not installed.
    echo Download from: https://ollama.com
    echo Continuing - ensure Ollama is running before starting the app.
) else (
    echo [OK] Ollama found.
)

:: 2. .env setup
echo.
echo [2/6] Environment configuration...
if not exist ".env" (
    if exist ".env.example" (
        copy .env.example .env >nul
        echo [OK] Created .env from .env.example
        echo [WARNING] Edit .env and set a real SECRET_KEY before use in production.
    ) else (
        echo [ERROR] No .env or .env.example found.
        exit /b 1
    )
) else (
    echo [OK] .env already exists.
)

:: 3. Python virtual environment
echo.
echo [3/6] Python virtual environment...
if not exist "venv" (
    python -m venv venv
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)

:: 4. Python packages
echo.
echo [4/6] Installing Python packages...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
REM vendor\ is deliberately NOT in git (.gitignore) - it only exists on a
REM machine that was handed the offline kit. Installing with --no-index
REM against a directory that is not there fails outright, which is exactly
REM what a fresh git clone used to do. So: use the wheels when they are
REM present, and fall back to a normal online install when they are not.
set "VENDOR_OK=0"
if exist "vendor\python" (
    dir /b "vendor\python\*.whl" >nul 2>&1
    if not errorlevel 1 set "VENDOR_OK=1"
)

if "%VENDOR_OK%"=="1" (
    echo [OK]   vendor\python found - installing offline, no network needed.
    pip install --no-index --find-links=vendor\python -r requirements.txt
) else (
    echo [OK]   No vendor\python - installing from PyPI. Internet required.
    pip install -r requirements.txt
)

echo.
echo Downloading spaCy NLP models...
if "%VENDOR_OK%"=="1" (
    if exist "vendor\python\en_core_web_sm-3.7.1.tar.gz" pip install --no-index --find-links=vendor\python vendor\python\en_core_web_sm-3.7.1.tar.gz
    if exist "vendor\python\en_core_web_lg-3.7.1.tar.gz" pip install --no-index --find-links=vendor\python vendor\python\en_core_web_lg-3.7.1.tar.gz
) else (
    python -m spacy download en_core_web_sm
    python -m spacy download en_core_web_lg
)

:: 5. Frontend setup
echo.
echo [5/6] Installing frontend dependencies...
cd frontend
REM npm, NOT yarn. start_windows.bat warns about this explicitly: the global
REM yarn 1.x on Windows cannot resolve vite and dies with
REM "vite is not recognized". frontend\package-lock.json is the lockfile.
call npm install
cd ..

REM 6. Migrations
REM init_db() in backend/database.py uses Base.metadata.create_all, which
REM CREATES missing tables but never ADDS a column to a table that already
REM exists. So an existing forensic.db keeps whatever schema it had, and a
REM backend started against it fails with "no such column:
REM ingestion_jobs.eta_seconds". migrate_all.py is what adds those columns.
REM It is idempotent - running it twice is a no-op - so it is safe here even
REM on a brand new install, where it simply has nothing to do.
echo.
echo [6/6] Running database migrations...
call venv\Scripts\activate.bat
set "PYTHONPATH=."
python backend\migrate_all.py
if errorlevel 1 (
    echo [WARN] A migration reported a problem. The app will still start, but
    echo        re-run 'set PYTHONPATH=. ^&^& python backend\migrate_all.py'
    echo        before trusting the queue or system-health page.
) else (
    echo [OK] Migrations complete.
)

echo.
echo ======================================================
echo Setup Complete!
echo Run 'start_windows.bat' to launch the application.
echo ======================================================
pause

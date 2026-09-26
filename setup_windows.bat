@echo off
setlocal EnableDelayedExpansion

echo.
echo ======================================================
echo    Intelligent Digital Forensic AI Assistant Setup (Windows)
echo ======================================================
echo.

:: 1. Prerequisites check
echo [1/5] Checking prerequisites...
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
echo [2/5] Environment configuration...
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
echo [3/5] Python virtual environment...
if not exist "venv" (
    python -m venv venv
    echo [OK] Virtual environment created.
) else (
    echo [OK] Virtual environment already exists.
)

:: 4. Python packages
echo.
echo [4/5] Installing Python packages...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip setuptools wheel
pip install --no-index --find-links=vendor\python -r requirements.txt

echo.
echo Downloading spaCy NLP models...
pip install --no-index --find-links=vendor\python vendor\python\en_core_web_sm-3.7.1.tar.gz
pip install --no-index --find-links=vendor\python vendor\python\en_core_web_lg-3.7.1.tar.gz

:: 5. Frontend setup
echo.
echo [5/5] Installing frontend dependencies...
cd frontend
yarn install
cd ..

echo.
echo ======================================================
echo Setup Complete!
echo Run 'start_windows.bat' to launch the application.
echo ======================================================
pause

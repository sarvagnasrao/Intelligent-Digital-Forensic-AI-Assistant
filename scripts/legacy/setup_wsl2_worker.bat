@echo off
REM ============================================================
REM IDFA WSL2 Forensic Worker - Automated Setup
REM Run as Administrator for Docker permissions
REM ============================================================

echo.
echo ============================================================
echo  IDFA WSL2 Forensic Worker Setup
echo ============================================================
echo.

REM Check Ubuntu by trying to run a command in it
wsl -d Ubuntu -- bash -c "echo 'Ubuntu exists'" >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Ubuntu not accessible in WSL2.
    echo Attempting to install Ubuntu...
    wsl --install -d Ubuntu
    echo.
    echo [ACTION REQUIRED] Please REBOOT Windows now, then run this script again.
    pause
    exit /b 1
)

echo [OK] Ubuntu found in WSL2
echo.

REM Check if Ubuntu is stopped - start it
wsl -d Ubuntu -- bash -c "echo 'Ubuntu started'" >nul 2>&1
timeout /t 3 >nul

REM Check if already initialized
wsl -d Ubuntu -- bash -c "whoami" 2>nul | findstr "." >nul
if errorlevel 1 (
    echo [INFO] Ubuntu needs first-time initialization.
    echo Opening Ubuntu terminal for setup...
    start "" wsl -d Ubuntu
    echo.
    echo [ACTION REQUIRED] Complete Ubuntu setup (create username/password), then run this script again.
    pause
    exit /b 1
)

echo [OK] Ubuntu initialized
echo.

REM ============================================================
REM Phase 1: System Dependencies (requires sudo password)
REM ============================================================
echo.
echo ============================================================
echo Phase 1: Installing system dependencies (sudo required)
echo ============================================================
echo.

wsl -d Ubuntu -- bash -c "sudo apt update"
wsl -d Ubuntu -- bash -c "sudo apt install -y python3-venv python3-pip libtsk3-dev libewf-dev tesseract-ocr docker.io docker-compose-plugin"

if errorlevel 1 (
    echo [ERROR] System dependency installation failed.
    echo Please run manually in Ubuntu terminal:
    echo   sudo apt update && sudo apt install -y python3-venv python3-pip libtsk3-dev libewf-dev tesseract-ocr docker.io docker-compose-plugin
    pause
    exit /b 1
)

echo [OK] System dependencies installed
echo.

REM ============================================================
REM Phase 2: Python Virtual Environment & Packages
REM ============================================================
echo.
echo ============================================================
echo Phase 2: Setting up Python environment
echo ============================================================
echo.

wsl -d Ubuntu -- bash -c "python3 -m venv ~/idfa-worker-venv"
wsl -d Ubuntu -- bash -c "source ~/idfa-worker-venv/bin/activate && pip install --upgrade pip"
wsl -d Ubuntu -- bash -c "source ~/idfa-worker-venv/bin/activate && pip install pytsk3 pyewf fastapi uvicorn[standard] ollama qdrant-client sentence-transformers spacy python-multipart httpx pydantic pydantic-settings pyyaml"
wsl -d Ubuntu -- bash -c "source ~/idfa-worker-venv/bin/activate && python -m spacy download en_core_web_sm"

if errorlevel 1 (
    echo [ERROR] Python package installation failed.
    echo Please run manually in Ubuntu terminal:
    echo   python3 -m venv ~/idfa-worker-venv
    echo   source ~/idfa-worker-venv/bin/activate
    echo   pip install --upgrade pip
    echo   pip install pytsk3 pyewf fastapi uvicorn[standard] ollama qdrant-client sentence-transformers spacy python-multipart httpx pydantic pydantic-settings pyyaml
    echo   python -m spacy download en_core_web_sm
    pause
    exit /b 1
)

echo [OK] Python environment ready
echo.

REM ============================================================
REM Phase 3: Ollama & Qdrant
REM ============================================================
echo.
echo ============================================================
echo Phase 3: Installing Ollama & Qdrant
echo ============================================================
echo.

wsl -d Ubuntu -- bash -c "curl -fsSL https://ollama.com/install.sh | sh"
wsl -d Ubuntu -- bash -c "ollama serve &"
timeout /t 10 >nul
wsl -d Ubuntu -- bash -c "ollama pull phi3:mini"
wsl -d Ubuntu -- bash -c "docker run -d -p 6333:6333 --name qdrant qdrant/qdrant"

if errorlevel 1 (
    echo [WARNING] Ollama/Qdrant setup had issues.
    echo Please run manually in Ubuntu terminal:
    echo   ollama serve &
    echo   ollama pull phi3:mini
    echo   docker run -d -p 6333:6333 --name qdrant qdrant/qdrant
)

echo [OK] AI services configured
echo.

REM ============================================================
REM Phase 4: Copy Worker Code & Start
REM ============================================================
echo.
echo ============================================================
echo Phase 4: Deploying Worker
echo ============================================================
echo.

wsl -d Ubuntu -- bash -c "cp -r /mnt/c/Users/%USERNAME%/Documents/Final_Project/worker ~/idfa-worker 2>/dev/null || cp -r /mnt/e/Users/%USERNAME%/Documents/Final_Project/worker ~/idfa-worker"
wsl -d Ubuntu -- bash -c "cd ~/idfa-worker && source ~/idfa-worker-venv/bin/activate && python main.py"

echo.
echo ============================================================
echo Worker should now be running at http://localhost:8000
echo Test with: curl http://localhost:8000/health
echo ============================================================
pause
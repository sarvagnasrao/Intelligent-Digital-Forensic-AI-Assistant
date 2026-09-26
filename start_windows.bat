@echo off
echo Starting Intelligent Digital Forensic AI Assistant (Windows)...
echo.

:: Start Ollama
start "IDFA Ollama" cmd /c "ollama serve"

:: Start Backend in a separate window
start "IDFA Backend" cmd /c "call venv\Scripts\activate.bat && set PYTHONPATH=. && uvicorn backend.main:app --host 0.0.0.0 --port 8000"

:: Start Frontend in a separate window (must cd into frontend for Yarn v4)
start "IDFA Frontend" cmd /c "cd frontend && yarn dev"

echo.
echo All services started in separate windows!
echo Frontend: http://localhost:5173
echo Backend:  http://localhost:8000
echo Docs:     http://localhost:8000/docs
echo.
pause

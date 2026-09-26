@echo off
echo Starting Cognitive Forensic Investigator...

echo Starting Ollama...
start "Ollama" cmd /c "ollama serve"

echo Starting Backend...
start "Backend" cmd /c "set PYTHONPATH=. && .\venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

echo Starting Frontend...
start "Frontend" cmd /c "cd frontend && yarn dev"

echo.
echo All services have been started in separate windows!
echo Frontend is available at: http://localhost:3000
echo Backend is available at: http://localhost:8000
echo.
pause

#!/usr/bin/env bash
# ===========================================================================
#  Intelligent Digital Forensic AI Assistant - Linux / macOS launcher
#
#  Starts Ollama, the FastAPI backend and the Vite frontend, then verifies that
#  each port actually came up.
# ===========================================================================
set -uo pipefail

# Always run from the repository root, whatever the caller's CWD was.
cd "$(dirname "$0")" || exit 1
ROOT="$PWD"
VENV_PY="$ROOT/venv/bin/python"
FE_DIR="$ROOT/frontend"
VITE="$FE_DIR/node_modules/.bin/vite"

READY=""

port_listening() {  # returns 0 if something is listening on $1
    if command -v ss >/dev/null 2>&1; then
        ss -ltn "sport = :$1" 2>/dev/null | grep -q LISTEN
    else
        (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null && exec 3<&- 3>&- && return 0
        return 1
    fi
}

mark_ready() {  # append $1 to READY if that port is listening
    port_listening "$1" && READY="$READY $1"
    return 0
}

echo "Starting Intelligent Digital Forensic AI Assistant..."
echo

# --- 1. Ollama --------------------------------------------------------------
if port_listening 11434; then
    echo "[ok]   Ollama already listening on 11434 - not starting another."
elif command -v ollama >/dev/null 2>&1; then
    echo "[....] Starting Ollama..."
    ollama serve &>/dev/null &
else
    echo "[WARN] 'ollama' not found. Install from https://ollama.com or start it"
    echo "       manually, otherwise AI queries will fail."
fi

# --- 2. Backend -------------------------------------------------------------
echo
if [ -x "$VENV_PY" ]; then
    echo "[....] Starting backend on port 8000..."
    PYTHONPATH="$ROOT" "$VENV_PY" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
else
    echo "[FAIL] Virtual environment not found at: $VENV_PY"
    echo "       Run ./setup.sh first."
fi

# --- 3. Frontend ------------------------------------------------------------
echo
if [ -x "$VITE" ]; then
    echo "[....] Starting frontend on port 3000..."
    (cd "$FE_DIR" && "$VITE") &
elif command -v npm >/dev/null 2>&1; then
    echo "[WARN] vite binary missing, falling back to 'npm run dev'."
    (cd "$FE_DIR" && npm run dev) &
else
    echo "[FAIL] Frontend dependencies missing and npm unavailable."
    echo "       Run ./setup.sh first."
fi

# --- 4. Wait for the ports to come up ---------------------------------------
echo
echo "Waiting for services to bind their ports..."
for _ in $(seq 1 20); do
    [ -z "${READY##*8000*}" ] || mark_ready 8000
    [ -z "${READY##*3000*}" ] || mark_ready 3000
    if [ "$READY" = " 8000 3000" ]; then
        break
    fi
    sleep 1
done

echo
echo "------------------------------------------------------------------"
if [ "$READY" = " 8000 3000" ]; then
    echo "All services are up."
else
    echo "WARNING: not every service came up (got:$READY)."
    echo "         Check the output above for the error."
fi
echo
echo "  Frontend:  http://localhost:3000"
echo "  Backend:   http://localhost:8000"
echo "  API docs:  http://localhost:8000/docs"
echo "  Health:    http://localhost:8000/api/status"
echo
echo "  Note: the dev server is pinned to port 3000 in frontend/vite.config.js."
echo "        If that port is busy Vite falls back to 5173 - use the URL it"
echo "        prints, not the one above."
echo

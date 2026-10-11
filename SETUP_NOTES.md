# SETUP_NOTES — Machine-specific setup record

**Scope:** setup steps and environment facts for *this machine only* (the IDFA
dev box). For generic project instructions see SETUP.md / README.md / AGENTS.md.
All paths below were verified on 2026-10-11; versions were read from the
installed binaries/packages, not from memory.

## Machine-specific fact summary

| Item | Value (verified) |
|---|---|
| OS | Windows (PowerShell) |
| Portable Node.js | `E:\tools\node-v18.20.8-win-x64` — `v18.20.8`; on **User PATH** (`E:\tools\node-v18.20.8-win-x64`) |
| System default `python` | **3.15** — NOT usable for this project (no compatible spacy/torch wheels) |
| Project Python | 3.12.10 at `C:\Users\sarva\AppData\Local\Programs\Python\Python312` (also on User PATH) |
| venv | `E:\Users\sarva\Documents\IDFA\venv` (Python 3.12.10, `venv\Scripts\python.exe`) |
| Backend | FastAPI/uvicorn on port **8000** (`backend.main:app`) |
| Frontend | Vite dev server on port **3000** (`frontend\vite.config.js`; Vite falls back to 5173 if 3000 is busy) |
| Ollama | 0.40.3 at `C:\Users\sarva\AppData\Local\Programs\Ollama`; model `llama3.2:3b` pulled (2.0 GB); port **11434** |
| DB | SQLite `data\forensic.db`; `CASES_DIR=./data/cases` |
| Migrations | 19/19 applied via `backend\migrate_all.py` (step 1 `init_db` + 18 migration steps; re-runs are skipped as "already applied") |
| Demo data | Seeded — see credentials below |

### Demo credentials (seeded)
- `admin` / `Admin@IDF2025` (Admin)
- `det_markov` / `Markov@2025` (Investigator — Det. Elena Markov)
- `analyst_chen` / `Chen@2025` (Analyst — Robert Chen)

## Installed Python packages (venv)

Installed from `requirements.txt`, plus the embedding stack. Versions verified in
the venv (`importlib.metadata`), except the spaCy model versions which are the
wheel versions installed (3.7.1).

- spaCy **3.7.4** (thinc 8.2.5); models installed via direct wheels:
  - `en_core_web_sm` **3.7.1**
  - `en_core_web_lg` **3.7.1**
- Embedding stack:
  - sentence-transformers **3.0.1**
  - transformers **4.44.2**
  - torch **2.14.1+cpu** (CPU build; `cuda.is_available()` = False)
  - numpy **1.26.4** (pinned — spaCy's thinc requires numpy<2)
  - scipy **1.13.1**
  - scikit-learn **1.4.2**
- Embedding model `sentence-transformers/all-MiniLM-L6-v2` cached in
  `%USERPROFILE%\.cache\huggingface\hub\models--sentence-transformers--all-MiniLM-L6-v2`.

## Key setup steps performed on this box

1. Installed portable Node.js 18.20.8 to `E:\tools\node-v18.20.8-win-x64` and
   appended it to the User PATH (verified present). Do NOT delete it.
2. Installed Python 3.12.10 to
   `C:\Users\sarva\AppData\Local\Programs\Python\Python312`. The 3.15 default
   `python` cannot install this project's wheels, so always use the venv or the
   3.12 interpreter.
3. Created the venv from Python 3.12:
   `E:\Users\sarva\Documents\IDFA\venv`.
4. `pip install -r requirements.txt` inside the venv, then the embedding stack
   above (torch `+cpu`, numpy pinned to 1.26.4).
5. Installed spaCy models from wheels: `en_core_web_sm` 3.7.1 and
   `en_core_web_lg` 3.7.1.
6. Installed Ollama 0.40.3 (Windows app,
   `C:\Users\sarva\AppData\Local\Programs\Ollama`) and pulled `llama3.2:3b`.
   **Ollama is NOT on PATH** — it auto-starts as a Windows desktop app
   (verified listening on 11434); see gotchas.
7. Applied migrations: `PYTHONPATH=. venv\Scripts\python.exe backend\migrate_all.py`
   → 19/19 (step 1 `init_db` + 18 migration steps).
8. Seeded demo data (credentials above) and cached the MiniLM-L6-v2 model.

## Starting the stack

Run from the repo root:

```
start_windows.bat
```

- Starts Ollama (only if not already listening on 11434), the backend
  (`venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000`),
  and the Vite frontend, each in its own window, teeing to `logs\`.
- URLs: frontend http://localhost:3000 · backend http://localhost:8000 ·
  API docs http://localhost:8000/docs · health http://localhost:8000/api/status.
- `start_windows.bat` ends with a `pause` — expected.

**Manual frontend fallback:** the frontend child is launched in a *fresh* `cmd`
whose PATH may not contain `E:\tools\node-v18.20.8-win-x64`. If `logs\frontend.log`
shows `'"node"' is not recognized`, start the frontend by hand from a shell
that has Node on PATH:

```
cd frontend
npm install          # only if node_modules is missing
npm run dev          # or: node_modules\.bin\vite.cmd
```

(The launcher uses `npm`-installed `node_modules\.bin\vite.cmd`; global
`yarn` 1.x on Windows cannot resolve vite — use npm.)

### Manual service starts (if not using the .bat)
```
REM backend
set PYTHONPATH=.&&venv\Scripts\python.exe -m uvicorn backend.main:app --host 0.0.0.0 --port 8000

REM ollama (if the desktop app is not running)
"C:\Users\sarva\AppData\Local\Programs\Ollama\ollama.exe" serve
```

## Gotchas

1. **Import order — sklearn before torch breaks torch** (WinError 1114,
   `c10.dll`): importing `scikit-learn` before `torch` in one process corrupts
   torch's DLL load. `sentence-transformers` does **not** import sklearn, so the
   app is unaffected; keep it that way and don't add a sklearn import anywhere
   touched before the embedding stack loads.
2. **Portable Node PATH loss:** a fresh `cmd` (as spawned by
   `start_windows.bat`) may lack `E:\tools\node-v18.20.8-win-x64`. Check
   `logs\frontend.log`; fix by launching the frontend from a shell where
   `node` resolves.
3. **Ollama not on PATH:** `where ollama` fails in a normal shell. Ollama
   auto-starts as a desktop app; `start_windows.bat` detects port 11434 instead
   of relying on PATH. To run `ollama` CLI by hand, use the full path
   `C:\Users\sarva\AppData\Local\Programs\Ollama\ollama.exe`.
4. **Python 3.15 default is unusable for this project.** Always use
   `venv\Scripts\python.exe` (or the 3.12 interpreter at
   `C:\Users\sarva\AppData\Local\Programs\Python\Python312`).
5. **Do not unpin numpy.** thinc (spaCy) needs numpy < 2; numpy must stay at
   1.26.4 in this venv.
6. **`python -m uvicorn` vs activate:** start the backend with
   `venv\Scripts\python.exe -m uvicorn` (as the .bat does); it does not depend
   on activation PATH munging.
7. **Port 3000 fallback:** if 3000 is taken, Vite silently moves to 5173 — use
   the URL printed in the frontend window, not the one in the .bat summary.
8. **Migrations are idempotent one-offs:** `backend\migrate_all.py` imports each
   `migrate_*.py` module; "already applied" steps are skipped on re-run. There
   is no schema-migrations bookkeeping table.

## Cleanup performed (2026-10-11)

Temp installers/artifacts removed from `%TEMP%`:
`OllamaSetup2.exe`, `node-v18.20.8-win-x64.zip`,
`python-3.12.10-amd64.exe`, `ollama-pull.log`, `ollama-pull.err`.
(`OllamaSetup.exe` and `python-3.12.11-amd64.exe` were already absent.)
No `~*` leftover directories were found in `venv\Lib\site-packages`.

**Never delete:** `E:\tools\node-v18.20.8-win-x64` (portable Node), the venv,
`data\`, `.env`, or any repo source file.
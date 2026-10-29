# IDFA — Developer Setup Guide

**Intelligent Digital Forensic Analysis** — A local-first Windows desktop application for digital forensic investigators.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Windows | 10/11 64-bit | Native only; no WSL/Docker |
| Python | 3.12+ | Optional: setup installs `packages\python-3.12.10-amd64.exe` when Python is missing |
| Git | Any | For cloning |
| Inno Setup 6 | Optional | Only for building the installer |

Nothing else is downloaded when the dependency bundle is present (see
[Installing without downloads](#installing-without-downloads)).

---

## Quick Start (Development)

### 1. Install Git LFS, Clone & Enter
```powershell
git lfs install
git clone --branch Desktop-Application https://github.com/sarvagnasrao/Intelligent-Digital-Forensic-AI-Assistant.git Final_Project
cd Final_Project
```

Git LFS downloads the bundled Python wheels, Qdrant, CPU Ollama runtime and
models with the checkout (~2.4 GiB). If you already cloned without LFS, run
`git lfs pull` in the repository before setup.

### 2. One-Command Setup
```powershell
# Prints a preflight report (Windows, Python, disk space, bundle, ports), then
# creates .venv, installs deps, Qdrant, the Ollama CPU runtime and models,
# migrates the database, verifies the install and creates shortcuts.
.\SETUP_IDFA.bat
```

Setup is idempotent: running it again only does what is missing. `-Check` reports
the state of the machine and the install without changing anything, and
`-Repair` deletes `.venv` and reinstalls every package.

### 3. Start All Services + Launch GUI
```powershell
.\START_IDFA.bat
```
If the environment is missing or incomplete, the launcher offers to run setup
first; `-Yes` skips the question and `-NoSetup` disables that behaviour.

After setup you can also use the **IDFA** shortcut on the Desktop / Start Menu.

### 4. Login
- **Username:** `admin`
- **Password:** `1234` (fresh installs; existing accounts are unchanged)

---

## Installing without downloads

`packages\` (wheels, Qdrant, Python installer, portable Ollama) and `models\`
(the weights, ~2.1 GiB) make setup work with no network. They are deliberately
excluded from git, so a fresh clone does not have them: build them once on a
connected machine with

```powershell
scripts\build_offline_bundle.ps1
```

then copy the project folder including `packages\` and `models\` to the target
machine and run `SETUP_IDFA.bat -Offline`. `SETUP_IDFA.bat -Check` prints
`Offline bundle found: … wheels …` when the bundle is complete.

---

## Manual Setup (If You Prefer Control)

### Create Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\pip install --upgrade pip
.\.venv\Scripts\pip install -r requirements.txt
```

### Install Windows Dependencies (pytsk3, libewf-python, etc.)
```powershell
.\.venv\Scripts\pip install -r requirements.txt
```

### Download/Prepare External Tools
```powershell
# Qdrant (embedded, no Docker)
# Ollama CPU runtime (bundled in packages/ollama-windows-cpu.zip)
# Python embeddable (for offline installs)
# These are downloaded/unpacked by SETUP_IDFA.bat
```

### Pull Models (if online)
```powershell
ollama pull phi3:mini      # Chat model (~2.2 GB)
ollama pull all-minilm     # Embedding model (~46 MB, 384-dim)
```

### Initialize Database
```powershell
.\.venv\Scripts\alembic upgrade head
```

### Run GUI
```powershell
.\.venv\Scripts\python.exe -m app
```

---

## Project Structure

```
Final_Project/
├── app/                    # PySide6 GUI application
│   ├── __main__.py         # Entry point
│   ├── auth/               # Auth & RBAC
│   ├── cases/              # Case management
│   ├── evidence/           # Evidence registration & hashing
│   ├── examination/        # Examination job management
│   ├── artifacts/          # Artifacts, search, entities, timeline
│   ├── analysis/           # Background NER + relationships
│   ├── ai/                 # AI analysis (local Ollama)
│   ├── findings/           # Findings workflow
│   ├── reports/            # PDF report generation
│   ├── audit/              # Audit trail & chain of custody
│   ├── db/                 # SQLAlchemy models & session
│   ├── forensics/          # Forensic processing helpers
│   ├── ui/                 # PySide6 UI components
│   └── config.py           # Config loader (YAML + env overrides)
├── worker/                 # FastAPI local worker (port 8000)
│   ├── main.py             # Forensic + AI endpoints
│   └── requirements.txt    # Standalone worker deps
├── migrations/             # Alembic migrations
├── scripts/                # Setup/start/stop helpers
├── tools/                  # Runtime binaries (created at setup, NOT in git)
│   ├── qdrant/qdrant.exe
│   └── ollama/ollama.exe
├── packages/               # Offline bundle (wheels, Qdrant, Ollama, Python)
├── models/ollama/          # Optional bundled model weights
├── installer/idfa.iss      # Inno Setup installer
├── config.example.yaml     # Configuration template
├── pyproject.toml          # Dependencies & tool config
├── alembic.ini             # Alembic config
├── requirements.txt        # Windows dependencies
├── SETUP_IDFA.bat          # One-command setup
├── START_IDFA.bat          # Start services + GUI
└── STOP_IDFA.bat           # Stop services
```

---

## Key Commands

### Development
```bash
# Run GUI
.\.venv\Scripts\python.exe -m app

# Run tests
.\.venv\Scripts\pytest

# Lint
.\.venv\Scripts\ruff check .

# Type check
.\.venv\Scripts\mypy app/

# Format
.\.venv\Scripts\ruff format .

# Create migration
.\.venv\Scripts\alembic revision --autogenerate -m "description"

# Apply migrations
.\.venv\Scripts\alembic upgrade head

# Reset DB (dev only)
.\.venv\Scripts\python -c "from app.db.session import drop_db, init_db; drop_db(); init_db()"
```

### Worker (Forensic Backend)
```powershell
# Start worker manually (launchers do this automatically)
Start-Process .venv\Scripts\python.exe -ArgumentList "worker\main.py" -WindowStyle Hidden

# Health check
curl.exe -s http://127.0.0.1:8000/health
# Expected: {"status":"ok","pytsk3":true,"pyewf":true,"ollama":true,"qdrant":true,"embeddings":true}

# Worker env overrides
#   IDFA_WORKER_HOST / IDFA_WORKER_PORT
#   IDFA_OLLAMA_HOST / IDFA_OLLAMA_MODEL / IDFA_EMBEDDING_MODEL
#   IDFA_MAX_CONTEXT_TOKENS (default 8192)
#   IDFA_QDRANT_URL
```

### Ollama & Models
```powershell
# List available models
curl.exe -s http://127.0.0.1:11434/api/tags

# Chat model (phi3:mini, 2.2 GB)
ollama pull phi3:mini

# Embedding model (all-minilm, 46 MB, 384-dim)
ollama pull all-minilm
```

---

## Architecture Overview

### Two-Process Design (Both Native Windows)
- **GUI** (`app/`): PySide6, SQLite, auth, case management, evidence, search UI, reports
- **Worker** (`worker/main.py`): FastAPI on `127.0.0.1:8000`, pytsk3/pyewf for disk forensics, talks to Ollama (`127.0.0.1:11434`) and Qdrant (`127.0.0.1:6333`)

### Communication
- GUI → Worker via HTTP/JSON (httpx async client)
- Paths passed through unchanged (both run on Windows)
- Long operations on background threads; UI updates via Qt signals

### Service Layer Pattern
- **GUI never touches DB directly** — all operations through service classes
- Services in `app/<module>/service.py`
- Models in `app/<module>/models.py`
- UI in `app/ui/pages/` — receive services via dependency injection

---

## Configuration

### Active Config: `%APPDATA%\IDFA\config.yaml`
- Created on first run from `config.example.yaml`
- Only `app.data_dir` is stored; database, logs, evidence, Qdrant paths derived from it
- Environment overrides:
  - `APP__DATA_DIR`
  - `DATABASE__URL`
  - `WORKER__URL`
  - `OLLAMA__HOST`
  - `QDRANT__URL`

### AI Providers
- `ollama.provider` / `embeddings.provider` = `ollama` (local) or `openai` (any OpenAI-compatible endpoint, e.g., NVIDIA NIM)
- Cloud settings stored encrypted via DPAPI (`dpapi:<base64>` in config.yaml)
- Only IDFA-launched Ollama is stopped on exit

---

## Testing

```bash
# All tests
.\.venv\Scripts\pytest

# Single file
.\.venv\Scripts\pytest tests/test_analysis.py

# With coverage
.\.venv\Scripts\pytest --cov=app
```

### Test Config (pyproject.toml)
- `testpaths = ["tests"]`
- `tests/manual/` holds ad-hoc scripts, not collected
- Every test writes to a throwaway `%TEMP%` config dir (see `tests/conftest.py`)

---

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: PySide6` | `.\.venv\Scripts\pip install -r requirements.txt` |
| Worker health shows `ollama: false` | Start Ollama for Windows; check `curl http://127.0.0.1:11434/api/tags` |
| Worker health shows `embeddings: false` | `ollama pull all-minilm` |
| AI page: "could not get a reply from local model" | Check `%LOCALAPPDATA%\Ollama\server.log`; context window too large — worker clamps to 8192 |
| Worker health shows `qdrant: false` | `START_IDFA.bat` starts `tools\qdrant\qdrant.exe`; check `http://127.0.0.1:6333/healthz` |
| Qdrant missing | `SETUP_IDFA.bat` downloads it; verify with `SETUP_IDFA.bat -Check` |
| `table ... already exists` on setup | Fixed in `init_db`; re-run setup |
| Port 8000/6333 in use | `STOP_IDFA.bat` stops recorded PIDs; else stop other process |
| `pytsk3` import error | `.\.venv\Scripts\pip install pytsk3` |
| E01 files rejected | `.\.venv\Scripts\pip install libewf-python` (provides `pyewf`) |
| Alembic can't find models | Ensure `app.db.__init__` imports all models |

---

## Security Notes

- **Default admin password:** `1234` on fresh installs — **change immediately**
- **JWT secret:** Generated per install on first run
- **Chain of custody:** Application-level logging only, not legally binding
- **AI output:** Explicitly marked "unverified", requires investigator verification
- **Local-first:** AI generation, embeddings, Qdrant all local; no cloud deps

---

## Key Files for New Developers

| File | Purpose |
|------|---------|
| `AGENTS.md` | Complete agent guide (architecture, decisions, workflows) |
| `README.md` | User-facing overview |
| `INSTALL_LOCAL.md` | Offline bundle build/install |
| `WINDOWS_REFERENCE.md` | Windows-specific implementation notes |
| `app/__main__.py` | App entry point |
| `worker/main.py` | Worker API endpoints |
| `app/ui/main_window.py` | Navigation & shells |
| `app/db/session.py` | Database session management |
| `app/examination/profiles.py` | Examination presets & parameter validation |
| `app/analysis/` | Background NER + relationships pipeline |

---

## Development Workflow

1. **Make changes** to service/UI code
2. **Run tests:** `.\.venv\Scripts\pytest`
3. **Lint:** `.\.venv\Scripts\ruff check .`
4. **Type check:** `.\.venv\Scripts\mypy app/`
5. **Create migration** if DB schema changed: `.\.venv\Scripts\alembic revision --autogenerate -m "description"`
6. **Test GUI:** `.\.venv\Scripts\python.exe -m app`

---

## Important Constraints

- **Windows only** — GUI and worker are both native Windows
- **Python 3.12+** required
- **SQLite only** — no PostgreSQL/MySQL support planned
- **Local-first** — no cloud dependencies
- **No external API keys required** — all AI runs locally via Ollama

---

## Offline / Air-Gapped Install

See `INSTALL_LOCAL.md` for building the offline bundle (`packages/`) and installing on a machine without internet.

---

## Building the Installer

```powershell
# Requires Inno Setup 6 installed
iscc.exe installer\idfa.iss
# Output: dist\IDFA-Setup.exe
```

---

## Support

- Check `AGENTS.md` for detailed architecture notes
- Run `START_IDFA.bat -Status` for service health
- Worker logs: `<data_dir>\logs\worker.err.log`
- Qdrant logs: `<data_dir>\logs\qdrant.err.log`
- Ollama logs: `%LOCALAPPDATA%\Ollama\server.log`

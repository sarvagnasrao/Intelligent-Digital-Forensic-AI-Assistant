# IDFA - Intelligent Digital Forensic Analysis System

Final-year BE Computer Science and Engineering project at K.S. Institute of Technology (KSIT), Bengaluru, under VTU.

## Team
- Shrisha C M
- Srigowri S Kulkarni
- Sarvagna S Rao
- Yashaswi R

Guide: Ms. Shruthi T. S., Assistant Professor, Dept. of CSE

## Architecture

```
┌──────────────────────────────────────┐     HTTP/JSON      ┌──────────────────────────────────────┐
│            IDFA GUI                  │ ◄────────────────► │         Forensic Worker              │
│  PySide6  │  SQLite  │  Auth/Cases   │   127.0.0.1:8000   │  FastAPI  │  pytsk3  │  pyewf      │
│  Evidence │  Search  │  Reports      │                    │  Exam     │  Worker API           │
└──────────────────────────────────────┘                    └──────────────────────────────────────┘
                    │                                                        │
                    └──────────────► Ollama :11434  ◄───────────────────────┘
                                     Qdrant  :6333
```

Everything runs on one Windows machine. There is no WSL and no Docker: the
worker is a second local process, and Qdrant is the bundled `qdrant.exe`.

## AI providers

The offline/local setup uses Ollama:

| Purpose | Model | Size |
|---|---|---|
| Chat / analysis | `phi3:mini` | 2.2 GB |
| Embeddings (384-dim) | `all-minilm` | 46 MB |

`all-minilm` is the same `all-MiniLM-L6-v2` model earlier builds loaded through
sentence-transformers, with identical vectors, so existing Qdrant collections
stay valid. The GUI itself no longer ships torch or transformers. Ollama picks a
supported GPU automatically; evidence copying, hashing and pytsk3 parsing remain
CPU operations.

For a faster exhibition/demo, open **Settings → AI & Models** and switch the mode
to **Cloud**. Pick a provider preset (NVIDIA NIM, OpenAI) or a custom
OpenAI-compatible endpoint, paste the API key, enter the model ID, and press
**Test connection**. Cloud embeddings can also be selected under Advanced;
`text-embedding-3-small` is requested at the existing 384-vector size. Changing
embedding models can require re-indexing artifacts. The API key is encrypted for
the current Windows account with DPAPI before it is written to `config.yaml`, so
the stored value is useless on another account or machine - still, never include
a real key in a shared bundle or project copy. Cloud mode sends the prompt and
selected evidence context to the configured provider; do not use it with
restricted evidence unless your policies permit that transfer. Local Ollama
remains the default and works offline.

IDFA starts Ollama automatically whenever chat or embeddings is local, and stops
the instance it launched when both are set to cloud. Only a server IDFA itself
started is stopped, so an Ollama installation serving other applications keeps
running. The same ownership rule applies to **Settings → Services**, which can
start, stop or restart the worker, Qdrant and Ollama without closing the app.

## Prerequisites

- Windows 10/11, 64-bit
- Python 3.12+ (setup installs it from the bundle when one is present)
- Ollama for Windows, or the CPU runtime in `packages\ollama-windows-cpu.zip`,
  which setup unpacks to `tools\ollama\` when Ollama is not installed
- No WSL, no Docker: Qdrant ships as `tools\qdrant\qdrant.exe`

## Installation

### Quick setup (recommended)
From the project folder, run:
```powershell
SETUP_IDFA.bat
```
Setup first prints a preflight report (Windows version, Python, free disk space,
offline bundle, ports), then creates `.venv`, installs the Windows dependencies
(from `packages\` when a cache exists, otherwise from PyPI), installs the bundled
Qdrant into `tools\qdrant\`, unpacks the CPU Ollama runtime into `tools\ollama\`
if Ollama is missing, checks both models, runs the database migrations, verifies
the result and creates **IDFA** / **Stop IDFA** shortcuts on the Desktop and in
the Start Menu.

Flags:

| Flag | Effect |
|------|--------|
| `-Check` | Preflight + doctor: verify the computer and an existing installation without changing anything |
| `-Repair` | Delete `.venv` and reinstall every Python package |
| `-Offline` | Never use the network; fail if `packages\` is incomplete |
| `-SkipModels` | Skip the Ollama model check |
| `-SkipQdrant` | Skip the Qdrant install |
| `-NoShortcuts` | Do not create Desktop/Start Menu shortcuts |
| `-Yes` | Do not ask for confirmation |

`START_IDFA.bat` detects a missing or half-installed environment and offers to
run setup for you, so forgetting the setup step no longer leaves you at an error
message. Use `START_IDFA.bat -NoSetup` if you never want that prompt.

For an air-gapped machine see [INSTALL_LOCAL.md](INSTALL_LOCAL.md).

#### Installing without downloads
The `Desktop-Application` branch includes the Windows dependency bundle using
Git LFS (about 2.4 GiB, including Python wheels, Qdrant, Ollama and both models).
Install Git LFS before cloning so the bundle downloads with the source:

```text
packages\   wheels for requirements.txt, Qdrant, the Python installer, CPU Ollama
models\     phi3:mini and all-minilm weights (~2.1 GiB)
```

```powershell
git lfs install
git clone --branch Desktop-Application https://github.com/sarvagnasrao/Intelligent-Digital-Forensic-AI-Assistant.git
```

For an existing clone, run `git lfs pull` from the project directory. Setup
checks the bundle against its manifest and stops with that instruction if the
LFS payload has not been downloaded. Once the clone is complete, setup installs
from the bundle and needs no network connection. To rebuild the bundle on a
connected Windows machine:

```powershell
scripts\build_offline_bundle.ps1
```

The large model layer is split into LFS-sized pieces and reassembled into the
Ollama model store during setup. GitHub's LFS free quota is 10 GiB storage and
10 GiB monthly download bandwidth; a full clone consumes about 2.4 GiB of
bandwidth. For lab/offline distribution, clone once on an internet-connected
machine and copy the project folder (including `packages\` and `models\`) to
the target; then run `SETUP_IDFA.bat -Offline`.

### Uninstall
Use the uninstaller instead of deleting files by hand:

```powershell
UNINSTALL_IDFA.bat              # stop services and remove .venv, tools\, caches, shortcuts
UNINSTALL_IDFA.bat -DryRun      # show exactly what would be removed
UNINSTALL_IDFA.bat -PurgeData   # also delete the case database, evidence copies and config
```

The default keeps the source code, case data, configuration and the offline
bundle (`packages\`, `models\`) so a reinstall needs no download. `-PurgeData`
asks you to type `DELETE`, refuses unsafe folders (a drive root, your profile,
the project folder) and removes `%APPDATA%\IDFA\config.yaml` too. Other flags:
`-RemoveModels` deletes `phi3:mini`/`all-minilm` from the Ollama store without
touching blobs another model still references, `-RemoveBundle` deletes
`packages\` and `models\`, and `-Yes` skips the questions. The source folder
itself is never deleted by the script; delete it afterwards if you want it gone.

### Installer
`installer\idfa.iss` builds a per-user Windows installer with Inno Setup 6. It
ships the offline cache, the model weights and the four BAT files, and runs
`SETUP_IDFA.bat -Offline -NoShortcuts` as its last step:

```powershell
winget install --id JRSoftware.InnoSetup -e
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" installer\idfa.iss
# -> dist\IDFA-0.1.0-setup.exe
```

The Inno Setup uninstaller stops IDFA services and removes its installed program
files; it leaves case data in the configured data folder. The standalone
`UNINSTALL_IDFA.bat` offers the same cautious cleanup for a cloned project.

### Manual setup (advanced)
#### 1. Clone and setup Windows environment
```bash
cd E:\Users\sarva\Documents\Final_Project
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

#### 2. Initialize database
```bash
# Run Alembic migrations
alembic upgrade head
```

#### 3. Configure
No editing is needed on a new machine. The first launch asks where case data
should live and writes the configuration to your user profile:

```text
%APPDATA%\IDFA\config.yaml
```

Only `app.data_dir` is stored. The database, logs, evidence store and vector
storage are derived from that one folder, so the file keeps working when the
project is moved or the data folder changes. `config.example.yaml` documents
every setting, and **Settings → Data & Storage** can change the folder later
(move existing data, adopt a folder, or start fresh).

#### 4. Run
```powershell
# Start Qdrant, the forensic worker, ensure Ollama, then launch the GUI
START_IDFA.bat
```

Other commands:
```powershell
START_IDFA.bat -NoGui    # Start services only
START_IDFA.bat -Status   # Check service health
STOP_IDFA.bat            # Stop all services
```

Manual start (advanced):
```powershell
# Terminal 1: start the bundled Qdrant
tools\qdrant\qdrant.exe

# Terminal 2: start the forensic worker
.venv\Scripts\python.exe worker\main.py

# Terminal 3: start the GUI
.venv\Scripts\python.exe -m app
```

## Default Login
- Username: `admin`
- Password: `1234`

Fresh installations create this account on first launch. Existing installations
keep their current admin password; change the password immediately after first
login.

## Project Structure
```
Final_Project/
├── SETUP_IDFA.bat          # Install all prerequisites
├── START_IDFA.bat          # Start services + launch GUI
├── STOP_IDFA.bat           # Stop all services
├── scripts/                # setup/start/stop helper scripts
├── installer/idfa.iss      # Inno Setup 6 installer (output in dist\)
├── tests/                  # pytest suite; tests/manual/ holds ad-hoc checks
├── tools/qdrant/           # qdrant.exe installed by setup
├── tools/ollama/           # CPU Ollama runtime, unpacked from the bundle
├── packages/               # offline bundle: wheels, Qdrant, Ollama, Python
├── models/ollama/          # bundled model weights for offline installs (optional)
app/
├── __main__.py              # Entry point
├── config.py                # Configuration management
├── firstrun.py              # First-run data folder, move/adopt/fresh
├── logging_config.py        # Logging setup
├── auth/                    # Authentication & users
├── cases/                   # Case management
├── evidence/                # Evidence registration & hashing
├── examination/             # Examination jobs
├── artifacts/               # Artifacts, search, entities, timeline
├── analysis/                # Entity extraction, relationships, analysis queue
├── ai/                      # AI analysis (RAG) + Ollama embeddings
├── findings/                # Findings workflow
├── reports/                 # PDF report generation
├── audit/                   # Audit trail & chain of custody
├── db/                      # Database models & session
├── forensics/               # Forensic processing helpers
├── workers/                 # Background workers
├── ui/
│   ├── main_window.py       # Main window & navigation
│   ├── login_dialog.py      # Login dialog
│   ├── base.py              # Base UI components
│   ├── theme/               # Design system & styling
│   └── pages/               # All UI pages
└── config/                  # Configuration package

worker/
└── main.py                  # local FastAPI worker (pytsk3, Ollama, Qdrant)

migrations/
├── env.py                   # Alembic environment
├── script.py.mako           # Migration template
└── versions/                # Migration scripts
```

## Features Implemented

### Core (Windows GUI)
- [x] Login with JWT authentication
- [x] Role-based access control (Admin/Investigator/Read-only)
- [x] Global case dashboard with statistics
- [x] Case creation, editing, filtering
- [x] Case-scoped navigation (9-page sidebar)
- [x] Evidence registration with SHA-256/MD5 hashing
- [x] Integrity verification workflow
- [x] Evidence control: remove from case (reversible), guarded permanent
      delete, open file/folder, reference hash from the bag, export a verified
      copy, CSV/JSON case manifest, file-presence check, multipick + filters
- [x] Examination job management (queue, progress, results, cancel)
- [x] Clean shutdown: closing IDFA while a status check, search, report build
      or export is running stops those threads and waits briefly instead of
      crashing; a copy that cannot stop in time is abandoned, not killed
      mid-write
- [x] Examination presets (Fast / Balanced / Deep) with an Advanced panel that
      shows and controls every ingestion parameter (file limit, size cap,
      stored text, deleted files, media, large-file hashing, deep extraction,
      partition offset, timeout) before the scan starts
- [x] Transparent results: the job log records the parameters used and the raw
      values the worker was given
- [x] Artifact storage with FTS5 keyword search
- [x] Search: filename/path/content matches with snippets, phrase, OR, NOT,
      NEAR and regex syntax, chunked semantic search with near-duplicate
      collapse, and hybrid ranking (Reciprocal Rank Fusion)
- [x] Background analysis after every examination: exact entity extraction
      (e-mail, phone, URL, IP, MAC, wallet, digest, username, device id,
      timestamp, path, filename), model-assisted names with quote verification,
      file timeline, and a relationship graph (shared entity, related artifacts,
      duplicate content) with confirm/reject review
- [x] AI Analysis chat interface (placeholder for worker integration)
- [x] Findings workflow (Draft → Under Review → Verified/Rejected)
- [x] Report generation (ReportLab PDF)
- [x] Audit trail & chain of custody viewer

### Forensic Worker (native Windows)
- [x] FastAPI server with health endpoint
- [x] pytsk3 integration for partition analysis
- [x] Filesystem detection (NTFS, FAT32, ext4)
- [x] File traversal and metadata extraction
- [x] File content extraction
- [x] Deleted file recovery support
- [x] A single Win32 process reads split raw images (.001-.008) and E01 (pyewf)
- [x] Ollama integration for local LLM
- [x] Qdrant vector store for semantic search
- [x] Batched embeddings through Ollama (`all-minilm`)

## Development Commands

```bash
# Run tests
.venv\Scripts\pytest

# Create new migration
.venv\Scripts\alembic revision --autogenerate -m "description"

# Apply migrations
.venv\Scripts\alembic upgrade head

# Lint and format
.venv\Scripts\ruff check --fix .
.venv\Scripts\ruff format .

# Type check
.venv\Scripts\mypy app/
```

## Configuration

The active file is `%APPDATA%\IDFA\config.yaml`, created on first run.
`config.example.yaml` is the committed template.

- `app.data_dir`: single root for cases, evidence, database, logs and vectors
- `worker.url`: forensic worker URL (default: http://127.0.0.1:8000)
- `ollama.host`: Ollama host (default: http://127.0.0.1:11434)
- `ollama.max_tokens` / `ollama.context_window_tokens`: reply length and context
  window (defaults 2048 / 8192). The context window costs memory per token and
  is capped by the worker at 8192 unless `IDFA_MAX_CONTEXT_TOKENS` raises it.
- `qdrant.url`: Qdrant host (default: http://127.0.0.1:6333)
- `embeddings.model_id`: Ollama embedding model (default: `all-minilm`)
- `analysis.*`: background entity/relationship analysis. `auto_queue` queues a
  job after each examination and picks up evidence added to an existing case;
  `llm_max_artifacts` / `llm_max_chars` cap how much text a model sees;
  `defer_llm_while_examining` keeps model calls out of a running scan;
  `hub_fraction` decides what counts as a value too common to link artifacts
- `auth.secret_key`: generated per install on first run; set it explicitly only
  if you need a fixed value

Older files that still say `localhost` or
`sentence-transformers/all-MiniLM-L6-v2` are normalised on load, so they keep
working without editing.

Override any of these with environment variables: `APP__DATA_DIR`,
`DATABASE__URL`, `WORKER__URL`, `OLLAMA__HOST`, `QDRANT__URL`,
`AUTH__SECRET_KEY`, `EMBEDDINGS__MODEL_ID`.

If the configured data folder is missing — for example an unplugged external
drive — IDFA blocks startup and offers Retry, Choose another folder, or Quit
rather than opening an empty database.

## License
Academic project - KSIT Bengaluru

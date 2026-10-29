# IDFA - Agent Guide

## Project Overview
**IDFA (Intelligent Digital Forensic Analysis)** - A local-first desktop application for digital forensic investigators. Built with Python, PySide6 (GUI), SQLAlchemy/SQLite (persistence), FastAPI (local worker), Ollama (local LLM + embeddings), Qdrant (vector search).

**Architecture**: Two-process design, both native Windows
- **GUI**: PySide6 desktop app, SQLite, auth, case management, evidence registration, search UI, reports
- **Worker**: FastAPI on `127.0.0.1:8000`, pytsk3/pyewf for disk forensics. Talks to Ollama on `127.0.0.1:11434` and Qdrant on `127.0.0.1:6333`

---

## Quick Start

### Prerequisites
- Windows 10/11, 64-bit
- Python 3.12+
- Ollama for Windows, with `phi3:mini` and `all-minilm` pulled, or the CPU runtime
  in `packages\ollama-windows-cpu.zip` (unpacked to `tools\ollama\` by setup)
- Qdrant: the bundled `qdrant.exe`, no Docker required

### One-Command Start
```powershell
# First time only: create the venv, install packages, tools and models
SETUP_IDFA.bat

# Start all services and launch the GUI
START_IDFA.bat

# Stop all services
STOP_IDFA.bat

# Remove .venv, tools\, caches and shortcuts (keeps cases unless -PurgeData)
UNINSTALL_IDFA.bat
```

`START_IDFA.bat -NoGui` starts services only, and `START_IDFA.bat -Status`
prints service health. If `.venv` is missing or half-installed the launcher
offers to run setup itself (`-NoSetup` disables the prompt, `-Yes` skips the
question). Setup prints a preflight report, is idempotent, installs from
`packages\` + `models\` when present, and creates per-user Desktop/Start Menu
shortcuts (`-NoShortcuts` to skip). `SETUP_IDFA.bat -Check` verifies the machine
and an existing install without changing anything; `-Repair` reinstalls `.venv`.
`UNINSTALL_IDFA.bat` stops the services and removes the runtime it created
(`.venv`, `tools\`, caches, shortcuts) but keeps case data, config and the
offline bundle; `-DryRun` previews, `-PurgeData` (typed `DELETE`) also removes
cases and config, `-RemoveModels`/`-RemoveBundle` extend it further.

### Verify Services
```powershell
curl.exe -s http://127.0.0.1:8000/health
# Expected: {"status":"ok","pytsk3":true,"pyewf":true,"ollama":true,"qdrant":true,"embeddings":true}
```

### Login
- **Username**: `admin`
- **Password**: `1234` on fresh installs (change it after the first sign-in)

---

## Project Structure

```
Final_Project/
├── app/                    # Windows GUI application
│   ├── __main__.py         # Entry point
│   ├── auth/               # Authentication & RBAC
│   ├── cases/              # Case management
│   ├── evidence/           # Evidence registration & hashing
│   ├── examination/        # Examination job management
│   ├── artifacts/          # Artifacts, search, entities, timeline
│   ├── analysis/           # Background entities, relationships, timeline queue
│   ├── ai/                 # AI analysis (stub)
│   ├── findings/           # Findings workflow
│   ├── reports/            # PDF report generation
│   ├── audit/              # Audit trail & chain of custody
│   ├── db/                 # SQLAlchemy models & session
│   ├── forensics/          # Forensic processing helpers
│   ├── ui/                 # PySide6 UI components
│   └── config.py           # Config loader (YAML + env overrides)
├── worker/                 # local FastAPI worker
│   ├── main.py             # FastAPI app with forensic + AI endpoints
│   └── requirements.txt    # standalone worker dependencies
├── migrations/             # Alembic migrations
├── scripts/                # setup/start/stop helpers (+ scripts/README.md)
├── tests/                  # pytest suite; tests/manual/ holds ad-hoc checks
├── tools/qdrant/           # qdrant.exe installed by setup (not in git)
├── tools/ollama/           # CPU Ollama runtime unpacked from the bundle (not in git)
├── packages/               # bundled wheels, Qdrant, Ollama runtime and Python (Git LFS)
├── models/ollama/          # bundled phi3:mini/all-minilm weights (Git LFS)
├── installer/idfa.iss      # Inno Setup 6 installer (build outputs to dist\)
├── config.example.yaml     # Configuration template (active file: %APPDATA%\IDFA\config.yaml)
├── pyproject.toml          # Dependencies & tool config
├── alembic.ini             # Alembic config
├── INSTALL_LOCAL.md        # Offline bundle: how to build and install
└── requirements.txt        # Windows dependencies
```

---

## Key Commands

### Development
```bash
# First-time prerequisites (add -Check to verify, -Offline for air-gapped)
SETUP_IDFA.bat

# Start services + GUI (-NoGui, -Status also accepted)
START_IDFA.bat

# Stop services (-IncludeOllama also stops Ollama)
STOP_IDFA.bat

# Install Windows dependencies
.venv\Scripts\pip install -r requirements.txt

# Run GUI
.venv\Scripts\python.exe -m app

# Run tests
.venv\Scripts\pytest

# Lint
.venv\Scripts\ruff check .

# Type check
.venv\Scripts\mypy app/

# Format
.venv\Scripts\ruff format .
```

### Database
```bash
# Create migration
.venv\Scripts\alembic revision --autogenerate -m "description"

# Apply migrations
.venv\Scripts\alembic upgrade head

# Reset DB (dev only)
.venv\Scripts\python -c "from app.db.session import drop_db, init_db; drop_db(); init_db()"
```

### Forensic Worker
```powershell
# Start the worker (the launchers do this automatically)
Start-Process .venv\Scripts\python.exe -ArgumentList "worker\main.py" -WindowStyle Hidden

# Health check
curl.exe -s http://127.0.0.1:8000/health

# Worker environment overrides
#   IDFA_WORKER_HOST / IDFA_WORKER_PORT
#   IDFA_OLLAMA_HOST / IDFA_OLLAMA_MODEL / IDFA_EMBEDDING_MODEL
#   IDFA_MAX_CONTEXT_TOKENS (default 8192; raise only on a large-memory machine)
#   IDFA_QDRANT_URL
```

### Ollama & Models
```powershell
# Pull the chat model (2.2 GB)
ollama pull phi3:mini

# Pull the embedding model (46 MB, 384 dimensions)
ollama pull all-minilm

# List what is available
curl.exe -s http://127.0.0.1:11434/api/tags
```

Embeddings are produced by Ollama's `all-minilm`, which is the same
`all-MiniLM-L6-v2` model earlier builds loaded through sentence-transformers.
Vectors are identical (cosine 0.999999), so existing Qdrant collections remain
valid and do not need re-indexing. Because of that, torch, transformers and the
old `models/` folder are no longer part of the runtime.

---

## Architecture Notes

### Evidence management (remove vs delete)
- **Remove from case** is a tombstone: `removed_at`/`removed_by_id`/`removal_reason` are set, the record, hashes, custody trail and files survive, and `return_evidence()` clears it. `get_evidence_by_case()` hides removed items, so the examination picker, reports and AI context ignore them; pass `include_removed=True` for the evidence table and the manifest.
- **Delete permanently** is separate and guarded: it refuses while examination jobs or artifacts reference the item, only unlinks files inside `worker.evidence_root_windows` (never the source), and every action writes both a `CustodyEvent` and an audit entry.
- `file_state()` reports `present` / `reference` / `missing` per item, so a stored copy moved or deleted outside IDFA shows as **Missing** in the table instead of only failing at verification.
- A hash entered at intake (or later via `set_reference_hash()`) is stored as the reference with the value IDFA computed kept as a second, non-reference row. Verification therefore always compares against the bag; a mismatch is visible immediately and stays visible.
- Removal and deletion do not rely on SQLite cascade: hashes and custody are deleted through the ORM cascade on `Evidence`.

### Service Layer Pattern
- **GUI never touches DB directly** - all operations go through service classes
- **Services** in `app/<module>/service.py` handle business logic
- **Models** in `app/<module>/models.py` - SQLAlchemy declarative models
- **UI** in `app/ui/pages/` - PySide6 pages, receive services via dependency injection

### Shutdown (threads and exit)
- Qt aborts the process when a `QThread` is destroyed while it is still running;
  on Windows that appears as a crash dialog. Closing IDFA during an AI status
  check, a search, a report build or an evidence export used to do exactly that,
  because nothing stopped the pages' threads.
- `app/ui/qt_threads.py` is the single registry: pages call `track()` for every
  thread they start, and each page that owns a thread exposes `shutdown()`
  (AI, Artifacts, Evidence, Reports; Settings already had one).
- `NavigationController.shutdown()` (called from `MainWindow.closeEvent`) stops
  the analysis runner, calls every page's `shutdown()`, then `stop_all()` waits
  up to 3 s for anything left. Evidence and report threads get 5 s because they
  write to the case store.
- `python -m app` checks `qt_threads.alive()` after `app.exec()` returns. If a
  thread is still busy (a multi-gigabyte copy cannot be interrupted politely),
  it logs that and exits with `os._exit(0)`: an abandoned copy leaves its
  `.part` file behind and SQLite rolls the transaction back, which is better
  than the abort Qt would otherwise cause.

### Case-Scoped Navigation
- **Global Shell**: Case management dashboard (no case context)
- **Case Shell**: 9-page sidebar (Overview, Evidence, Examination, Artifacts & Search, AI Analysis, Entities & Timeline, Findings, Reports, Audit & Custody)
- **CaseContext** object passed to case-scoped pages - no case selectors in case shell

### Async Worker Communication
- GUI → worker via HTTP/JSON (httpx async client) on `127.0.0.1:8000`
- Paths are passed through unchanged: the worker runs on Windows and reads the same paths the GUI does
- Long operations run on background threads, UI updates via signals

### Forensic Pipeline (Worker)
1. **Partition Analysis** - MBR/GPT via pytsk3 Volume_Info
2. **Filesystem Detection** - NTFS/FAT32/ext4 via pytsk3 FS_Info
3. **File Traversal** - Recursive walk, metadata extraction
4. **Artifact Extraction** - Streaming SHA-256 for every file; stored text is capped by `max_text_chars`, so a 4 GB log cannot inflate the database
5. **Deleted Recovery** - Filter unallocated inodes; recorded metadata-only unless the caller opts into more

`POST /examine` takes `{case_id, evidence_id, image_path, operation, job_id,
parameters}`. The `parameters` object is what the Examination page controls;
the worker honours these keys:

| key | meaning |
|-----|---------|
| `max_files` | stop after this many entries |
| `max_file_size` | bytes; larger files get a digest only |
| `max_text_chars` | stored text per file |
| `include_deleted` | list unallocated entries (metadata only) |
| `skip_media` | do not read media content |
| `hash_large_files` | digest files above `max_file_size` |
| `deep_extraction` | keep a stand-in text for files with no readable content |
| `partition_offset` | scan only the partition at this byte offset |

The presets in `app/examination/profiles.py` expand to exactly those keys (a
preset is a shortcut, never a hidden behaviour); `profile` and the GUI-side
timeout are stored on the job with the rest. `deep_extraction` is off for Fast
and Balanced, so a hex header, `[Image - N bytes]` or `[SQLite Database - N
bytes]` is not stored or embedded for a file with no readable text. Text files
and real Office (`.docx/.xlsx/.pptx`) text are extracted either way: the switch
only governs the stand-in, never the content. It is on for Deep. `POST
/examine/{job_id}/cancel` stops a running scan between files. The full request
is stored on the job (`parameters_json`) and echoed in the job log, so a run can
be reproduced.

### Background analysis (entities, timeline, relationships)
- `app/analysis/service.py` owns the queue: one job per **examination**, created
  after a scan completes and by `enqueue_missing()` for any completed
  examination that has none (that is how evidence added to an existing case
  gets analysed without a second click)
- `app/analysis/runner.py` is a `QTimer` (4 s) plus one thread. It runs one job
  at a time, waits while an examination is running, and can be paused from the
  page. Jobs left `running` by a crash are marked `interrupted` at start
- `app/analysis/extractors.py` is deterministic only: URLs, e-mail, wallets,
  digests, IP/MAC, phone, Windows/POSIX paths and filenames, usernames, device
  ids and timestamps. Overlapping spans are resolved by pattern priority, and
  one row is kept per `(type, normalised value)` per artifact
- `app/analysis/llm.py` asks a model only for people/organisations/locations.
  A candidate is stored only when its `quote` appears literally in the source
  text, which is what stops `phi3:mini` from inventing names. The cloud model
  is used when configured, the local one otherwise
- `app/analysis/relationships.py` rebuilds the graph each run:
  `shared_entity` (two co-occurring values), `related_artifacts` (two files
  sharing an identifier) and `duplicate_content` (identical bytes)
- A link needs either two artifacts or two strong identifiers in one artifact.
  Values present in more than `hub_fraction` of artifacts are hubs and are
  skipped; file paths and timestamps never link artifacts
- Confirmed/rejected rows survive a rebuild; unreviewed ones are recomputed
- Entity ids are `ENT-/EVT-/ANL-{case:04d}-{uuid10}` — random, because
  re-analysis deletes and recreates the rows a counter would collide with

### Search & AI
- **Keyword**: SQLite FTS5 (`artifacts_fts`), whole-table `MATCH`; name, path and
  content are searched, and `matched_fields` says which one hit
- **Syntax**: `"phrase"`, `OR`, `NOT`, prefix `term*`, `NEAR(a b, 10)`; regex is a
  separate mode (scans up to `REGEX_SCAN_LIMIT = 5000` rows) and is disabled for
  semantic search
- **Snippets**: `make_snippet()` returns the matched span with context, shown in
  the results table and the detail pane
- **Semantic**: Qdrant vectors per **chunk** (1200 chars / 200 overlap), collapsed
  to one hit per artifact using the best-scoring chunk. Point ids are a `uuid5`
  of `idfa:{case}:{artifact.id}:{chunk_index}`, so re-indexing overwrites the
  same point instead of duplicating it
- **Hybrid**: Reciprocal Rank Fusion (k=60)
- **AI Generation**: Ollama phi3:mini (or the configured cloud model) with
  context + citations; `mode: "raw"` sends the prompt verbatim and is what the
  analysis pipeline uses for JSON-shaped extraction
- **AI answer rendering**: `app/ui/markdown.py` decides whether a reply is
  Markdown (`looks_like_markdown`) and only then renders it with `MarkdownView`
  (`QTextBrowser`, auto-height, no inner scrollbar); replies without Markdown
  syntax stay plain text so their line breaks are preserved. The same detector
  drives the read-only fields of a saved finding, and the raw reply is what is
  stored in SQLite

---

## Configuration

### Config: `%APPDATA%\IDFA\config.yaml`
- Created on first run; `config.example.yaml` is the committed template
- Only `app.data_dir` is stored — database, logs, evidence and Qdrant paths are derived from it
- Never persist absolute machine paths: `save_config` writes blank for any value that matches the derived path
- Environment overrides: `APP__DATA_DIR`, `DATABASE__URL`, `WORKER__URL`, `OLLAMA__HOST`, `QDRANT__URL`
- `auth.secret_key` is generated per install; the shipped placeholder is replaced automatically
- A missing data folder blocks startup (Retry / Choose another folder / Quit) instead of opening an empty database
- Changing the data folder offers move (copy, keep source), adopt, or fresh — the source is never deleted

### AI providers and the Ollama lifecycle
- `ollama.provider` and `embeddings.provider` are each `ollama` (local) or `openai` (any OpenAI-compatible endpoint, e.g. NVIDIA NIM at `https://integrate.api.nvidia.com/v1`)
- Cloud chat uses `ollama.cloud_base_url` / `cloud_api_key` / `cloud_model`; cloud embeddings reuse the same key and send `dimensions: 384` for `text-embedding-3-*` so Qdrant stays compatible
- The model combos are editable: the app never fetches a provider model list, so the exact model ID must be typed or pasted
- The key is stored as `dpapi:<base64>` in the per-user `config.yaml`, encrypted for the current Windows account by `app/util/dpapi.py`; `save_config` encrypts it on every write and `cloud_api_key()` decrypts it for use. Plain-text keys from older configs are upgraded on the next save
- Presets (`NVIDIA NIM`, `OpenAI`, `Custom`) only fill the base URL; any other OpenAI-compatible endpoint can be typed under Custom
- `app/util/ollama_service.py` owns the Ollama lifecycle: `ensure_running()` launches it when either provider is local, `stop_managed()` stops it when both are cloud
- Only an IDFA-launched server is stopped. The PID is recorded at `%LOCALAPPDATA%\IDFA\run\ollama-idfa.pid` (also written by `start_idfa.ps1`); the PID's image name is verified before terminating, so a recycled PID or a server owned by another app is never killed
- The lifecycle runs on a daemon thread from `MainWindow._apply_ui_settings`; the AI status strip shows Ollama as `not needed` (not an error) in all-cloud mode

### Settings services pane
- `app/util/services.py` starts, stops and reports the worker, Qdrant and Ollama; `app/util/procs.py` holds the shared PID/health primitives
- The GUI writes the same PID files as `start_idfa.ps1` (`worker.pid`, `qdrant.pid`, `ollama-idfa.pid`), so `STOP_IDFA.bat` still cleans up whatever Settings started
- Ownership is checked before killing: a health endpoint answering without a matching PID is shown as "Started outside IDFA" and cannot be stopped from the GUI
- All service actions and health polls run on `QThread` workers; the status timer only runs while the Services pane is visible
- Settings is split into five panes behind a left nav (General, AI & Models, Services, Data & Storage, Security), and the AI pane shows either local or cloud controls, never both

### Path Mapping (Windows ↔ WSL, legacy only)
These mappings still apply to `scripts/legacy/` and the WSL worker; the native
Windows worker uses paths unchanged.
| Windows | WSL2 |
|---------|------|
| `E:\IDFA_Data\cases\...` | `/mnt/e/IDFA_Data/cases/...` |
| `E:\IDFA_Data\idfa.db` | `/mnt/e/IDFA_Data/idfa.db` |

---

## Testing

```bash
# Run all tests (test files in root directory)
.venv\Scripts\pytest

# Single test file
.venv\Scripts\pytest test_examination.py

# With coverage
.venv\Scripts\pytest --cov=app
```

### Test Configuration (pyproject.toml)
- `testpaths = ["tests"]`; `tests/manual/` holds ad-hoc scripts and is not collected
- No async or Qt plugin is required: async code is driven with `asyncio.run`
- Every test writes to a throwaway `%TEMP%` config dir (see `tests/conftest.py`)

---

## Common Issues & Fixes

| Issue | Fix |
|-------|-----|
| `ModuleNotFoundError: PySide6` | Run `.venv\Scripts\pip install -r requirements.txt` |
| Worker health shows `ollama: false` | Start Ollama for Windows (it normally starts at login) and check `curl.exe -s http://127.0.0.1:11434/api/tags` |
| Worker health shows `embeddings: false` | Pull the embedding model: `ollama pull all-minilm` |
| AI page says it could not get a reply from the local model | Check `%LOCALAPPDATA%\Ollama\server.log`; `failed to allocate buffer for kv cache` means the context window is too large. The worker clamps it to 8192 tokens now; stale configs are fixed on the next Settings save |
| Worker health shows `qdrant: false` | `START_IDFA.bat` starts `tools\qdrant\qdrant.exe`; check `http://127.0.0.1:6333/healthz` and `<data_dir>\logs\qdrant.err.log` |
| Qdrant is missing entirely | `SETUP_IDFA.bat` downloads it once (or use `-SkipQdrant` to skip); verify with `SETUP_IDFA.bat -Check` |
| Setup fails with `table ... already exists` | Fixed in `init_db`: it reconciles `alembic_version` with the tables that exist; re-run setup |
| Port 8000/6333 already in use | `STOP_IDFA.bat` stops recorded PID-file processes and any `worker\main.py` / `qdrant.exe` holding the port; otherwise stop the other process |
| Services start but the status table is yellow | Warnings only: AI needs Ollama, semantic search needs Qdrant; keyword search and examination still work |
| `pytsk3` import error | `.venv\Scripts\pip install pytsk3` |
| E01 files rejected | `.venv\Scripts\pip install libewf-python` (provides `pyewf`) |
| GUI won't start (DPI) | Already handled: `AA_EnableHighDpiScaling` disabled in main |
| Alembic can't find models | Ensure `app.db.__init__` imports all models |
| PySide6 not found in venv | Reinstall: `.venv\Scripts\pip install -r requirements.txt` |

---

## Security Notes

- **Default admin password**: `1234` on fresh installs (change immediately)
- **JWT secret**: generated per install on first run; override `auth.secret_key` only for a shared fixed value
- **Chain of custody**: Application-level logging only, not legally binding
- **AI output**: Explicitly marked "unverified", requires investigator verification
- **Local-first**: AI generation, embeddings and Qdrant are all local. Both models are served by the local Ollama
  runtime; nothing is downloaded at startup.

---

## References

- `%APPDATA%\IDFA\config.yaml` - Active configuration (per user, per machine)
- `config.example.yaml` - Configuration template
- `pyproject.toml` - Dependencies & tool config
- `worker/main.py` - Worker API endpoints
- `worker/requirements.txt` - Standalone worker dependencies
- `app/ai/embeddings.py` - Ollama embedding client (batched)
- `app/ui/main_window.py` - Navigation & shells
- `app/db/session.py` - Database session management
- `app/auth/service.py` - Authentication logic
- `app/examination/service.py` - Worker communication
- `app/artifacts/service.py` - Search service (FTS5 + Qdrant + RRF)

---

## Development Workflow

1. **Make changes** to service/UI code
2. **Run tests**: `.venv\Scripts\pytest`
3. **Lint**: `.venv\Scripts\ruff check .`
4. **Type check**: `.venv\Scripts\mypy app/`
5. **Create migration** if DB schema changed: `.venv\Scripts\alembic revision --autogenerate -m "description"`
6. **Test GUI**: `.venv\Scripts\python.exe -m app`

---

## Important Constraints

- **Windows only** - GUI and worker are both native Windows; no WSL or Docker
- **Python 3.12+** required (pyproject.toml)
- **SQLite only** - No PostgreSQL/MySQL support planned
- **Local-first** - No cloud dependencies
- **No external API keys** - All AI runs locally via Ollama

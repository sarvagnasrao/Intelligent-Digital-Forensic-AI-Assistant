# AGENTS.md — Progress & Operating Guide

> **Audience:** any AI coding agent (Claude Code, Cursor, Copilot, Antigravity, Devin…) picking up this repo.
> **Rule:** read this file *before* changing code. It records verified state, known bugs, and traps that are not
> derivable from the code itself.
>
> Last verified against: `main3` @ the §23 commit (2026-09-30) —
> §13 covers the ingestion rework, §14 the live end-to-end run and the three
> further bugs it found (B10/B11/B12), **§15 the stop button, per-case
> Qdrant isolation and the optional-dependency trap (B13/B14/B15)**,
> §16/§17 the telemetry and per-job controls, **§18 the honesty pass
> (B20–B25)**, **§19 the RAG prompt budget (B26)**, **§20 the context
> window, which was a reporting-only knob and never a control (B27)**, and
> **§21 a health probe that reported 0 indexes for indexed cases (B28)**, and
> **§23 an Archive button that worked perfectly and did nothing (B29)**.
> See §6 and §12 for the forensic-image fixes.
>
> **Read §20 before touching `ollama_client`.** The window is now *sent* on every request.
> `ollama_num_ctx` was a number that only fed the budget arithmetic, so raising it in `.env`
> made the app budget against a window Ollama had never agreed to — the B26 failure,
> re-armed by the obvious remedy. Two independent guards now watch the result.
>
> **Read §23 before writing an assertion that observes a request, and before
> adding a cache.** Two traps there are about the *checking* and the *caching*
> rather than the product: a capture that kept only the **last** request, so the
> guard read a `/api/show` probe instead of the `/api/generate` under test and
> passed only while a cache was warm; and a cache sentinel of `0.0` compared
> against `time.monotonic()`, whose origin is arbitrary and small on some
> platforms. Both were correct code with a wrong witness.
>
> **Read §21 before trusting any test gate, and before adding a `reason` string to
> `service_health.py`.** Two traps there are about *the checking*, not the checked: a summary
> parser that reported 0 failures for a suite with 15, and a field and its sentence
> disagreeing because they read different variables. A gate that reads "0" for a script which
> did not pass converts a red suite green — which is the one outcome this file exists to stop.
>
> **§22 is three habits, and it is the shortest useful section here.** Every bug in the list
> above shares one cause: verification that reported success without measuring anything.

---

## 0. Read this first — branch topology is a trap

This repo has **four long-diverged branches**. `git log` on any one of them tells you almost nothing about
the others. They share only a common ancestor.

| Branch | HEAD | Notes |
|---|---|---|
| `main` | — | GitHub **default branch**. Oldest. Not the working branch. |
| `Main2` | `0687a86` | "Government-grade" amber/steel UI. **Has the docs** (`AGENTS.md`, `CLAUDE.md`, `CFI_Setup_Guide.md`). |
| `main3` | `e8d1990` | **← You are here.** Indigo/violet redesign + light-mode CSS-var refactor, + the ingestion pipeline rework (§13). **Docs were lost in the redesign** — this file restores them. |
| `ui-redesign` | — | Experimental, unreviewed. |

`git merge-base origin/Main2 main3` → `3dbdd49`. Everything after that point is independent work on each branch.

**Consequences:**
- `main3` **deleted** `AGENTS.md`, `CLAUDE.md` and `CFI_Setup_Guide.md`. This file restores the first one.
- `Main2` still has two components that `main3` **deleted**:
  `frontend/src/pages/ModernDashboard.jsx` and `frontend/src/components/LiveIngestionHardwareMonitor.jsx`.
  If you need them: `git show origin/Main2:<path>`.
- The two branches use **incompatible CSS variable namespaces**. See §7 — this is the single biggest
  source of confusion when porting UI between them.

---

## 1. What the project is

**Intelligent Digital Forensic AI Assistant** — an offline, local-only AI digital-forensics workstation.
Upload evidence → extract text/metadata → index into a vector store → query with natural language →
reconstruct timelines, entity graphs and anomalies. Nothing leaves the machine (air-gap requirement).

Scale: **~13.2k lines** Python (57 files) · **~14.8k lines** React/JS/CSS (58 files) · 0 TODO/FIXME markers in code.

---

## 2. Architecture

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React 18 + Vite 5 + Tailwind 3 | `frontend/`, dev server **port 3000**, proxies `/api` → `:8000` |
| Backend | FastAPI 0.110 + Uvicorn | `backend/main.py`, port 8000 |
| ORM/DB | SQLAlchemy 2.0 + SQLite | `data/forensic.db`, **14 tables** |
| Vector store | Qdrant (embedded, local) | `data/cases/<case_id>/qdrant/` |
| Embeddings | **local `all-MiniLM-L6-v2` via SentenceTransformers**, 384-dim | 🔴 `requirements.txt` declares torch/sentence-transformers *absent* — **fixed in B15 (§15)**: both are now imported lazily inside the function, so the backend starts without them and only embedding needs them. Do **not** switch to an Ollama embedder casually: that is 768-dim and invalidates every existing collection. |
| LLM | Ollama, default `llama3.2:3b` | |
| NER | spaCy 3.7 `en_core_web_lg` | GPU disabled by design for cross-platform stability |
| Disk images | `pyewf` + `pytsk3` (Sleuth Kit) | installed here: pyewf `20260924`, pytsk3 `20260715` |
| Reports | ReportLab → PDF | |

### Where things live

```
backend/
  main.py                 FastAPI app, router registration, middleware
  models.py               SQLAlchemy ORM models
  schemas.py              Pydantic request/response models
  auth.py                 JWT issue/verify, bcrypt hashing
  database.py             engine + session factory
  dependencies.py         shared FastAPI deps
  ingestion.py            file ingestion dispatch + forensic pipeline driver
  seed_demo.py            idempotent demo-data seeder
  clear_demo_cases.py     demo data cleanup
  migrate_all.py          ← run this for migrations; calls all migrate_*.py
  routers/                audit, auth_router, cases, case_access, credentials,
                          entities, evidence, notes, queries, queue_router,
                          reports, watchlist
  modules/
    forensic_ingestion.py   ★ pyewf/pytsk3 walk + per-file extraction  (has bugs, §6)
    rag_engine.py           retrieval + prompt + citation processing
    vector_store.py         Qdrant wrapper  (🔴 stale torch import, §2)
    hardware_probe.py       ★ live hardware + device inventory (CPU/GPU/volumes/NICs)
    gpu_telemetry.py        ★ live GPU utilisation + VRAM via NVML/ctypes (§16)
    ollama_client.py        Ollama HTTP client
    graph_builder.py        NetworkX entity graph
    job_worker.py           background ingestion worker
    registry_parser.py      Windows registry hive parsing
    credential_scanner.py   password/secret finding
    entropy_analyzer.py     Shannon entropy
    anomaly_detector.py     anomaly rules
    media_extractor.py      audio/video/email/office extraction
    report_generator.py     ReportLab PDF builder
    resource_governor.py    RAM/CPU throttling for the worker
    time_estimator.py       job duration estimates
    file_store.py           evidence file storage
frontend/src/
  App.jsx                 routing + AppLayout (sidebar + statusbar + <main>)
  api/client.js           axios instance + ~90 API functions
  context/                AuthContext, ThemeContext
  hooks/                  useNotifications, useWebSocket, useTilt, useCountUp,
                          usePreferences (★ gates the resource monitor)
  components/             Sidebar, StatusBar, PageLayout, AppBackground, FileViewer,
                          GlobalSearch, cards, ErrorBoundary, ProtectedRoute,
                          ResourceMonitor (★ live hardware panel)
  pages/                  27 route components
  index.css               ★ design tokens  (namespace differs per branch, §7)
```

---

## 3. Setup & run

### Windows
```cmd
setup_windows.bat          :: once
start_windows.bat          :: ollama + backend + frontend
```
Manual:
```cmd
ollama serve
call venv\Scripts\activate.bat && set PYTHONPATH=. && uvicorn backend.main:app --host 0.0.0.0 --port 8000
cd frontend && yarn dev
```

### Linux / macOS
```bash
./setup.sh        # once
./start.sh
```
Manual:
```bash
ollama serve
source venv/bin/activate && PYTHONPATH=. uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev
```

> ⚠️ **Port mismatch:** `start_windows.bat` prints `http://localhost:5173` but `frontend/vite.config.js`
> pins **port 3000**. 5173 is only the Vite fallback. Trust 3000.

### Migrations & demo data
```bash
PYTHONPATH=. python backend/migrate_all.py     # Windows: venv\Scripts\python.exe backend\migrate_all.py
PYTHONPATH=. python backend/seed_demo.py       # idempotent
```
Demo logins: `admin` / `Admin@IDF2025` (Admin), `det_markov` / `Markov@2025`, `analyst_chen` / `Chen@2025`.

### Health checks
- `GET http://localhost:8000/api/status` — DB + Ollama health
- `GET http://localhost:8000/docs` — Swagger
- Frontend: <http://localhost:3000>

---

## 4. Feature inventory (all implemented)

Case management · evidence ingestion (PDF/DOCX/XLSX/PPTX/images/audio/video/email/MSG/E01/DD/raw) ·
background queue with live WebSocket progress + CPU/RAM throttling · SHA-256 chain of custody ·
RAG Q&A with citations & confidence · entity NER + force-directed graph · AI entity profiles ·
timeline · anomaly detection (entropy + timestamp) · geo/EXIF map · keyword watchlist ·
PDF reports (5 types) · audit log + global activity feed + CSV export · JWT auth, 4-tier roles,
lockout, rate limiting · **2FA/TOTP** · **credential scanner** · **contradiction detection** ·
**artifact comparison** · **AI case summary** · **case access control** · **case import/export** ·
**system health page** · **live hardware & device inventory** · **per-user UI preferences** ·
global search · dark/light theming.

> The `README.md` on `main3` documents only ~22 of the 27 pages and **omits** 2FA, credentials,
> contradictions, comparison, case summary, case settings, system health, import/export.
> **The README is stale — trust this file over it.**

---

## 4b. Hardware & device detection (added this session)

`backend/modules/hardware_probe.py` auto-detects the machine the app runs on. It is **live, not
static** — a forensics box gains and loses devices between cases, so everything is re-detected.

| Exposed via | What it returns |
|---|---|
| `hardware_probe.scan_hardware()` | full re-walk, no cache |
| `hardware_probe.get_hardware_spec(force=False, ttl=4.0)` | cached ≤4 s, **auto-invalidated by a device fingerprint** (partition list + NIC list), so plugging in a drive takes effect immediately |
| `hardware_probe.rescan_hardware()` | forced re-scan; backs `POST /api/queue/system-info/rescan` |
| `resource_governor.get_system_info()` | thin wrapper that adds back the legacy `cpu_count` / `platform` aliases |
| `GET /api/queue/system-info` | `{ system, hardware, suggested_budget }` |
| `POST /api/queue/system-info/rescan` | same shape + `rescanned: true` |

**Detected:** CPU model + physical/logical cores + clock · **every** GPU with VRAM and
shared-vs-dedicated · **every** mounted volume (`all=True`, so USB/removable appears) with
fstype, rw/ro, free/total, and an `is_evidence_store` flag · network adapters with MAC/IP/up/virtual
· chassis manufacturer/model/BIOS/hostname · battery + laptop detection · swap/pagefile · OS.

**Constraints honoured** (§9): stdlib + `psutil` only, **no new dependency**, and **no shell calls**.
Windows reads the registry via `winreg` (`Video\*\0000` for GPUs, `CentralProcessor\<n>` for CPU,
`BIOS` for the chassis); Linux reads `/proc` and `/sys/class/drm`; macOS reports no GPU rather than
guessing.

Two traps found while building it — do not reintroduce them:
- `winreg.OpenKey(... r"CentralProcessor\0")` **intermittently reports zero values**. Enumerate the
  parent's subkeys instead.
- `mem.total / 1024 * 1024` is `mem.total` (operator precedence). This shipped once and every
  memory figure came back as raw bytes. `verify_dynamic.py` now asserts MB ranges to catch it.

**Frontend:** `frontend/src/components/ResourceMonitor.jsx` is shared by the **Evidence page and
the Queue page** so both show an identical description. It renders `null` and stops polling when
`show_system_resources` is off — the gate lives in exactly one place, so the preference governs
both surfaces by construction.

Its default view is deliberately short: **CPU / memory / GPU as three independent gauges**, a VRAM
meter, a per-core strip and a storage line. Behind a **"Show device details"** disclosure sit only
the things that bear on an ingest: the per-adapter GPU rows (which is where "this adapter exposes
no utilisation counter" is actually stated), the CPU/RAM/pagefile the ingestion budget is derived
from, battery state, and the mounted volumes.

**Deliberately not shown, though the backend still returns them:** `network_adapters` and the
machine's identity block (`machine_manufacturer`, `machine_model`, `bios_version`, `hostname`,
`platform_*`). A NIC list carries no information about resource use, and identifying the host is
not resource monitoring — the audit log already records what machine a case was worked on. They
remain in `hardware_probe`'s output for anything that needs them; they just do not occupy screen
space next to a running transcription. Two rounds of trimming got here: the first kept the whole
inventory behind a toggle, the second removed the parts of it that were reference material rather
than ingest-relevant.

---

## 5. Work completed (by branch)

**`main3` (current)** — baseline v1.0 → docs/setup → UI redesign + ingestion speedup → fixed
"No response" bug → real-time response display → WebSockets → **dropped PyTorch/SentenceTransformers
for Ollama embeddings (fixed OOM crashes)** → light-mode CSS-variable refactor → notifications
dropdown → published to a public GitHub repo → **CFI → "Intelligent Digital Forensic AI Assistant"
rename** → **Main2 sidebar placement restored** → **per-user UI preferences (resource-monitor
toggle)** → **live hardware & device inventory**.

> ⚠️ The "dropped PyTorch/SentenceTransformers" entry above is **half true**: the *pins* were
> removed from `requirements.txt` but `vector_store.py` was never converted. See B6.

**`Main2`** — diverged at `3dbdd49`: amber/steel "government-grade" design system (Barlow Condensed +
JetBrains Mono, classified status bar, terminal login, command-center layout), complete light-mode
overhaul, 10MB–200MB test evidence generators, Ollama idle-unload + CUDA/RAM cache clearing,
RAG prompt-size optimisation, TOTP/embedding-model fallback fixes, Apple-Silicon MPS support.

---

## 6. Known bugs — verified, with root causes

### ✅ FIXED B1. Raw/forensic images silently reported "0 artifacts"

**Symptom (was):** upload a `.001`/`.dd` image → job went `Completed — 0 artifacts` in ~5 s, evidence
was marked `Indexed`, **no error ever shown**. Investigator believed the file was processed.

**Root cause 1 — silent failure (code defect, fixed).** `forensic_ingestion.py` wrapped every
`pytsk3.FS_Info()` attempt in a bare `except Exception: continue`, discarding the real TSK diagnostic.
If no filesystem opened, the generator simply ended and the caller marked the job successful.

**Root cause 2 — the sample evidence file is truncated (data problem, NOT a code regression).**
Measured on `data/cases/f15d31a9-.../evidence/8fe98ee9-..._SCHARDT.001`:

| Property | Value |
|---|---|
| File size on disk | 666,238,976 B (**635 MB**) |
| MBR partition 0 | start LBA 63, 9,510,417 sectors, type `0x07` (NTFS) |
| NTFS volume size declared by boot sector | 4,869,332,992 B (**4.53 GB**) |
| Bytes of that volume actually present | 635 MB → **13.7 %** |
| `$MFT` location (`MFT LCN` 2,097,152 × 512) | 1.00 GB into the volume → **407 MB past EOF** |

`pyewf` is *not* involved: the file has no `EVF\x09\x0d\x0a\xff\x00` signature, it is a genuine raw
image (MBR boot sig `55AA` at 510, valid NTFS OEM id `NTFS    ` at +3, sig `55AA` at +510).
TSK cannot initialise NTFS without the MFT, so it reports the misleading
`Cannot determine file system type`, which the `except: continue` then hid.

**For this specific file, "0 artifacts" is the correct outcome** — it is an incomplete copy and must
be re-acquired. The genuine bug was that the app claimed success.

**What was changed** (`forensic_ingestion.py` + `ingestion.py`):
- New `_walk_all_filesystems()` — collects per-partition mount failures and **raises `RuntimeError`
  with the real TSK diagnostics** when nothing mounts, instead of silently yielding nothing.
  Replaces the duplicated `try/except/continue` blocks in both `ingest_e01` and `ingest_raw`.
- New `inspect_raw_image()` — parses MBR + boot sectors **without mounting**, returning per-partition
  `{declared_bytes, present_bytes, truncated}`. Detects truncation before any work starts.
- New `detect_image_format()` — sniffs EWF/LVF magic bytes (see B2).
- `ingest_raw` now warns loudly on a truncated image but **still attempts partial recovery**, so any
  recoverable files are kept (forensic value preserved).
- `ingestion.py` marks evidence **`Failed`** with a `FILE_INGEST_FAILED` audit entry (severity `error`,
  registered in `audit_helper.SEVERITY_MAP`) when a truncated image yields 0 artifacts — it is no
  longer marked `Indexed`.
- `walk_filesystem`, `extract_file_content`, `EWFImageInfo` are **byte-for-byte unchanged** (verified
  via `git diff`: every hunk is at line 507+).

Verified against the real file: correct truncation report, and a `RuntimeError` carrying the actual
TSK error instead of a silent 0.

### ✅ FIXED B2. `.001` was routed as a raw image

`ingestion.py` did `if ext == '.e01': ingest_e01(...) else: ingest_raw(...)`. But `.001` is the
**standard EWF split-segment extension**, so a genuine multi-segment EWF set was handed to
`pytsk3.Img_Info()`, which cannot read EWF-compressed segments → guaranteed 0 artifacts.
It happened to work for `SCHARDT.001` only because that file is *actually* raw despite its name.

Now routed by **content**: `detect_image_format()` checks the first 8 bytes for an
`EVF`/`LVF` signature. Verified: synthetic EWF header → `ewf`; `.001` with raw content → `raw`.

### ✅ FIXED B3. `requirements.txt` was corrupted → Whisper would not install

The file was ASCII/UTF-8 for the first 945 bytes, then the final line was **UTF-16LE**, so
`pip install -r requirements.txt` could not parse `openai-whisper==20231117` and **git treated the
whole file as binary** (`git diff` said `Binary files differ`). Rewritten as clean UTF-8/LF;
`git diff` now shows a reviewable text diff. Verified: no NUL bytes, 35 requirement lines,
`openai-whisper==20231117` readable.

### ✅ FIXED B4. `requirements.txt` still pinned PyTorch — the OOM fix was silently reverted

`0be7d9a` removed SentenceTransformers/PyTorch from the code to stop OOM crashes, but the pins
remained and `vendor/` bundles a 152 MB `torch-2.3.0` wheel nothing imports. Both pins
(`torch==2.3.0`, `sentence-transformers==2.7.0`) are now **removed**, with an inline comment warning
future agents not to re-add them. **Remaining:** `vendor/python/torch-2.3.0-*.whl` is still on disk
and should be deleted so the air-gap kit stops shipping dead weight.

### 🔴 OPEN B5. Ollama-offline path wastes 25 s and returns an error string as an answer

`data/forensic.db` shows a `QUERY_MADE` audit entry with
`raw_llm_response = "⚠️ Ollama is offline. Please start Ollama and try again."` and
`response_time_ms = 24708`. The offline check happens *after* the timeout, so the UI shows a
24.7 s "thinking" pause and then stores an error as if it were a model response.
**Fix:** probe Ollama's health endpoint before starting a generation request.

### ✅ FIXED B10 / B11 / B12 — found by the live end-to-end run

Three further silent-success defects, all the same shape as B1, all fixed and all
regression-tested. **Read §14 before touching the ingestion path** — the short version is
that a failed vector-store write used to finish as `Completed — 0 chunks` with the
evidence marked `Indexed`, and a failed job used to stay `Running` for ever.

### ✅ FIXED B13 / B14 / B15 — the Stop button, Qdrant isolation, the import

**Read §15 before touching the vector store, the hash step, or the stop path.**
The short version: Stop was correctly wired end to end and still useless, because the
longest steps never asked (34.7 s → 1.0 s after the fix); `get_client` served every
case the *first* case's Qdrant client, silently cross-contaminating cases; and
`import backend.main` still required two packages `requirements.txt` omits.

---

## 7. Traps when porting UI between `main3` and `Main2`

The two branches have **incompatible design-token namespaces**. Copying a file between them silently
produces unstyled/invisible elements.

| Purpose | `main3` (current) | `Main2` |
|---|---|---|
| surfaces | `--surface-0 … --surface-5` | `--bg-app`, `--bg-sidebar`, `--bg-panel`, `--bg-panel-raised`, `--bg-hover`, `--bg-active` |
| text | `--ink-0 … --ink-3` | `--text-heading`, `--text-primary`, `--text-secondary`, `--text-muted` |
| borders | `--line-DEFAULT`, `--line-bright` | `--border-base`, `--border-strong` |
| brand | **hardcoded hex** in `tailwind.config.js` (`#4f46e5` indigo) | CSS vars (`--brand-primary`, amber `#D4A32A`) |
| heading font | system / Inter | `'Barlow Condensed'` + `'JetBrains Mono'` |
| theme flag | — | `isModernLight` from `ThemeContext`, `data-modern-light` attr on `<main>` |

`main3` also **removed** the `<div data-modern-light={...}>` wrapper on `<main>` in `App.jsx` and the
`isModernLight` consumption. Any `Main2` component relying on that attribute needs it re-added.

**Open decision (not yet actioned):** the user wants the **`Main2` GUI placement/layout** restored
while keeping `main3` functionality. The affected files are:
`index.css` (853 lines differ), `Sidebar.jsx` (704), `StatusBar.jsx` (398), `LoginPage.jsx` (1087),
`DashboardPage.jsx` (1002), `AppBackground.jsx` (113), `StatCard.jsx` (110), `AnimStatCard.jsx` (88),
`CasesPage.jsx` (194), `tailwind.config.js` (103), `App.jsx` (18), `PageLayout.jsx` (44).
This is a **token-namespace migration, not a file copy** — do it token-first, then component-by-component.

---

## 8. Local-only artefacts & remotes

**The working tree is clean.** The Windows/air-gap porting work that §8 used to
list as uncommitted (§12) has since landed. `git status` should be empty on a
clean checkout.

### `vendor/` — air-gap install kit, deliberately NOT in git

`.gitignore:106` excludes `vendor/`, and it must stay that way. It holds
**~1.1 GB** of pre-downloaded wheels plus the spaCy `en_core_web_lg` tarball, and
several files exceed GitHub's 100 MB per-file limit — committing it breaks the
push and bloats history permanently. It is a **local artefact**: distribute it as
a zip or release asset if an air-gap installer is needed, never as tracked source.

Regenerate it with:
```bash
pip download -r requirements.txt -d vendor/python
python -m spacy download en_core_web_lg   # then move the tarball into vendor/python
```

> **Housekeeping (unfinished, B4):** `vendor/python/torch-2.3.0-cp312-cp312-win_amd64.whl`
> is **152 MB** on disk that nothing imports — `requirements.txt` no longer pins
> torch and `ingestion_modes.transcription_device()` imports it *opportunistically*,
> falling back to CPU. Deleting it removes dead weight from the air-gap kit. Note
> that a CUDA build of torch is what §13 says is needed to enable GPU
> transcription, so keep or replace it deliberately rather than reflexively.

### ✅ Security: remotes are credential-free

Earlier revisions of this file warned that the origin URL embedded a GitHub
personal access token. That is fixed — both remotes are now plain HTTPS URLs
with no inline credentials, and no `PAT`/`ghp_`-style string remains anywhere in
`.git/config`:

```
idfa    https://github.com/sarvagnasrao/Intelligent-Digital-Forensic-AI-Assistant.git
origin  https://github.com/Shrishacm/Cognitive-Forensic-Investigator.git
```

`main3` tracks `idfa/main`; push with `git push idfa main3:main`. **Keep it that
way** — do not re-embed a token to make a push work. If a push starts demanding
credentials, that is a credential-helper or auth problem to fix locally, not a
reason to put a secret in the remote URL.

---

## 9. Conventions & gotchas

- **Paths:** always `os.path.join()` / `pathlib`. Never hardcode `/` or `\`.
- **No OS shell calls** from Python (`grep`, `cat`, `ls`). Use `os`, `shutil`, `glob`.
- **pyewf on Windows:** needs an absolute, normalised path. `forensic_ingestion.py:529` already does
  `os.path.abspath(...).replace("\\./", "\\")` — keep that, it prevents a hard crash.
- **spaCy GPU is disabled on purpose** for CUDA-version portability. Do not "fix" this.
- **Migrations are additive scripts** (`migrate_*.py`) orchestrated by `migrate_all.py`. Add a new
  script and register it there; never edit `models.py` alone and expect an existing DB to update.
- **Auth:** first registered user becomes Admin; later ones default to Analyst and need manual promotion.
- **Evidence files are stored under** `data/cases/<case_id>/evidence/`; disk-image extractions go to
  `.../evidence/<evidence_id>/extracted/`. Per-case Qdrant lives at `data/cases/<case_id>/qdrant/`.
- **Demo seeder is idempotent** — safe to re-run.

---

## 10. Verification commands

```bash
# backend imports + syntax
PYTHONPATH=. python -c "import backend.main; print('backend OK')"

# frontend build
cd frontend && npm run build        # or: yarn build

# spaCy model present
python -c "import spacy; spacy.load('en_core_web_lg'); print('spaCy OK')"

# forensic libs present
python -c "import pyewf, pytsk3; print(pyewf.get_version(), pytsk3.get_version())"

# migrations idempotent?
PYTHONPATH=. python backend/migrate_all.py && PYTHONPATH=. python backend/migrate_all.py
```

### Behavioural checks (`tests/`)

These run the real pipeline, the real event loop and the real HTTP API — not
mocks. Each prints `PASS`/`FAIL` per assertion and exits non-zero on failure.
See `tests/README.md` for details.

```bash
PYTHONPATH=. python tests/verify_ingestion_modes.py    #  39 assertions, ~15 s
PYTHONPATH=. python tests/verify_ws_progress.py        #  15 assertions, ~10 s
PYTHONPATH=. python -W error::RuntimeWarning \
                    tests/verify_ws_progress.py       # also catches coroutine leaks
PYTHONPATH=. python tests/verify_queue_api.py          #  51 assertions, ~5 s
PYTHONPATH=. python tests/verify_job_stop.py           #  17 assertions, ~20 s
PYTHONPATH=. python tests/verify_forensic_failure.py   #  15 assertions, ~30 s
PYTHONPATH=. python tests/verify_vector_store.py       #  17 assertions, ~10 s
PYTHONPATH=. python tests/verify_cpu_sampler.py        #   9 assertions, ~10 s
PYTHONPATH=. python tests/verify_gpu_telemetry.py      # 171 assertions, ~20 s
PYTHONPATH=. python tests/verify_eta.py                #  59 assertions, ~10 s
PYTHONPATH=. python tests/verify_file_formats.py       # 153 assertions, ~15 s
PYTHONPATH=. python tests/verify_prompt_budget.py      #  85 assertions, ~30 s
PYTHONPATH=. python tests/verify_service_health.py     # 209 assertions, ~40 s
PYTHONPATH=. python tests/verify_evidence_archive.py   #  38 assertions, ~15 s
PYTHONPATH=. python tests/verify_live_stack.py         #  26 assertions, ~90 s
```

Windows: `$env:PYTHONPATH="."` then `venv\Scripts\python.exe tests\<name>.py`.

The first **fourteen** are self-contained; **878 assertions total**. `verify_live_stack.py`
is the exception — it needs `ollama serve`, uvicorn on `:8000` and Vite on
`:3000` already running, and it is the only one that crosses a real socket
(see §14). All of them clean up every row and per-case Qdrant directory they
create, and are safe to re-run.

> **Run the self-contained ones with the servers stopped.** A backend already
> running on the same `data/forensic.db` has its own worker thread, and that
> worker selects `Queued` jobs. A test fixture left in `Queued` therefore gets
> picked up and executed in a *second process*, which then loses the race for
> the same per-case Qdrant directory and reports
> `Storage folder ... is already accessed by another instance of Qdrant client`.
> The fix is on both sides: tests insert fixture jobs as `Running` (the worker
> only ever selects `Queued`), and the server is stopped for the test run.
> See §15 for why that error is a symptom rather than the disease.

### Inspecting a disk image by hand (when 0 artifacts)
```python
import pytsk3, os
p = "<path to image>"
print("size:", os.path.getsize(p))
img = pytsk3.Img_Info(p)
for part in pytsk3.Volume_Info(img):
    print(part.addr, part.start, part.len, part.desc, part.flags)
    if part.flags == pytsk3.TSK_VS_PART_FLAG_ALLOC:
        fs = pytsk3.FS_Info(img, offset=part.start * 512)   # raises if unopenable
        print("  ->", fs.info.ftype)
```
Compare `os.path.getsize(p)` against `part.start + part.len` sectors × 512 — if the file is smaller,
**the image is truncated** and no filesystem walk can succeed. That is bug B1, not a code regression.

---

## 11. Suggested next actions, in priority order

1. ~~Rotate the leaked GitHub PAT~~ ✅ done — both remotes are credential-free (§8).
2. ~~Commit the air-gap/Windows porting work~~ ✅ done — working tree is clean (§8).
3. ~~Fix B1~~ ✅ done — see §12.
4. ~~Fix B2~~ ✅ done — see §12.
5. ~~Fix B3 + B4~~ ✅ done (except deleting the vendored torch wheel) — see §12.
6. ~~Fix B7/B8/B9~~ ✅ done — live progress, device-synced limits, real throttling (§13).
7. **Fix B5** — probe Ollama before starting the request.
8. **Decide the GUI question** (§7) — restore `Main2` layout onto `main3` via token migration.
9. **Refresh `README.md`** against the real feature set, and restore `CLAUDE.md` / `CFI_Setup_Guide.md` from `Main2`.
10. **Keep this file updated** as work lands.

---

## 12. Changelog of agent work

### Raw/forensic image fixes (committed)

Files changed: `backend/modules/forensic_ingestion.py`, `backend/ingestion.py`,
`backend/modules/audit_helper.py`, `requirements.txt`, `AGENTS.md`.

- B1 fixed: real TSK errors now surface; truncation pre-flight; truncated+0-artifact evidence is
  marked `Failed`, not `Indexed`. `walk_filesystem` / `extract_file_content` untouched.
- B2 fixed: EWF vs raw chosen by magic bytes, not file extension.
- B3 fixed: `requirements.txt` rewritten as clean UTF-8.
- B4 fixed: `torch` / `sentence-transformers` pins removed.
- B5 still open.
- `vendor/python/torch-2.3.0-*.whl` still needs deleting (152 MB dead weight — but see the
  caution in §8: a CUDA build of torch is what §13 needs for GPU transcription, so replace
  rather than reflexively delete).

**Verification performed:** backend imports OK · `py_compile` OK · against the real
`SCHARDT.001`: correct truncation report + `RuntimeError` carrying the true TSK error (no longer a
silent 0) · synthetic EWF header detected as `ewf` · `requirements.txt` parses with no NUL bytes.

**Not yet verified:** a full end-to-end ingest of a *valid, complete* raw image (would need a real
forensic image or a correctly constructed test fixture). The mount path was confirmed to mount a
valid FAT16 volume successfully; the risk is low because the walk/extract code is unchanged. Still
unproven after §13 as well.

**Committed:** the air-gap/Windows porting work and these fixes. Working tree is clean (§8).

### Still to do

1. ~~Rotate the leaked GitHub PAT~~ ✅ done — both remotes are credential-free (§8).
2. ~~Commit the air-gap/Windows porting work~~ ✅ done — working tree is clean (§8).
3. ~~Fix B4's stale import~~ ✅ done — B15 (§15): torch/sentence-transformers are lazy now.
4. **Delete `vendor/python/torch-2.3.0-*.whl`** (finishes B4, 152 MB of dead weight — but read the note in §8 first, a CUDA build is what GPU transcription needs).
5. **Fix B5** — probe Ollama health before starting a generation request.
6. **Decide the GUI question** (§7) — restore `Main2` layout onto `main3` via token migration.
7. **Refresh `README.md`** against the real feature set; restore `CLAUDE.md` /
   `CFI_Setup_Guide.md` from `Main2`.
8. **Decide the embedding backend** (§15) — staying on local SentenceTransformers is
   deliberate; moving to Ollama is 768-dim and needs a full re-index.
9. **Keep this file updated** as work lands.

---

## 13. Ingestion pipeline: progress, resource budget, and three profiles

New files: `backend/modules/ingestion_modes.py`, `backend/migrate_ingestion_mode.py`,
`frontend/src/hooks/useSystemInfo.js`, `tests/`.

### ✅ FIXED B7. Live ingestion progress never reached the browser

**Symptom:** the job row sat at 5 % (or jumped 0 → 100) and the bar froze.

**Two independent root causes, both silent by construction.**

1. **Cross-loop WebSocket sends.** `job_worker` ran the ingestion on a
   background thread but built a *brand new* event loop inside that thread
   for each broadcast, then awaited `_notify_case` on it. The `WebSocket`
   objects had been accepted on the *server's* loop, so the sends could not
   land. Now the server loop is captured at startup
   (`job_worker.set_main_loop()` in `main.py`'s lifespan) and broadcasts are
   scheduled with `asyncio.run_coroutine_threadsafe`. The three throwaway
   `run_until_complete` blocks are gone.
2. **A callback arity mismatch behind a bare `except: pass`.** This is the one
   that actually cost every intermediate tick. `run_ingestion_with_progress`
   defined `_progress(percent, step)` and handed *that* to the sub-pipelines
   as their `progress_callback`. The sub-pipelines correctly called the
   documented 5-argument contract
   `progress_callback(case_id, job_id, evidence_id, percent, step)`, so every
   call raised `TypeError: _progress() takes 2 positional arguments but 5
   were given` — inside `except Exception: pass`. The database row still
   advanced (that path is separate), so the job *looked* alive server-side
   while the socket emitted exactly one event. Fixed by introducing an
   explicit 5-argument `_dispatch(cid, jid, eid, percent, step)` and passing
   *that* to the sub-pipelines. The bare `pass` is now a printed error.

**Also fixed while in there:**
- The forensic path called `_update_job_progress` directly at every stage, so
  a disk image — the slowest ingest in the product — emitted **no** WebSocket
  events at all. It now uses the same dispatcher.
- Non-monotonic progress: the forensic path went `85 → 75 → 90`, so the bar
  moved backwards mid-job.
- Step 3 recomputed as `40 + int((done/total)*30)` over the band the step
  actually owns, replacing `i/len(chunks)` computed *after* the batch was
  stored (always one batch behind, never reached 70 before jumping to 75).
- Added `_finish_job_no_text()` — a file yielding no text left the job stuck
  at "Running" 10 % forever.

**Trap — do not reintroduce:** a loop that is *registered but not spinning*
accepts `run_coroutine_threadsafe` and then never runs the coroutine, so the
event vanishes with no error and the coroutine leaks ("was never awaited").
`_notify` checks `loop.is_running()` as well as `is_closed()`, and closes the
coroutine on a scheduling failure.

### ✅ FIXED B8. The RAM limit was a hardcoded 8 GB, unrelated to the machine

The "8 GB" the operator saw was `max="8"` on an HTML range input in
`EvidencePage.jsx`, with hardcoded labels `0 GB (override) / 2 GB (safe) /
8 GB (cautious)`. Behind it, `suggest_resource_budget()` branched on a fixed
8/16/32 GB ladder. Nothing in that path consulted the hardware.

`ingestion_modes.suggest_budget()` now derives everything from the live probe
(available RAM, physical/logical cores, laptop + battery, discrete GPU) and
returns the **slider bounds** alongside the defaults: `ram_floor_min_mb`,
`ram_floor_default_mb`, `ram_floor_max_mb`, `cpu_min_percent`,
`cpu_max_percent`, `total_ram_mb`, `available_ram_mb`, `gpu_acceleration`,
`description`, `health`, `max_parallel_files`.

On the dev box (15.9 GB RAM, 4C/8T, GTX 1050 Ti) that is a 1792 MB default
floor and a 7168 MB ceiling, replacing the fixed 8192 MB.

The old `suggest_resource_budget()` survives as a thin shim over
`suggest_budget()` for signature compatibility; its `total_ram_mb` argument is
ignored because the probe is authoritative.

### ✅ FIXED B9. Resource throttling was disabled for every job

`check_and_throttle` contained an unconditional `self.force_override = True`,
which short-circuited both the RAM and the CPU check — so the queue page's
limits were decorative. The governor now:

- honours `force_override` only when the constructor sets it;
- ramps `get_sleep_seconds(cpu_percent)` from *measured* load against the
  ceiling (at a 70 % ceiling: 0 s at ≤70 % load, 0.75 s at 100 %) instead of a
  flat 1 s per batch;
- waits for RAM in 2 s slices honouring stop, bounded by
  `ram_wait_seconds = 120` so a busy machine cannot produce a queue that
  never drains;
- records `last_reason`, `total_throttle_seconds`, `total_pauses`, and
  supports `update_limits()` for live changes.

`job_worker` keeps a `_live_governors` registry, so `PATCH /queue/{id}/settings`
on a *running* job takes effect immediately and reports `applied_live: true`.

### ✅ NEW — three ingestion profiles

`backend/modules/ingestion_modes.py` is the single source of truth; the worker,
the estimator and the UI all read it, so they cannot disagree.

| | `fastest` | `normal` | `accurate` |
|---|---|---|---|
| chunk size / overlap | 30000 / 0 | 20000 / 0 | 8000 / 400 |
| embed batch | 256 | 128 | 64 |
| OCR | off | on | on |
| Whisper | `tiny` | `base` | `small` |
| deleted-file recovery | off | off | **on** |
| `MODE_TIME_FACTOR` | 0.55 | 1.0 | 2.6 |

- `GET /api/queue/modes` returns all three already resolved against this
  machine, each under `effective`. It sends the **whole** resolved profile,
  not a hand-picked subset — a subset is a trap, because the first new knob
  added to `MODES` would silently never reach the UI.
- `resolve_mode_for_device()` only ever downgrades the *Whisper size* and
  clamps `max_parallel`; it never silently drops OCR, chunking or
  deleted-file recovery. Every downgrade is returned in `warnings` and
  surfaced in the UI and in the `add_to_queue` response as `mode_warnings`.
- Chunk-size changes affect retrieval granularity, not dimensionality, so
  existing Qdrant collections stay valid (`VECTOR_SIZE = 384`).
- `include_deleted` is the main cost driver on disk images and only `accurate`
  sets it.
- `ingestion_mode` is a nullable `String(20)` on `ingestion_jobs`, added by
  `migrate_ingestion_mode.py` (registry entry 18). Nullable because SQLite
  cannot `ALTER TABLE ADD COLUMN` with a non-constant default; the existing
  row is backfilled to `'normal'` and `resolve_mode_for_device(None)` already
  treats NULL as `'normal'`.
- `estimate_ingestion_time(..., mode_key=)` now scales by `MODE_TIME_FACTOR`.
  It did not before, so all three profiles quoted the identical time.

**GPU honesty:** a GPU in the hardware inventory is not the same thing as
torch being able to drive it. `transcription_device()` (in `ingestion_modes`,
probed once, cached) asks `torch.cuda.is_available()`;
`media_extractor._resolve_whisper_device` delegates to it. If a discrete GPU
is present but torch is a CPU-only build, the profile reports
`whisper_gpu: false` and warns, instead of showing a `(GPU)` badge that turns
out to be false the first time an audio file is queued. `fp16` is tied to the
resolved device rather than hardcoded `False`.

**On this machine:** torch is `2.3.0+cpu`, so `_resolve_whisper_device`
returns `'cpu'` and `normal`/`accurate` emit the "torch reports no usable CUDA
device" warning. A CUDA torch build is required before GPU transcription
actually engages.

### Frontend

- `hooks/useSystemInfo.js` — one shared, module-cached description of the
  machine, consumed by the Evidence-page queue form, the Edit-settings modal
  and `ResourceMonitor`'s rescan. The RAM slider renders **disabled with a
  placeholder** until the budget lands rather than guessing a maximum and
  snapping the value when the real one arrives.
- `EvidencePage.jsx` — `ModePicker` (rendered from the server's profile list,
  so a label cannot drift from the code that implements it), the device-synced
  RAM ceiling, and `governor.reason` on the job row so a throttled job does not
  look hung. A 0 GB floor gets an explicit warning.
- `QueuePage.jsx` — WebSocket-driven live progress (the 3 s poll is kept as the
  safety net for chunk/entity counts and the completed rows), the profile
  badge, and the throttle reason.
- `ResourceMonitor.jsx` — its Rescan button now also invalidates the shared
  budget cache, which is exactly the moment the answer changes.

**Verification:** `py_compile` on all touched Python · `import backend.main` ·
`migrate_all.py` twice (idempotent, 18/18 OK) · `vite build` clean (3384
modules) · **117 behavioural assertions across four scripts, 0 failures**
(see §14 for the live-stack pass and the three bugs it found).

**Re-verified at the end of §15** after B13/B14/B15: the same gate plus the two
new scripts — **151 assertions across six scripts, 0 failures**, including the
live stack over a real socket (26/26, 12 monotonic frames on `/ws/global`).

---

## 14. Live-stack verification, and the three bugs it found

`tests/verify_live_stack.py` exists because §13's suites all drive
`run_ingestion_with_progress` **in-process**. That proves the pipeline and the
broadcaster are correct, but not that uvicorn's own event loop delivers frames
to a real socket — which is exactly the seam B7 lived in. This is the only
check that crosses it.

It requires `ollama serve` + uvicorn on `:8000` + Vite on `:3000`; it waits 90 s
for the backend and skips cleanly otherwise. 26 assertions: services up, auth,
`/queue/modes` and `/queue/system-info` shapes, a real upload, a real queue, and
then a real `/ws/global` socket from which it requires **≥3 monotonic
`INGESTION_PROGRESS` frames, ≥3 distinct percentages, arrival at 100, and a
`Completed` row**. It found three things:

### ✅ FIXED B10. A failed index was reported as a success

**This is the same defect class as B1, in the embedding path — and the most
consequential bug in the repo.**

`vector_store.store_chunks` did `except Exception: e: print(...)` and
`return 0`. Zero is also what it returns when a document legitimately has no
chunks, so the two were indistinguishable. Observed live, in the backend log:

```
QDRANT STORE ERROR: Expecting value: line 1 column 1 (char 0)
[INGESTION] Done: 0 chunks, 0 entities (text, mode=accurate)
```

The job finished **`Completed — 0 chunks`** with the evidence marked
**`Indexed`**. An investigator then searches a case containing nothing and
concludes the evidence was clean. The JSON error is Ollama's embeddings
response failing to parse — Ollama had just been restarted.

- `store_chunks` now returns `0` **only** for empty input and raises
  `VectorStoreError` (with the chunk count, filename, evidence id and the
  underlying exception) for any real failure.
- Guarded by 7 new assertions in `verify_ingestion_modes.py` that force the
  store to raise and assert the job ends `Failed` with a reason and a terminal
  timestamp, and the evidence `Failed` — never `Indexed`.

### ✅ FIXED B11. A failed job stayed "Running" for ever

`_run_document_with_progress` caught its own exceptions, marked the evidence
`Failed`, and **returned normally**. The outer handler in
`run_ingestion_with_progress` and the one in `job_worker` — both of which mark
the job terminal and broadcast `INGESTION_FAILED` — therefore never ran. The
observable result: bar freezes at whatever percent it reached, evidence says
`Failed`, job says `Running`, nothing explains why.

Both handlers now `raise`, so the worker's single handler finishes the job and
broadcasts the failure. The outer handler also distinguishes a **user stop**
from a real failure (`StopIteration` / `"stopped by user"`): Stop now yields
`Stopped` and evidence `Uploaded`, not a red `Failed` row the operator caused
deliberately.

### ✅ FIXED B12. Two different labels for the same profile

`job_worker` set `current_step` and its opening broadcast **only for
`accurate`**, and in a different format from every other frame:

```
Step 1/5: Starting ingestion [mode: accurate]     ← job_worker
Step 3/5: Embedding (64/237 chunks) [accurate]    ← ingestion.py
```

So `fastest` and `normal` showed **no profile at all** on the first frame, and
`accurate` used a second convention. Now one format, `[{key}]`, for all three
modes, and the database row carries a richer `current_step` naming the
transcription model, the device it will run on, whether deleted-file recovery is
on, and whether OCR is off.

### Test-suite hygiene

`verify_live_stack.py` had to hard-delete its own case: the API's
`DELETE /api/cases/{id}` is a **soft** delete (`status → Archived`), which is
correct for chain of custody and wrong for a test. An `atexit` hook now removes
the case on every exit path, including a failed assertion. Verified residue-free:
after a full four-script run the database is back to its pre-test state
(4 cases — 1 real + 3 demo, 1 evidence, 1 job, 16 demo entities).

**Still unproven:** an end-to-end ingest of a **valid, complete** raw/forensic
image. The disk-image progress dispatcher is correct by construction and shares
the code path these tests exercise, and B1's truncation reporting is now
verified end to end over HTTP — but no fixture on disk is a complete image
(`SCHARDT.001` is truncated, §6 B1).

**Still to do:** B5 (Ollama offline probe), the `Main2` GUI question (§7), delete the
vendored torch wheel (§8 — read the note there first), refresh `README.md`.

---

## 15. Stop button, per-case Qdrant isolation, and the optional-dependency trap

Three more defects, found by actually asking "why doesn't Stop work?" rather than
by reading the stop path — which looked correct end to end and had been read
twice before it was tested. `tests/verify_job_stop.py` (17 assertions) and
`tests/verify_vector_store.py` (17 assertions) are the guards.

### ✅ FIXED B13. Stop was acknowledged, then ignored for tens of seconds

`POST /api/queue/{id}/stop` returned 200, `stop_job()` set its `threading.Event`,
`is_stop_requested()` read it, and the governor raised `StopIteration` — every
link in the chain was present and correct. The button was still useless, because
**stopping is cooperative and the longest steps never asked**:

| Step | Checked? | Consequence |
|---|---|---|
| `compute_sha256` over the whole image | **no** | a stop ignored for the entire hash of every byte of evidence, before any progress is reported |
| embedding a batch (up to 64 chunks) | **no** | 34.7 s measured on a loaded 4-core box, at a bar frozen at 40% |
| `graph_builder`'s O(n²) person-pair loop | **no** | its only check ran every 50 spaCy docs — for a short file, exactly once at `i=0` |
| forensic `store_chunks` (all extracted text in **one** call) | **no** | thousands of chunks embedded as a single uninterruptible stretch |

Fixed by threading the stop signal into each of them: `compute_sha256` now takes
`stop_check` and raises between 1 MB reads (also 128× fewer syscalls);
`store_chunks` embeds in `EMBED_SLICE`-sized slices and takes `stop_check`; the
entity pair loop calls the governor every 10 rows. **Measured stop latency on the
same test: 34.7 s → 1.0 s.**

Two traps hit while fixing this — both are the *same* trap as B1/B10:

- `compute_sha256` ends in `except Exception: return ""`. `StopIteration` is a
  subclass of `Exception`, so an unguarded fix **swallows the stop and returns an
  empty hash**, writing `""` to `evidence.sha256_hash` and carrying on as though
  verification had passed. It now re-raises before the generic handler.
- Same in `store_chunks`, where swallowing would report an operator's stop as
  `VectorStoreError` and turn the row red instead of `Stopped`.

**Do not reintroduce:** a bare `except Exception` around any loop that can be
interrupted. Check the re-raise exists.

**Still not interruptible:** Whisper transcription in `extract_text_from_bytes`.
Transcribing a long video is minutes of one library call. It needs segment-wise
transcription to fix properly, and is the one remaining place where Stop is
advisory rather than prompt.

### ✅ FIXED B14. One Qdrant client for every case — silent cross-case contamination

```python
_qdrant_client = None
def get_client(qdrant_path: str) -> QdrantClient:
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(path=qdrant_path)   # path ignored ever after
    return _qdrant_client
```

`qdrant_path` was used to open the client and then **never consulted again**, so
only the first case opened in a process was ever reachable. Every later case was
served that same client: case B's chunks were written into case A's storage
folder, and case B's collection never existed. A search over case B found nothing
and the investigator concluded the evidence was clean — the exact failure mode
B1 and B10 exist to prevent, in a place nobody was looking.

Verified directly: `get_client(A) is get_client(B)` returned `True` before the
fix, `False` after.

The cache is now keyed on a **normalised absolute path**, which fixes a second
failure that the shared client had been masking. Qdrant's embedded mode takes an
*exclusive* lock per directory — verified: two clients on one path in one process
raise `Storage folder ... is already accessed by another instance of Qdrant
client`; two clients on *different* paths are fine. Callers spell the same
directory two ways: `cases.py` uses `os.path.join` (backslashes on Windows) while
`ingestion.py`, `queries.py`, `entities.py` and `evidence.py` use
`f"{cases_dir}/{case_id}/qdrant"` (forward slashes) — the hardcoded `/` that §9
forbids. Keyed on the raw string those are two keys for one directory. `abspath`
+ `normpath` collapses them. (It is also how the `Storage folder ... already
accessed` error was reached in practice: a second process, e.g. a test whose
fixture sat in `Queued` while a live server's worker selected it.)

Also added `close_client()` / `close_all_clients()`, called from
`delete_case_collection()`. Without releasing it, deleting a case removes the
database row while `shutil.rmtree` fails on the locked directory, leaving the
vector store on disk — on Windows that is guaranteed, not likely.

### ✅ FIXED B15. `import backend.main` required two packages `requirements.txt` omits

`vector_store.py` imported `torch` and `sentence_transformers` at module scope
while `requirements.txt` pins neither (B4 removed the pins). On any install that
follows `requirements.txt`, `import backend.main` raised `ImportError` — which
does not degrade the embedding path, it **removes the entire backend**: no
status endpoint, no queue, no cases. An optional, lazily-needed dependency must
never be able to do that. Both are now imported inside the function that needs
them, and the failure names the fix.

Also removed `torch.set_num_threads(4)`, which was applied process-wide at
import: it hardcoded 4 regardless of the machine's core count, and a global
thread-pool override fights `ResourceGovernor`, whose entire job is to cap CPU at
the operator's ceiling. It now sizes off `os.cpu_count()`.

Verified by blocking both imports with a `MetaPathFinder`: `backend.main` and
`backend.ingestion` both import, and embedding then fails with a message that
names the missing package.

**Trap — do not "fix" this by switching to Ollama embeddings.** Despite the name,
`get_ollama_embeddings` uses local SentenceTransformers, and that is load-bearing:
MiniLM-L6-v2 is 384-dim and matches `VECTOR_SIZE`. Ollama's embedder is 768-dim,
so switching **invalidates every existing per-case collection** and forces a full
re-index. It is a migration with its own decision, not a bug fix.

---

## 16. Per-resource hardware telemetry (CPU / GPU / memory, measured separately)

`hardware_probe` (§4b) could already say *which* adapters exist. Nothing could say
how **busy** one is — which is the number that matters during an ingest, because it
is how you tell whether Whisper reached the GPU or quietly stayed on the CPU.

New file `backend/modules/gpu_telemetry.py`. Constraints honoured (§2/§9): **stdlib
+ `psutil` only, no new dependency, no shell calls.** That rules out `nvidia-smi`,
`system_profiler` and `wmic`, so NVIDIA is read through **NVML via `ctypes`** — the
driver library already on the machine, loaded rather than invoked. AMD/Intel on
Linux come from sysfs `gpu_busy_percent` / `gt_busy_percent`, `mem_info_vram_used`.

**New aggregate keys** (per adapter: `util_percent`, `vram_used_mb`,
`gpu_telemetry_reason`): `gpu_util_percent` (busiest adapter, not an average),
`gpu_vram_used_mb`, `gpu_util_available`, `gpu_telemetry_source`
(`nvml`/`sysfs`/`null`), `gpu_telemetry_reason`, `gpu_driver_version`,
`gpu_adapters_measured`, `gpu_adapters_total`. **All legacy keys are preserved**
(`cpu_count`, `platform`, `gpu_names`, `gpu_vram_total_mb`) — the ingestion
budget, the volume list and the evidence-store check all read this same dict, so
`verify_queue_api.py` guards its shape.

CPU sampling was also de-blocking: `_cpu()` called `psutil.cpu_percent(interval=0.3)`,
i.e. a guaranteed **300 ms sleep inside the module lock on every cache miss**, so the
Evidence page's budget request, the Queue page's poll and the worker's governor all
serialised behind a quarter-second pause to produce one number. Now non-blocking
(`interval=None`), primed at import, plus `cpu_per_core_percent`. Forced re-scan
worst case measured **43 ms**, versus a guaranteed 300 ms before.

### 🔴 TRAP 1 — a `_vN` entry point does not share its base's struct

This is the most important thing in this section, and it is a **latent 16-byte stack
buffer overflow that was shipped in the first draft of this module.**

`nvmlDeviceGetMemoryInfo_v2` was called with the 24-byte `nvmlMemory_t` struct, on
the reasonable-sounding grounds that both entry points return memory info. But
`nvmlMemory_v2_t` is a **different, larger** struct — `version, total, reserved,
free, used`, **40 bytes** — so the driver writes 40 bytes through a 24-byte buffer.

It never fired on the dev box, and the reason why is the interesting part: the v2
struct's first field is a **version handshake** (`sizeof(struct) | (2 << 24)`), and
the draft never set it. The driver therefore rejected the malformed request with
`rc=2` *before writing anything*, and the code read that rejection as "v2 is not
supported on this driver" and fell back to v1. **The masked bug and the masking were
the same fact.** Called correctly, v2 works fine on this driver and additionally
reports `reserved` (92 MB on the 1050 Ti).

Two rules, both generalising past NVML:
1. **Never share a struct between an entry point and its `_vN` sibling.** The
   version suffix changes the *layout*, not just the name.
2. **A versioned struct is a request as well as a return value.** The caller fills
   in `version` to tell the driver how much space it has been handed. An
   uninitialised version is not a default, it is a malformed request.

Struct sizes are now `assert`ed at import (24 / 40 / 8), because a wrong-sized
struct is not something to discover at run time on someone else's machine.

### 🔴 TRAP 2 — a 32-bit struct returns SUCCESS while writing nonsense

Measured on this box (driver 582.66), not assumed:

| call | result |
|---|---|
| `nvmlDeviceGetMemoryInfo_v2` called *incorrectly* | `rc=2`, nothing written |
| `nvmlDeviceGetMemoryInfo_v2` called correctly | `rc=0`, total=4096MB, reserved=92MB |
| `nvmlDeviceGetMemoryInfo` (v1) | `rc=0`, total=4096MB, used=479MB |
| `nvmlDeviceGetMemoryInfo` with **32-bit** fields | **`rc=0`** — total=0MB, used=3501MB |

That last row is the dangerous one: it **reports success**. `nvmlMemory_t` is three
`unsigned long long`, so a 32-bit struct hands the callee a 12-byte buffer for a
24-byte write — `total` reads 0 and `used` reads what is really `free`. A
return-code check passes and the panel displays confidently wrong numbers.

**So return code alone is never sufficient. Three layers, all in `_memory`:**
- **The struct is 64-bit.** Non-negotiable.
- **The values are validated** — `total > 0`, `free <= total`, `used <= total`, and
  the fields must *reconcile* — checked in **bytes**, not MB, so integer flooring
  cannot manufacture a violation. The total is then cross-checked against the
  dedicated VRAM the registry reported, within `max(64MB, 5%)`.

### 🔴 TRAP 3 — the reconciliation formula depends on a convention the docs and the driver disagree about

NVIDIA's reference for `nvmlMemory_v2_t.used` describes it as **including**
`reserved`, giving `total ≈ free + used`. Measured on this box (582.66), it
**excludes** it:

```
total == reserved + free + used   delta = 0 bytes       <- what this driver does
total ==           free + used   delta = 96468992 bytes  <- what the docs describe
v1.used - v2.used == v2.reserved  (92 MB, exactly)
```

The trap is not the disagreement — it is what a *hard-coded* identity does about
it. A driver following the documented convention fails the `reserved + free + used`
test, the code falls back to v1, and v1's `used` **includes** the reservation, so
the panel shows a plausible number that is right by accident and for the wrong
reason. A refusal that quietly becomes a different answer is silent degradation,
which is the B1/B10 defect class one layer down.

`_reconcile_memory()` therefore **accepts either convention, detects which it got,
and normalises** so `vram_used_mb` means application VRAM (excluding the driver
reservation) on every driver. A reading satisfying neither is refused. The v1
witness check follows whichever convention was detected, so it stays sharp rather
than accepting both and proving nothing.

### 🔴 TRAP 4 — a conservation sum cannot detect a field-order error

`total == reserved + free + used` is **order-independent**. If the field order
were wrong but the size right, every value still lands in range, the three still
sum to `total`, and `total` still matches the registry — all guards pass.
Demonstrated: a misordered read displays **3459 MB** against a true **544 MB**.

The v1 call is the independent witness, precisely because it defines `used`
differently: `v1.used == v2.used + v2.reserved` (convention A) or
`v1.used == v2.used` (convention B). Those only agree if the layout is right.
`verify_gpu_telemetry.py` feeds the code a deliberately misordered 40-byte struct
and requires the reading to be **refused**, not displayed.

> Trap when *writing* that test: the misordered struct must be **standalone**.
> Subclassing `_NvmlMemoryV2` and redefining `_fields_` **appends** the new
> fields after the base class's, yielding an 80-byte struct in which the
> driver's 40-byte write lands in the base fields and the subclass's own fields
> stay zero. The first version of that test did exactly this and silently
> simulated nothing.

### 🔴 TRAP 5 — a ratio needs a denominator covering the same population

`gpu_vram_used_mb` summed only the adapters that were **measured**, while
`gpu_vram_total_mb` (summed by `hardware_probe` over the whole inventory) was the
denominator. Two different populations. With a measurable 4 GB card and an
unmeasurable 16 GB one, 1 GB in use renders as **5 %** instead of **25 %** — 5×
understated, and 5 % looks entirely plausible.

`gpu_vram_measured_total_mb` now sums the totals of exactly the adapters that
contributed a used figure, and the panel prefers it. Note the test fixture must
give the *unmeasured* adapter a real dedicated total: an unmeasured card with
`vram_total_mb = 0` contributes to neither total, so that shape **cannot**
discriminate the two denominators and the test passes for the wrong reason.

### The invariant: never report a fake `0`

**A metric that cannot be measured is `None` plus a reason, never `0`.** `None`
renders as `—` with a neutral track; a fabricated `0` renders as "idle", and an
idle reading during a two-hour transcription is the exact lie this module exists to
prevent. This is the same defect class as B1, B10 and B11 — *silent success* — in a
new place, and it is why `LoadGauge` treats `null` as a first-class state rather
than coercing it.

Two leaks found in my own first draft, both by this rule:
- An appended "extra" adapter used `reading.get("vram_total_mb") or 0`, converting
  an **unknown** VRAM total into **zero** VRAM. Now `None`, and the UI distinguishes
  "no dedicated VRAM" (integrated) from "VRAM total not measurable" (a dedicated
  card we could not read).
- The aggregate became "known" as soon as *any* adapter was measured, so on a mixed
  machine it implied all of them were. Now `gpu_adapters_measured` /
  `gpu_adapters_total` are reported, the label reads "busiest of 1/2 measured", and
  a partial-coverage note is shown **even when a number exists** — because "the one
  adapter I could measure is idle" and "the GPU is idle" are different answers.

**A telemetry failure must never fail a hardware scan**, which also feeds the
ingestion budget, the volume list and the evidence-store check. Three nested guards:
`sample_matched` degrades, `attach_gpu_telemetry` catches everything, and
`hardware_probe._gpu()` has its own fallback if the telemetry *module* itself raises.
Asserted in `verify_gpu_telemetry.py` part E.

### A failed session is not terminal

`ensure_ready` originally made `"unavailable"` permanent for the life of the
process. That contradicts the live-device premise: the driver may be absent when the
backend starts, the box may be suspended, and an eGPU gets plugged into a dock
mid-session. The panel would show a permanent em dash for a working GPU, and
**Rescan would not help** — the opposite of what Rescan is for. Success is now cached
for the process; failure expires after 30 s, and `rescan_hardware()` /
`get_hardware_spec(force=True)` bypass the backoff entirely via
`scan_hardware(telemetry_retry=True)`.

### Known limitation, stated rather than implied

The registry/sysfs inventory and the NVML device list are **two independent
enumerations joined by name** (vendor id as a Linux fallback). That is a guess, not
an identity: two identical cards, or hybrid-GPU silicon appearing twice, can bind a
reading to the wrong physical device, and the VRAM cross-check cannot catch it when
both cards have the same memory. Making it authoritative means matching PCI
location (NVML `busId` vs the registry's PCI path) and is **not done** — it needs a
Windows-side PCI enumeration. Documented at the join rather than left to read as
exact.

### Verification

```bash
PYTHONPATH=. python tests/verify_gpu_telemetry.py   # 171 assertions, ~20 s
PYTHONPATH=. python tests/verify_cpu_sampler.py     #   9 assertions, ~10 s
```

`verify_gpu_telemetry.py` (new, in `tests/`) covers the v2 struct rule and version
handshake, the 32-bit misread being *refused* (it first asserts the trap still
exists on this driver, so the guard cannot quietly become decorative), **both**
`used` conventions, the misordered-struct guard, the VRAM denominator, the
sysfs byte→MB conversion, retry semantics, partial coverage, and every
`None`-not-`0` path. `verify_cpu_sampler.py` (new) loads all cores in
**subprocesses** and requires the figure to move, because a primed sampler that
silently returned `0.0` forever would look exactly like an idle machine — correct
code, unverifiable by reading.

**Full gate, servers stopped: 305 assertions across seven scripts, 0 failures**
(39 + 37 + 15 + 17 + 17 + 9 + 171). `npm run build` clean. `verify_live_stack.py`
(26) is not in that count — it needs ollama + uvicorn + Vite up.

**Also verified in a real browser** (logged in, `/queue`, after the first-ever
render of the panel): the three gauges report `role="meter"` with correct
`aria-valuenow`/`aria-valuetext`; the integrated adapter's row shows
"shared memory, no dedicated VRAM" while the discrete one shows "4.0 GB VRAM";
the unmeasured adapter carries its reason; the NVML driver line renders; the
per-core strip draws one bar per logical thread (8 on a 4C/8T box); and the
"Show device details" disclosure expands and collapses correctly.

**What the browser pass changed.** It was worth doing, and not only for
confidence: reading the rendered DOM showed the default view was carrying the
whole device inventory expanded, which buried the three numbers the panel
exists for. The inventory is now behind one disclosure. A screenshot was not
possible in this environment (`browser.screenshot` requires a visible desktop
window), so the check was done by reading `innerText` and the meter attributes
out of the live DOM — which is stricter about values than a picture would have
been, but does **not** prove the visual layout, spacing or responsive behaviour
at any viewport width. That remains unverified.

**Test-harness traps hit while verifying** — read before extending these files:
- Utilisation and VRAM-used are **live** values. Compare with a tolerance, never for
  exact equality against a separately-timed read (observed 0% on one run, 23% the
  next). `vram_total_mb` *is* compared exactly — it is a stable per-adapter
  constant, and neither a mis-join nor a truncated struct produces 4096 by accident.
- **Ground truth must use the same NVML version as the code under test.** v1 folds
  the driver's reserved region into `used`; v2 reports it separately. Comparing the
  probe's v2 reading against a v1 ground truth showed a 92 MB discrepancy that was
  not a bug in either — just two definitions of "used".
- **Subclassing a `ctypes.Structure` appends fields; it does not reorder them.**
  See TRAP 4 above. A test that builds a misordered struct as a subclass silently
  tests nothing.
- **A fixture must be able to *discriminate* the thing it guards.** The VRAM
  denominator is only distinguishable when the unmeasured adapter has a non-zero
  total; with a `0`-total unmeasured card both denominators are equal and the
  assertion passes for the wrong reason. I also wrote a literally vacuous
  assertion (`x != 4096 or True`) while drafting this suite. Prefer a fixture that
  would *fail* if the fix were reverted.
- **Prefer outcome tests to spy tests.** An early version asserted
  `attach_gpu_telemetry` passed `force=True` down to the session — which would pass
  even if the rescan path were never wired to it, because it tested plumbing
  instead of behaviour. Force a failed session, rescan, require the reading back.
- Load generators must be `subprocess`, not `multiprocessing` (Windows spawn
  re-imports `__main__`) and not threads (the GIL caps eight Python threads at ~12%,
  so a 28% "full load" is an artefact of the generator, not the sampler).
- `x or -1` is a **bug** in a percentage range check: an idle GPU reports `0`, and
  `0 or -1` is `-1`. I wrote that bug into the test that guards the null-vs-zero
  contract — twice, and Codex found the second one. Use an explicit `is not None`.
- Simulating a failed NVML session must also set `_failed_at = time.monotonic()`.
  Failure is no longer terminal, so a failure with no timestamp is one whose backoff
  has already expired — and the next sample silently re-initialises and succeeds.
- When stubbing a method whose signature gained a keyword, update the stub. A stub
  `ensure_ready(self)` called as `ensure_ready(force=...)` raises `TypeError`,
  which looks like a product bug rather than a stale test double.

---

## 17. Per-job ingestion controls (the queue page's missing half)

The queue API has been complete since §13: `PATCH /queue/{id}/settings` (profile, CPU
ceiling, RAM floor), `POST /{id}/force-start`, `POST /{id}/stop`, `DELETE /{id}/cancel`
— and all four were already in `api/client.js`. **The Queue page used none of them.**
A job row offered exactly two controls, Retry and Delete. Every one of those
endpoints was built, exported, documented and unreachable from the UI.

`frontend/src/pages/QueuePage.jsx` now wires them, behind a `SlidersHorizontal`
button that expands a `JobSettingsPanel` inline beneath the row. Inline rather than
a popover: a popover inside a grid row is clipped by the scroll container and has to
fight the sidebar on z-index, and this way the panel cannot overlap what it edits.

| Control | Queued | Running | Backend |
|---|---|---|---|
| Ingestion profile | editable | **disabled, with the reason shown** | `ingestion_mode` |
| CPU ceiling | editable | editable, marked *live* | `cpu_throttle_percent` |
| RAM floor | editable | editable, marked *live* | `min_free_ram_mb` |
| Force-start (override) | ✓ | ✓ | `POST /{id}/force-start` |
| Stop (graceful) | — | ✓ | `POST /{id}/stop` |
| Cancel | ✓ | **not offered** | `DELETE /{id}/cancel` |
| Retry | Failed, **Stopped** | — | `POST /queue/add` |

Not built, deliberately: **queue reordering** and **pause/resume**. `queue_position`
is honoured when picking the next job but nothing can change it, and the model
comments list a `Paused` status the worker never implements. Both are real gaps, but
pause would need worker support inside the interrupt path hardened in §15, and the
operator did not ask for them.

### ✅ FIXED B16. Changing the profile on a running job reported success and did nothing

The worker resolves the profile **once**, at `job_worker.py:353`, and never re-reads
it. `PATCH` accepted `ingestion_mode` for a `Running` job, wrote the column, returned
`ok: true` with `changed: ["mode→accurate"]` — and the running job carried on under
the old profile. The B1/B10/B11 defect class, fourth occurrence, in a control path.

It could not simply be honoured, either. The profile fixes chunk size and embedding
batch size, so switching either mid-run would leave the case **half-indexed at mixed
granularity** — retrieval results would then depend on which part of the document
happened to be ingested under which profile. That is worse than refusing.

Now refused with a 400 whose message explains why and points at the two limits that
*are* live. The UI disables the control on a running job and uses the same wording
as its tooltip, so the reason is visible without provoking the error.

An **empty or wholly unrecognised PATCH body** is refused for the same reason: it used
to answer `ok: true` having changed nothing at all.

### ✅ FIXED B17. A stopped job vanished from the queue

`Stop` sets `status = "Stopped"` (`job_worker.py:459`) and reverts the evidence to
`Uploaded`. But `Stopped` was in **neither** the active bucket
(`["Queued","Running","Paused"]`) nor the history bucket
(`["Completed","Failed","Cancelled"]`) of `/queue`, `/queue/history` **or**
`/queue/list`. So a stopped job was invisible in every queue view: the operator
stopped it, watched the row leave the screen, and kept no record of how far it had got
— the same silent-disappearance class as B10, one level up.

`"Stopped"` is now in both history buckets, has its own `STATUS_CONFIG` entry
(neutral slate, `Square` icon — not an error, not a success, and the row keeps
showing the percent it reached, which is what distinguishes it from `Cancelled`), and
offers **Retry**, since a stop reverts the evidence to `Uploaded` and a row the
operator cannot act on is only half a fix.

### Three smaller lies, closed while wiring the UI

- **Cancel was offered on a running job, where the backend always 400s.** The two
  controls were near-duplicates anyway — Stop and Cancel differ mainly in the status
  label, since both revert the evidence to `Uploaded`. Cancel is now offered only
  while a job has not started; a button that is guaranteed to fail is worse than no
  button. The backend's error also used to advise *"wait for it to complete or restart
  the server"* — neither is good advice, and a restart is a destructive way to abandon
  a half-written index. It now points at Stop, which exists and works.
- **Retry silently reset the chosen profile.** `POST /queue/add` deletes any existing
  job row for the same evidence (it must, to satisfy the `UNIQUE` constraint on
  `evidence_id`) and rebuilds it from the request body. Retry sent only the evidence
  and case ids, so an operator who deliberately chose `accurate` got the machine
  default on the retry. The settings are now carried across, and `mode_warnings` are
  surfaced so a device downgrade is still visible.
- **The RAM slider guessed a maximum.** The panel originally fell back to a hardcoded
  `8192` when the budget had not loaded — reintroducing B8, the very hardcode §13
  removed. Both the slider and the profile buttons now render a muted placeholder
  until the device answer lands, which is the precedent the Evidence page already set.

**Verification:** 12 new assertions in `tests/verify_queue_api.py` (**37 → 49**), which
now guards the profile refusal, that a refused profile leaves the stored column
untouched, that CPU/RAM remain editable while running, the empty-PATCH refusal, and
that a stopped job appears in both `/queue/list` and `/queue/history` and can be
re-queued with its profile intact. (It later went to **51** when the RAM-ceiling
assertion was rewritten — see *One test bug worth recording* below.) The browser pass
then found B18 and B19, which needed a new script; the current full gate is **334
assertions across eight scripts, 0 failures**.

> Note for the next agent: fixtures that need a non-`Queued` status are written
> directly to the database rather than through the API, precisely because the worker
> only ever selects `Queued` jobs — a `Queued` fixture can be picked up and executed by
> a second process, which then loses the race for the same per-case Qdrant directory
> (§10). `ev2` / `stopped_job` are pre-bound to `None` before use so a failure in the
> section above cannot make the cleanup `NameError` and mask it.

### ✅ FIXED B18. A failed disk-image ingest stayed `Running` and announced success

**Found by a browser pass, not by reading the code — and the thread that led to it was
an honest UI string.** The settings panel reported `applied_live: false` for a job the
worker was demonstrably executing. That is *correct* (`applied_live` is only true when a
live governor exists), and it is the reason the panel was trustworthy — but it
contradicted what the page showed, so it was worth resolving. The answer was in the
backend log, and it was not what either could show:

```
[FORENSIC] PIPELINE FAILED: Mount failed: Could not open any filesystem in this raw image...
<nothing further>
```

No `[INGESTION] FAILED`, no `[WORKER] Job failed`. And in the database, job `35025411`
sat at **`Running` / 20 % / "Step 3: Walking filesystem"** with an **empty
`error_message`**, while its evidence sat at `Processing` for ever.

§14 fixed B11 — "a failed job stayed Running for ever" — by making the handlers
re-raise. The **document** pipeline was corrected. The **forensic** pipeline was not:
the outer handler in `_run_forensic_with_progress` printed the traceback, marked the
*evidence* failed, and fell off the end of the `except` block. Every consequence then
followed from that single missing `raise`:

- the `IngestionJob` row was never touched, so it stayed `Running` with no error;
- `run_ingestion_with_progress` saw a normal return, so its handler — which marks the
  job `Failed` and re-raises — never ran;
- `job_worker._process_job` saw a normal return too, skipped its failure handler, and
  **broadcast `INGESTION_COMPLETE`** for a job that had failed.

That last one is the worst of them: a success event went out over the WebSocket for a
job that recovered nothing. The failure itself was B1 working correctly — the truncated
image is B1's own test case, and the pre-flight plus the real TSK diagnostic both fired
exactly as designed (§6). What was broken was everything *after* the failure.

Verified live, not just by assertion: restarting the backend re-ran the orphaned job
under the fix and the log now carries all three lines in order —
`[FORENSIC] PIPELINE FAILED` → `[INGESTION] FAILED` → `[WORKER] Job failed` — and the
row reads `Failed` with the full TSK diagnostic in `error_message`, rendered inline in
the queue with a **Retry** button.

### ✅ FIXED B19. A stop was swallowed once per file, in the forensic walk

The §15 trap, in the one place §15's fix did not reach. The per-file handler in the walk
loop was:

```python
except Exception as e:
    print(f"[FORENSIC] File error: {e}")
    continue
```

`StopIteration` subclasses `Exception`, and `governor.check_and_throttle()` — three lines
above, inside the same loop — raises it on a user stop. So the operator's stop was
discarded **once per file** and the walk carried on across the rest of the image. This
is B13 again, in the loop that walks a 635 MB disk image.

Fixed with the same guard §15 uses in `compute_sha256` and `store_chunks`: re-raise the
sentinel *before* the generic handler.

### A third fix, in how the two were distinguished

The mount handler wrapped everything, sentinel included, as
`RuntimeError(f"Mount failed: {mount_error}")`. A stop therefore arrived one layer up as
a `RuntimeError` whose *message* happened to contain the words "stopped by user", and
every handler above classified it by `isinstance(e, StopIteration) or "stopped by user"
in str(e).lower()` — so it worked, **by substring match on an error string**. A control
flow decision made that way is invisible to `isinstance`, survives a reworded message,
and would break silently. The sentinel is now re-raised as itself, and the mount handler
writes the correct evidence state the first time rather than writing `Failed` and
letting the outer handler correct it — its own evidence update is wrapped in
`try/except: pass`, so a throw there would leave a *stopped* job's evidence marked
failed.

### Verification — `tests/verify_forensic_failure.py` (new, 15 assertions)

New script, because this is a distinct concern from "the Stop button stops" and from
"a failed index is not a success": a disk-image failure must be **terminal** and must
**never announce completion**. Three parts, all outcome assertions — it drives the real
`_process_job` on a worker thread and reads the database row and the broadcast events,
rather than checking that a function was called.

| Part | Drives | Requires |
|---|---|---|
| A | the real worker, on 4 MB of random bytes (no partition table, no filesystem) | job `Failed` with the TSK diagnostic and a `completed_at`; evidence `Failed`, never `Indexed`; `INGESTION_FAILED` broadcast **and `INGESTION_COMPLETE` not** |
| A2 | `run_ingestion_with_progress` directly | it **raises** rather than returning normally |
| B | the walk loop, one file, a governor that raises the sentinel | the `StopIteration` reaches the caller **as a `StopIteration`**; job `Stopped`, evidence back to `Uploaded` |

**A2 exists because of a trap I hit writing A.** The first version asserted that
`_process_job` raises. It does not, and it *should* not: it is the terminal handler, its
job is to mark the row and broadcast, and swallowing there is correct. Asserting through
it proves nothing about the re-raise one layer down. §16's rule — prefer outcome tests to
spy tests — has a sharper form here: **assert at the boundary you actually changed, and
not at the boundary that is supposed to absorb.**

Part B is the reason the classification fix exists. Before the mount-handler change the
assertion read `RuntimeError` and the job still came out `Stopped` — it passed, for the
wrong reason, via the substring match. The assertion is on the exception *type* precisely
so that laundering it cannot pass.

### One test bug worth recording

`verify_queue_api.py` asserts on `ram_floor_max_mb` — a figure derived from the *live*
machine. The original assertion was "the ceiling is 70–100 % of available RAM", and it
failed at **50 %** on a re-run where free memory had dropped from 2538 MB to 2047 MB.
The product was correct the whole time: `suggest_budget` rounds the ceiling **down to a
whole GB** (`avail // 1024 * 1024`), so 2047 MB → 1024 MB. A 1 GB floor, deliberately —
the ceiling is a *safety floor*, and rounding down never over-promises.

The assertion was wrong, not the code, and it was wrong in a way that looked like a
regression. **A ratio band over a device-derived number is a property of when you ran
the test, not of the design.** It now pins the formula itself
(`ram_floor_max_mb == max(1024, min(avail, total) // 1024 * 1024)`), which a
hardcoded `8192` still fails, plus the two properties that actually matter: never above
what is free, and never below 1 GB.

**Full gate, servers stopped: 334 assertions across eight scripts, 0 failures**
(39 + 15 + 51 + 17 + 15 + 17 + 9 + 171). `npm run build` clean.

---

## 18. The honesty pass — B20–B23

Four user-reported symptoms. Each had a different proximate cause, and all four are the
same defect class as B1, B10, B11 and B16–B19: **a confident, true-shaped message that
is not what happened.** In three of the four, the app blamed the investigator for
something the investigator did not control.

### ✅ FIXED B20. "Authentication failed" for a server that was not running

Not an authentication failure at all. With the backend down, Vite's dev proxy still
answers — **HTTP 500 with a zero-length body** (measured: 126 ms). `LoginPage.jsx` read
`e.response?.data?.detail || 'Authentication failed'`, and on an empty body `detail` is
`undefined`, so the fallback won. An unreachable server was reported as a wrong password.

`apiErrorMessage(err, fallback)` in `client.js` now separates the cases, and the
load-bearing rule is that **`fallback` may only speak when a server actually answered**.
No response at all gets its own message. The login call also gained an explicit 15 s
timeout: bare `axios` defaults to *none*, so a proxy that accepts the socket without
answering spins the button for ever.

> **Trap — do not "tidy" this by routing `login` through the `api` instance.** `api`'s
> response interceptor redirects to `/login` on any 401, so a wrong password during a
> login attempt becomes a reload loop. The bare `axios` is load-bearing.

22 other call sites use the same `?.detail ||` shape. They are less exposed rather than
differently wrong; `apiErrorMessage` is exported for them.

### ✅ FIXED B21. The AI answered nothing, and blamed the investigator's question

Ollama was running with **zero models installed**. `generate_response` called
`/api/generate`, received `HTTP 404 {"error":"model 'llama3.2:3b' not found"}`, and read
only `.get("response","")` — discarding the error and returning `""`. `process_response`
then saw a short string and returned:

> The AI did not generate a response. Please try rephrasing your question.

No rewording of a question installs a model. That is not merely useless advice, it is
advice **guaranteed to fail**, and it pointed the investigator at their own typing
instead of at the fix.

- `generate_response` checks the status code and surfaces Ollama's `error` field, naming
  the exact `ollama pull` command.
- `run_rag_query` gates on `ollama_diagnostic()["model_ready"]`, not on the daemon merely
  answering. **"Ollama is up" and "a model exists to answer with" are different facts** —
  `/api/tags` returns 200 with an *empty* list on a machine that never pulled a model.
- The empty-response fallback no longer blames the question, and separates "the search
  matched 2 sources but the model returned nothing" (a model fault) from "nothing in this
  case matched" (a search fault).
- `SYSTEM_PROMPT` rewritten from a report generator into a senior forensic analyst working
  the case alongside the investigator: name files, timestamps and entities, connect
  artefacts, and when the evidence is thin say what is missing and what to pull next.
- One diagnostic per query, reused in the result, instead of probing twice and risking the
  two answers disagreeing.

This closes **B5** (§6), which had been open since the first live-stack pass.

### ✅ FIXED B22. System health reported fabricated successes

`SystemHealthPage.jsx` held two cards that were **string literals, not measurements**:
`Backend API / "Running" / status="ok"` and `Vector Store / "Qdrant" / status="ok"`. The
second also cited `data/qdrant_store`, **a directory that does not exist** — per-case
Qdrant is `data/cases/<case_id>/qdrant/` (§2, §9).

`/api/status` was worse: `database` was `os.path.exists("./data/forensic.db")` — **file
existence presented as connectivity**, so a corrupt or locked database reported
"connected".

New `backend/modules/service_health.py` runs six isolated probes, each returning `state`
(`ok` / `error` / `unavailable` — measured-and-broken vs could-not-measure) plus a reason:

| service | now actually measures |
|---|---|
| `database` | a real query against the `cases` table, with `latency_ms` |
| `ollama` | daemon, configured model, `model_ready`, `installed_models` |
| `vector_store` | real case-collection count, total size, writability |
| `worker` | the worker thread's real liveness |
| `cases_dir` | existence **and** a real writability check |
| `embeddings` | `importlib.util.find_spec` for the lazy optional deps — does not import torch |

One probe raising leaves the other five measured. No probe opens a `QdrantClient` —
embedded mode takes an exclusive lock per directory and would fight the running app
(§15, B14).

The page renders an unmeasured state as a **grey dot and an em dash**, never a colour. A
measured `0` is still shown as `0`, because *zero models installed* is the single most
important fact on that page. §16's rule cuts both ways: a fabricated `0` is a lie, and so
is turning a real `0` into an em dash.

> **Cost:** `/api/status` takes ~2.1 s, nearly all of it `ollama_diagnostic()`'s
> `/api/tags`. That is inside the frontend's 15 s poll and is now reported as
> `latency_ms` rather than being invisible.
> **Known gap:** the worker probe **cannot detect a wedged worker**. `job_worker` exposes
> only a thread and a boolean, with no heartbeat, so a loop stuck inside `_process_job`
> still reads `ok`. Fixing it needs a heartbeat in `job_worker.py`.

### ✅ FIXED B23. Prompts vanished when the investigator changed tab

Two different losses, and only the obvious one is a `useState` problem.

1. **An unsent draft** lived in component state. Changing route unmounts the page, so it
   went with it.
2. **A submitted question that was still generating** vanished for a subtler reason:
   `backend/routers/queries.py` writes its `QueryLog` **after** `run_rag_query` returns.
   A question in flight therefore **does not exist in the database yet**, so the refetch on
   return could not find a row that had not been created.

Fixed with a per-case `localStorage` draft, plus a `cfi_pending_questions` list of
in-flight questions that is reconciled against every fetch — a pending entry stops being
pending the moment the server has it — and re-rendered as a waiting bubble. A 3 s poll
runs **only while something is in flight**, and it is *quiet*, because a background poll
that blanks the transcript reads as the page breaking.

Pending entries expire after 10 minutes; past that the request is presumed lost, so a dead
backend cannot cause an infinite poll.

**Also added:** terminal-style **↑/↓ prompt recall** in the textarea, sourced from the
questions already asked *in that case* rather than from a second private store, so the
recall list and the visible transcript cannot disagree. Arrowing past the newest entry
restores whatever was being typed. The arrows are taken **only at the edges of the text**,
because in a textarea `ArrowUp` is also the ordinary way to move between lines and
hijacking it unconditionally would break Shift+Enter multi-line editing.

### ✅ FIXED B24. The queue had no ETA, and its elapsed time was a fabricated `0`

Two separate lies in the same row, and the second one was hiding the first.

`models.IngestionJob.elapsed_seconds` was **read by `queue_router._row()` and written
nowhere in the codebase.** Every running job reported `0`. There was no ETA field at
all — the only time figure on a running job was the queue-time `estimated_seconds`,
which is a fixed prior computed before the job starts and never revised. So the
question "how long has this been running, and how much longer?" was answered by a
number that was wrong and a number that did not exist.

`elapsed_seconds` being a permanent `0` is the same defect as B16's
`applied_live: false`: **a fabricated value in a field shaped exactly like a real one.**
A job running for ten minutes and a job that just started are indistinguishable on
screen.

New `backend/modules/eta.py` — `EtaTracker`, deliberately pure (no database, no network,
no backend imports) so it is unit-testable, with the clock injectable for exactly that
reason. Three design points, each of which is a trap someone will try to simplify away:

**1. Never `elapsed / percent * 100`.** `progress_percent` is five weighted bands
(hash, extraction, chunking, embedding, entity graph) whose cost per point is wildly
uneven. A 635 MB disk image spends most of its wall clock in step 1; a 2 MB text file
spends most of its in step 3. Linear extrapolation therefore extrapolates the wrong
quantity, and is wrong by the largest margin exactly where the operator most needs an
answer. So the prior is **blended** with observed throughput, not replaced by it:
below `OBS_MIN_PERCENT` (10) the observation is not trusted at all and the answer is the
prior, labelled as such; above it the observation earns weight `min(0.75, pct/100)`, so
one mis-measured step cannot take the number over. The prior knows the *relative* cost
of each stage and is already profile- and throttle-aware; the observation knows the
*actual* rate on this machine. Neither alone is trustworthy.

**2. Governor pauses are removed from the work rate and added back as a duty cycle.**
A job throttled to a 40 % CPU ceiling, or waiting on its RAM floor, spends real wall
clock in `time.sleep()` during which no work happens. Measuring throughput over wall
clock reports a machine several times slower than it is, and the ETA creeps upwards for
ever. So `work = elapsed − throttle_seconds` drives the rate, and the pause is
re-added as `1 + duty/(1−duty)` on the *remaining* work — **on the observed term only**,
because the prior already carries the requested throttle factor and applying it twice
double-counts. The duty cycle is capped at `MAX_THROTTLE_DUTY` (0.8): uncapped, a job
spending 90 % of its life waiting for its RAM floor yields a 10× ETA — arithmetically
defensible, useless to read.

**3. Smoothing is asymmetric, and that is the whole trick.** The rate is already an
EMA, so smoothing the ETA symmetrically on top of it is double-smoothing and it lags in
*both* directions. Measured on a 145 s job with a 600 s prior: a symmetric ETA EMA
quoted **168 s remaining at 95 %, when 5 s remained.** The lag, not the prior, was the
dominant error. So a falling countdown (work being consumed) is followed at α=0.8 and
only a *rise* is damped (α=0.35), where the real risk is a spike. Both directions are
also bounded — 1.5×/frame up, 0.35×/frame down — because **a collapse is as much a lie
as a spike**: promising a job is nearly done when it is not is the identical defect.
> If a symmetric smoother is ever proposed as "simpler", that measurement is the
> counter-argument.

**Never a fake zero** (§16 again, the fourth instance in this file). `eta_seconds` is
`None` when there is neither a prior nor a measurement, and `0` **only** when
`percent >= 100`, where it is true; below 100 the value is floored at 1 s so a 0.2 s
remainder cannot round down into a false "done". A prior of `0` is treated as *absent*,
not as "zero seconds remaining". A drop from 100 % is a restart, not a band recompute:
the observation is dropped and the answer is `None` with a reason, never `0`.

Wiring: one `EtaTracker` per job, created when the job is marked `Running` and seeded
from `estimated_seconds` so the *first* frame already shows a countdown. One reused
session for the whole job, committed per frame — a session per tick would open and
close a SQLite connection hundreds of times on a large ingest. The tick is written to be
**incapable of raising**: every failure is logged and reported as "unknown", because a
progress path that raises is the B11 shape (an exception out of the progress path left
the job `Running` for ever). `_broadcast_progress` gained the two fields as *keyword*
arguments — the first five parameters are the contract `ingestion.py` calls and are
positional by design, since an arity mismatch there is swallowed behind a bare `except`
inside the pipeline and silently kills every intermediate update (§13 B7).

> **Trap:** the elapsed/eta tick runs inside the progress callback, so it sits directly
> on the B7 seam. If you ever see the live queue jump from 0 % to 100 % with no
> intermediate frames, check the callback arity before anything else.

`eta_seconds` is a **nullable** column added by `migrate_eta.py` (registry entry 19) with
**no backfill**, for the same reason `ingestion_mode` is: SQLite cannot `ALTER TABLE ADD
COLUMN` with a non-constant default, and every existing row's correct value is NULL.
Migration is idempotent — the second run prints the same `duplicate column name` note
every other migration in this repo prints, which is the established style, not a failure.

### ✅ FIXED B25. The AI looked permanently offline while answering correctly

**Reported as:** the assistant "is not functioning properly", the only message is that it
is "offline", and rephrasing the question changes nothing. The backend was in fact
answering correctly the whole time — verified live: `ollama_available: true`,
`model_used: llama3.2:3b`, a grounded answer naming operators and hosts.

Three separate frontend defects, all in the *display* of status, none in the AI:

1. **`App.jsx` fabricated a failure in its `catch`.** `getStatus()` throwing produced
   `setSystemStatus({ database: 'error', ollama: 'offline' })` — the exact fabrication
   B22 removed from `SystemHealthPage.jsx`, one layer up, in the component that owns the
   Sidebar dot. It also polled only every 30 s, so a backend that was merely still
   starting read as a permanently dead AI. Now the catch sets `null` (unknown) and a fast
   4 s retry runs until a real reading lands, then settles to 30 s.
2. **`Sidebar.jsx` treated "not yet known" as failure.** `ollamaOk = status?.ollama ===
   'running'` is `false` while `status` is `null` — and `status` is `null` for the entire
   ~2 s that `/api/status` is in flight, because that endpoint asks Ollama for its model
   list. So the red "Ollama offline" dot was drawn *while the request was still running*,
   and a slow or hung `/api/tags` made it look permanent. There are now three states —
   ok / measured-and-broken / **not measured yet** — and the third is a neutral grey dot
   with a neutral tooltip, never a failure colour.
3. **`InvestigatePage.jsx` still rendered the B21 text.** `ResponseText` — live, at line
   1358 — said *"The AI did not return a response for this query. Try rephrasing your
   question."* The backend had been fixed to name the real fault; this fallback had not
   been. It now says to check the System Health page and names `ollama pull`.

> **The general rule, fourth time it has bitten:** a status that has not been measured yet
> is not a failure. `null` must render as "unknown", never as red. The same fix had to be
> applied in `SystemHealthPage.jsx` (B22), in `Sidebar.jsx` and `App.jsx` (here), and in
> `eta.py` (B24) — four places, one rule.

**Also fixed while in there:** `setup_windows.bat` and `setup.sh` both installed with
`pip install --no-index --find-links=vendor\python`, but `vendor/` is **gitignored**, so a
fresh clone has no wheels and the one-click setup failed outright. Both now detect the
kit and fall back to a normal online install. `setup_windows.bat` also used `yarn install`
while `start_windows.bat` explicitly warns that yarn is broken on Windows, and it never ran
migrations at all — so an existing `forensic.db` kept its old schema and the backend failed
with `no such column: ingestion_jobs.eta_seconds` (`create_all` creates tables but never
adds columns to existing ones). Both scripts now use npm and both run `migrate_all.py`.
`setup.sh` also created `data/qdrant_store`, a directory nothing in the codebase reads or
writes — the same phantom path the health page used to cite in B22.




---

## 19. The chatbot answered "I can't assist with that." — the prompt was 20× the context window

**Reported as:** the investigator asked the assistant a plain question about the case and
got a refusal. Re-asking changed nothing. Reported as "the chatbot has errors".

**It was not a chatbot error.** Retrieval, Ollama, the model and auth were all healthy and
all answered `200`. The prompt was being silently thrown away.

### What was actually happening

`run_rag_query` retrieved `top_k=7` chunks and concatenated them in full. Ingestion chunks
are sized in **characters** — 30,000 for the `fastest` profile, 20,000 for `normal` — so the
prompt was **212,815 characters**. Ollama reports how much of it was consumed:

```
level=WARN source=runner.go:153 msg="truncating input prompt" limit=4096 prompt=80311 keep=5 new=4096
```

`prompt=80311` is a **token** count (calibrated: 20,000 chars → 4,025 tok, 40,000 → 8,025,
80,000 → 16,025, i.e. ~5 chars/token on synthetic text). The window is **4,096**. So the
prompt was **~20× the entire context window**.

`keep=5` is the part that matters. Ollama kept the **first 5 tokens** and the **last 4,091**.
The first 5 are the start of `"Evidence Excerpts:"`. The last 4,091 are the tail of the
entity graph and the closing question. **Every one of the seven evidence excerpts was
discarded.** The model was asked to be specific about a suspect's email and phone number
with no evidence in front of it, so it declined to invent one. It was, in effect, correct.

The sources footer was then appended underneath, so the exchange read as answered.

Proven directly, same evidence, same model, same question:

| | `prompt_eval_count` | Result |
|---|---|---|
| **Before** — assembled whole | **4096 / 4096** (saturated) | `I can't assist with that.` |
| **After** — budgeted to fit | 2,894 / 4,096 | Named Yuki Tanaka's address, the `darknode.io` campaign date, the `$6,177,459` transfer |

### ✅ FIXED B26. Nothing measured the prompt against the window

**Four changes, in `ollama_client.py` and `rag_engine.py`.**

**1. The runtime window, not the trained one.** Two different numbers exist and conflating
them is the whole bug:

| source | value | what it is |
|---|---|---|
| `/api/show` → `llama.context_length` | 131072 | the length the model was **trained** at |
| `/api/ps` → `context_length` | **4096** | the length Ollama is **serving** it with |

Only the second bounds a prompt. `effective_context_tokens()` reads `/api/ps`, caches 30 s,
and falls back to a new `ollama_num_ctx` setting. Budgeting against `/api/show` over-estimates
the real window by **32×**.

**2. The prompt is built to a budget, spent per excerpt.** `build_prompt()` divides the
allowance across all seven chunks rather than handing it to the first or trimming the
assembled string from the end — `top_k` exists so different chunks cover different parts of
the question, and either shortcut answers a narrower question than retrieval just answered.
Every trimmed excerpt carries a visible `[… N characters …]` marker, because a silent slice
leaves the model unable to distinguish omitted evidence from absent evidence.

Three classes of text, treated differently:

- **protected** — the question, the conversation memory, the closing instruction. Measured
  first, never trimmed.
- **yields** — the entity graph, capped at ¼ of the remainder. It is a ranked list, so a
  truncated one is still a useful one.
- **shared** — the excerpts, evenly.

> **Trap, hit while writing this.** The first draft clamped the *assembled* prompt. But
> `_elide()` keeps the **front**, and the question sits at the **back** — so the clamp
> answered a different question than the one asked, which is the same failure as overflowing
> it, only quieter. `verify_prompt_budget.py` G8/G9 guard it.

**3. The estimate is checked against ground truth.** Ollama 0.17 has **no `/api/tokenize`**
(404) and `/api/embed` caps at 4,095, so an exact count is not obtainable for a long text
without generating. `CHARS_PER_TOKEN = 2.4` is therefore a *deliberately biased* estimate:

| text | chars/token |
|---|---|
| `SYSTEM_PROMPT` prose | 4.52 |
| dense log/dump evidence | 2.65 |
| assembled 7-excerpt prompt | 2.53 |

The estimate is `chars / C`, so it over-counts tokens only when `C` is **below** the real
ratio. **2.4 is below the densest measurement, on purpose:** over-estimating wastes a little
window, under-estimating overflows *silently*. Then `prompt_eval_count` — Ollama's own count,
returned with every response — is checked against the window, and if it came back saturated
the evidence allowance is halved and the call is retried once. A wrong ratio degrades into
one extra fast retry, never into a discarded prompt.

**4. A refusal is a missing answer, not a wrong one.** `is_refusal()` matches the opening of
the reply and `process_response` replaces it with the real diagnosis instead of filing it as
a response. The old "try rephrasing your question" advice stays gone — no rewording fixes a
context window. The replacement names the capacity limit and tells the investigator to narrow
to one entity or one artefact. It matches the **head** only: a model that declines and then
waffles is still declining, while a legitimate answer that happens to contain the phrase later
is not (guarded by E4).

The API now returns `prompt_stats` and `refused`, and the transcript renders the caveat as a
distinct block — a limit on the evidence behind a finding must not read in the same voice as
the finding. `EVIDENCE_NOTE_MARKER` in `rag_engine.py` and `EVIDENCE_CAVEAT_MARKER` in
`InvestigatePage.jsx` are the same string and **must be changed together**: the backend writes
it, the frontend splits on it.

### Verification — `tests/verify_prompt_budget.py` (84 assertions)

A–H: runtime window is not the trained length · the 212k prompt no longer fits · the graph
survives · all seven excerpts are represented and each marked as trimmed · shares are even ·
elision is announced and inside its reserved allowance · the production refusal is caught and
alternate phrasings too, while two realistic answers are **not** misread as refusals ·
`CHARS_PER_TOKEN` is on the safe side of the densest measurement · zero-chunk, history and
oversized-graph paths keep the question verbatim.

I: the transport clamp for the four call sites that assemble a prompt by hand. **J, K added in
§20**: the window is on the wire and the diagnostic reports it. Section J is the only place
the transport contract is observable, and **K is the one section that touches the network** —
`ollama_diagnostic()` reads `/api/tags`, `/api/show` and `/api/ps` for real, because the claim
under test is what an *operator* can see, and asserting that against a stub would only prove
the stub was called.

**Full gate, servers stopped: see §20 for the current total.** `npm run build` clean.
`verify_gpu_telemetry` reports 14 failures on an Apple M1 — every one is
`NVML library not found`, an NVIDIA suite on a machine with no NVIDIA driver. Pre-existing and
unrelated; its null-vs-zero assertions pass. **Do not port that claim to a box that has an
NVIDIA card** — this repository's dev machine is a Windows host with a GTX 1050 Ti, where the
NVML path is live and those 14 assertions pass.

### Still open — the real quality ceiling

The chunks are **30,000 characters ≈ 10,000 tokens**, roughly three times the entire usable
prompt budget. Retrieval is finding the right passages and the budgeter is now showing a
usable slice of each, but only ~370 characters of each 30,000 reach the model, so answers
are visibly hedged and can miss a fact that sits just past the cut.

Smaller chunks would fix that, and §13 already establishes that changing chunk size **does not**
change dimensionality (384-dim, `VECTOR_SIZE`) so existing collections stay valid. It does
mean a **re-index** to benefit, which is a decision, not a bug fix, and is deliberately not
made here. `ingestion_modes.py` is the single source of truth for chunk size, so the change is
one table edit plus a re-ingest.

**Partly resolved in §20** — raising the served window recovered 5.4× of that headroom without
the re-index. The chunk-size half remains open.

---

## 20. The context window was a reporting-only knob (B27)

§19 fixed the *symptom* — a 212,000-character prompt overflowing a 4,096-token model. It did
not fix the **window**, which is what made the overflow inevitable. B27 is the same defect shape
as B8 (a hardcoded 8 GB RAM floor that consulted nothing about the machine), one layer up and
in the direction of a capability rather than a resource.

**Reported as:** the chatbot is "not working properly". It was not broken. It was correct, and
correctly unable to answer.

### ✅ FIXED B27. `ollama_num_ctx` never reached Ollama

```python
"options": {"temperature": 0.1, "num_predict": settings.ollama_num_predict}
```

No `num_ctx`. So the window was **whatever Ollama's own default happened to be** — 4,096 for
`llama3.2:3b`, a model **trained for 131,072**. Measured on this box:

| request | `prompt_eval_count` |
|---|---|
| as the app sent it | **4,096** — clamped |
| with `num_ctx: 16384` | **10,044** — window genuinely raised |

`ollama_num_ctx: int = 4096` in `dependencies.py` fed the **budget arithmetic only**. It was
never a control. That is the dangerous part, and the reason this was not fixed by editing
`.env`:

> **Setting `OLLAMA_NUM_CTX=32768` — the obvious remedy, and the natural first thing anyone
> would try — would have made things *silently worse*.** The app would budget a 32k prompt,
> Ollama would keep serving 4,096, and the evidence would be discarded exactly as in B26 — but
> now the saturation check compared `prompt_eval_count` against a limit **the app had invented
> rather than one Ollama had agreed to**, so the app would report no overflow. A knob that
> only feeds the arithmetic is a lie dressed as a setting.

**Fixed by making it a real control**, in four parts:

- `model_context_limit()` — the model's trained capability, read from `/api/show`. Both
  shapes are read (`llama.context_length` and `model_info.<arch>.context_length`) because
  builds differ, and it returns **`None` when unreadable, never 0** (§16: a 0 limit would
  clamp every request to nothing while looking like a working number).
- `requested_context_tokens()` — `min(configured, capability)`, floored at 1,024. This is what
  goes **on the wire** as `options.num_ctx`.
- `effective_context_tokens()` — `/api/ps` still wins when it reports a real value; otherwise
  the requested value, which is now the honest answer *because* the request is what governs.
- `prompt_budget_tokens()` — unchanged, but now sized against a window Ollama has agreed to.
  **2,816 → 15,104 tokens: 5.4× more evidence per answer, no re-index.**

### 🔴 TRAP 6 — `/api/ps` does not report the window on this build, so the "live" path is dead

```
/api/ps details keys: ['families','family','format','parameter_size',
                       'parent_model','quantization_level']
```

No `context_length`. §19's "prefers the live value" therefore **never fires here** and fell
back to the hardcoded 4,096 on every query. The capability *is* readable — from `/api/show`,
where it correctly returns **131,072**. So the measurement the code preferred was on the
endpoint that does not carry it, and the endpoint that does carry it was not consulted.

**Generalisable:** when two sources disagree about which one is authoritative, check that the
authoritative one actually *has the field* before trusting it over the other. A probe that
always returns `None` and a silent fallback look identical from the call site.

### 🔴 TRAP 7 — a second, independent truncation guard, because the first one had a blind spot

The existing check was `prompt_eval_count >= limit - 2` — *did we fill the window we asked
for*. With `num_ctx` now sent, that is correct, since the served window equals the request.
But had it stayed as the **only** guard, a window smaller than we believe we have would pass
silently: `eval_count` hits the smaller real ceiling, which sits comfortably below `limit`, and
saturation stays `False`. That is precisely B26's mechanism, so a second guard was added:

> **Saturation asks "did we fill the window we asked for". Truncation asks "did Ollama read
> most of what we sent".** They fail differently, which is the only reason both are needed.

```python
lost_most = eval_count < estimated_tokens * _TRUNCATION_LOSS_RATIO   # 0.5
```

**The ratio is deliberately insensitive, and the bias in §19 is why.** `CHARS_PER_TOKEN` is
set *below* the densest measured ratio, so `estimated` over-states the true count on prose by
up to ~1.9×. `eval_count < estimated` is therefore **normal and means nothing** — a naive
`<` would flag every prose query as truncated. Only losing more than half the prompt is
unambiguous, and half is the case that matters: B26 lost 95% and it arrived looking successful.

> If this is ever "simplified" to `eval_count < estimated`, it will fire on essentially every
> query, and the obvious response will be to delete it.

### A test bug worth recording

`verify_prompt_budget.py` H1 asserted `estimated_tokens < 4096`. That passed for the wrong
reason the moment the window was corrected: the *property* (the prompt fits the window it will
be served with) was still true, but the **literal** was now a statement about one machine on
one day. Rewritten to assert `<= prompt_budget_tokens()` and given a second assertion that the
window is genuinely above 4,096 — because a test that only checks the prompt fits will happily
pass against a fictional window.

Same lesson as §17's `ram_floor_max_mb` assertion: **a constant that encodes a device fact will
either rot or pass for the wrong reason.** Assert the relationship, never the number.

New section **J** (7 assertions) guards the transport contract — `num_ctx` on the wire, the
wire value equals the clamped value, budget and request derived from the same number, and all
three truncation cases. These are the assertions that fail on the old code; asserting the
arithmetic alone would have passed throughout. §15's lesson: *Stop was correctly wired end to
end and still useless* — the wire is the only place this is observable.

**76 assertions, 0 failures** in `verify_prompt_budget.py` (up from 66).

### Also found while diagnosing: the corpus was empty

Worth recording because it cost more time than the bug did. The case being questioned held
three synthetic benchmark files, a README and a **truncated** disk image (§6 B1) — no real
evidence at all. The chatbot was asked for a suspect's email address that existed nowhere on
disk and it correctly said so, then recommended examining the email logs.

> **A refusal is only a bug when the evidence is there.** Check what is actually indexed before
> concluding the model is at fault. `seed_demo.py` creates cases and entity rows but **no
> evidence files**, so a fresh install has nothing for retrieval to find and every demo case
> looks identical: empty.

### Verification

```bash
PYTHONPATH=. python tests/verify_prompt_budget.py   # 84 assertions, ~30 s
```

Confirmed live over the API, against a case with **299 chunks / 978 entities** indexed (6.3 MB
of generated evidence — the corpus was empty before, which is the other half of this bug):

| | before | after |
|---|---|---|
| served window | 4,096 (Ollama's own default) | **16,384** (requested, honoured) |
| prompt budget | 2,816 | **15,104** |
| `prompt_eval_count` | 4,096 / 4,096 **saturated** | **13,322 / 16,384** |

The same question — name the suspect behind the darknode.io campaign, their email and phone,
who they spoke to, what moved — answered *"the evidence does not contain the suspect's email
address or phone number"* before, and names the suspect, five contacts with phone numbers,
seven transfers and a next step after. 165 s, since a 13k-token prefill on CPU is not free.

> **A caution about oracles.** The first proof script had a column "did the model see the
> fact?". It answered `no`, then `YES`, for the *same* clamped request across two runs — a 32
> token completion is sampling noise, not a measurement. A column that flips on a rerun is not
> evidence, and the fix would have been justified with it. Only `prompt_eval_count` carries
> weight here, which is the same reason TRAP 7's ratio is coarse.

---

## 21. A health probe reported 0 indexes for cases that were indexed (B28)

Found by running the §20 gate, and by a bug in the gate itself.

### 🔴 TRAP 8 — the gate reported 0 failures for a suite with 15 failures

`verify_service_health.py` prints `PASSED: 177    FAILED: 15`. The gate script matched
`'\d+\s+(passed|assertions)'` first, fell through to `Select-Object -Last 1` on a loose
`PASSED|FAILED` pattern, and therefore captured a **`FAILED: <description>` line** — the list of
failures, not the summary. `[int]` on an empty match is `0`, so the suite printed:

```
ok    verify_service_health.py                  0 passed    0 failed
```

and the run came out **630 passed, 0 failed** while hiding 15 failures.

> **A gate that reads 0 for a script which did not pass is worse than no gate: it converts a red
> suite green.** Same defect class as everything else in this file, in the one tool whose entire
> job is to not do that. The parser now matches both formats explicitly, and a script whose
> counts are unreadable — or that exits non-zero having reported zero failures — **fails the
> gate**. The `??` and `ERR` states are not cosmetic; they exist so a future format change is
> loud.

I had already written "0 failures" into a status report before noticing. The lesson is not
"check the numbers", it is that a summariser is a program and has to be tested like one.

### ✅ FIXED B28. The probe counted indexes in the wrong tree

`probe_vector_store(cases_dir)` listed **the directory it was handed**, then asked
`case_qdrant_path()` where each index was. But that function takes only a `case_id` and resolves
against **global settings**, because that is where the writer looks:

```python
def case_qdrant_path(case_id): return os.path.join(resolve_qdrant_dir(), case_id, "qdrant")
```

and `resolve_qdrant_dir()` relocates the whole store when the cases directory is on a slow
disk. On this box (D: 7200 RPM) it returns `C:\Users\Anon\AppData\Local\IDFA\qdrant` while the
probe was walking `D:\...\data\cases`. **Two different trees, so zero matches**, and the
detail string reported a measured zero:

> `0 of 2 case directories hold a Qdrant index; 0.0 MB total`

The consequence is not cosmetic — it is §15's failure mode rebuilt, from the filesystem side.
Every **reader** resolves through `case_qdrant_path()`, and `get_client()` *creates* whatever
directory it is handed:

```python
os.makedirs(key, exist_ok=True)
client = QdrantClient(path=key)
```

So a case indexed only in-cases does not merely look untidy — on the next query it gets a
**brand new, empty** collection and returns nothing at all. Fully indexed, yet searchable as
though it were empty, and an investigator concludes the evidence was clean. That is why the
probe's reason says those cases *will return no results* rather than calling the layout
untidy, and why the state is `error` rather than a warning.

### Verified live on this box, not assumed

| | |
|---|---|
| relocation | **active** — `[QDRANT] cases dir is on a rotating disk (D:); putting the vector index on the faster C: disk` |
| `migrate_qdrant_layout()` | runs at **startup** (`main.py:31`, import time) |
| `data\cases` | 63 case dirs |
| `C:\Users\Anon\AppData\Local\IDFA\qdrant` | 38 case dirs — a **split**, so the un-migrated state is live here, not hypothetical |

**An index has two legitimate homes, and both are now checked:**

| | location | when |
|---|---|---|
| in-cases | `<cases_dir>/<case_id>/qdrant` | all-SSD box, or pre-migration |
| canonical | `resolve_qdrant_dir()/<case_id>/qdrant` | slow cases disk, post-migration |

A case counts if **either** exists. Three states are named rather than summed into one number:

- **un-migrated** — indexed beside its case. Measured, disclosed, and *degraded*, because the
  index is real and the layout disagrees with the writer.
- **duplicated** — indexed in **both**. `migrate_qdrant_layout()` explicitly refuses to
  overwrite an existing destination, so this state can genuinely occur, and it is reported
  rather than collapsed. The size counts the canonical copy only; summing two copies of one
  index would double it.
- **resolver fault** — if `case_qdrant_path()` raises, the in-cases location is still
  checked, so a resolver fault cannot degrade into "no index here".

### 🔴 TRAP 9 — "not applicable" must agree with the sentence that states it

My first attempt reported the split as `None` for any directory that is not the configured
root — correct reasoning, and it **still failed 4 assertions**, because the two halves read
different variables:

```python
out["unmigrated_collections"] = None   # honest: this tree is not ours
...
if unmigrated:                          # the raw local: 1
    reasons.append("1 case index/indices still sit inside ...")
```

So one response said `unmigrated_collections: None` and `"1 case index/indices still sit"`
in the same breath, for the same tree. **A field and the sentence beside it must come from one
decision, or the sentence is the field's worst version.** Fixed by clearing the locals in the
same branch, and pinned by an assertion that reads both.

> Generalisable to every `reason` string in `service_health.py`: a reason computed from
> pre-normalisation state will eventually disagree with the normalised value it describes.

Also: for a non-configured directory the split is **`None`, not `0`**. Zero would be a claim
that this tree is fully migrated, and for a tree that is not the real one the claim means
nothing (§16, fifth occurrence in this file).

### The test bug, and the discriminating-fixture rule

New section **E2**, twelve assertions. It has to pin **three** things — the directory probed,
the configured root, and the resolver the writer consults — because patching only the first
makes the migration split structurally unobservable, which is exactly how the first fix attempt
passed its own tests while being wrong.

**Verified discriminating, not merely accompanying:** with the probe reverted to its pre-fix
logic the suite fails **22** assertions; restored, it passes **209**. A new guard that passes
on the old code proves nothing.

> A fixture must be able to *fail* if the fix is reverted. A test written alongside the fix,
> never run against the broken version, is a description of the fix rather than a check on it.

`verify_service_health.py` 177 → **209**.

A second, unrelated test bug surfaced here and is worth keeping in mind: the suite's
"the real database was never opened" check compared an `mtime_ns` fingerprint taken at
**import time** against one taken at the end. Anything that touched `forensic.db` in between
— a running backend, an editor — changed the stamp and the suite reported *its own* side
effect. It was measuring the wrong interval. The fingerprint is now taken around the run,
inside `main()`, and `mtime` is the load-bearing half: a write of identical content updates
it, so a size-only comparison would let the suite write to the real database and pass.

### Verification

```bash
PYTHONPATH=. python tests/verify_service_health.py   # 209 assertions, ~40 s
```

**Full gate, servers stopped: 839 assertions across twelve scripts, 0 failures**
(9 + 59 + 153 + 15 + 171 + 39 + 17 + 84 + 51 + 209 + 17 + 15).

Run the gate with **servers stopped** (§10), and read the totals rather than the exit code
alone — a summary that cannot be parsed is a failed gate, not an absent one.

---

## 22. Standing advice for whoever picks this up next

Six of the twenty-eight bugs in this file were **caught by the verification rather than found
by reading**, and the pattern is consistent enough to be worth stating on its own:

| found by | bug |
|---|---|
| running the live stack | B10, B11 |
| reading the rendered DOM | B18 |
| running the §20 gate | B28 |
| asking "why doesn't Stop work?" instead of re-reading the stop path | B13 |
| asking what is *actually* indexed before blaming the model | the empty corpus (§19/§20) |

The common cause is not bad code. It is **verification that reports success without
measuring anything**: `except: return 0`, a field read but never written, a knob that only fed
arithmetic, a probe that asked a function about a different directory, a gate whose parser read
0. Every one of those produces a true-shaped value carrying none of the information, which is
why they survive review — the code reads correctly.

Three habits that would have caught all of them:

1. **Assert the relationship, never a number that encodes a device fact.** `ram_floor_max_mb`
   (§17) and `estimated_tokens < 4096` (§20) both passed for the wrong reason. A literal is a
   statement about one machine on one day.
2. **Make every new guard able to fail when the fix is reverted.** §21's section E2 was
   re-run against the pre-fix probe deliberately: 22 failures. A test written alongside a fix
   and never run against the broken version is a description of the fix.
3. **Never report a zero you did not measure.** `None` + a reason when unmeasurable; `0` only
   when measured, because *zero models installed* is itself the most important fact on the
   health page. Nine occurrences in this file.

**And one that is not about code at all:** the chatbot "not working" for most of a session
was, in the end, an empty corpus plus a context window nobody was sending. Neither was in the
diff. When something is reported as not working, check what is actually in front of the system
before changing the system.


---

## 23. The Archive button worked perfectly and did nothing (B29) — and a guard that passed for the wrong reason

**Reported as:** "archive in evidence library is not working".

### The database answered it before the code did

```
Indexed   4
Failed    1
Archived  1     ← 468c78f3  test_evidence_6mb.txt  case=b42cc8ce
```

Exactly one archived row, and it was the item that had just been archived. So
the archive had **succeeded** — the write, the commit and the audit entry all
happened. Nothing failed. The complaint was not that it failed.

### Why it looked like nothing happened

`GET /api/cases/{case_id}/evidence` filtered on `case_id` and nothing else.
Archiving set `status='Archived'`, and the row was still returned and still
rendered, badge and all. The confirm dialog had promised *"It will be removed
from active investigations."* It was not removed from anything. It was
**relabelled** — the toast said "Evidence archived" and the row stayed put.

**Sixth occurrence of the §18 class, and the first where the write was right
and the *read* lied.** §17 was the mirror image: a stopped job that left the
queue entirely, so the operator lost the record of how far it had got.

### Four faults, not one

1. **The list had no status filter.** `include_archived` now excludes archived
   by default, which is what makes the operation mean something.
2. **The role gate was inverted.** Archiving required **Admin**, while
   *uploading* evidence requires **Investigator** and so does archiving the
   whole *case*. The broader action was gated **lower** than the narrower one,
   so the gate could only have been a copy-paste — and a non-admin got a bare
   `toast.error('Failed to archive')`, which is B20's shape: a permission
   refusal reported as a failed click.
3. **The Qdrant cleanup was `except Exception: print(...)` and marked
   non-fatal.** The dialog promises *"AI queries will no longer return its
   content."* If that delete fails the chunks are still in the index, queries
   **do** still return them, and the response says "archived successfully" —
   so an investigator who archives a document to keep it out of an analysis
   finds it in the answer, and has been misled about their own evidence. It is
   now fatal to the archive, and the message says why. Nothing is lost by
   refusing: the status change has not run, the file is untouched, and the item
   is still active and intact.
4. **There was no way back, and no way to even see what was hidden.** Restore
   is a new `POST .../restore`, and the page gets a "Show archived (N)"
   disclosure. An operation that cannot be undone should not be one click away
   from a forensic record.

### A trap in writing the inverse: restore must not claim the index came back

Archiving **deletes the vectors**, so a restore that set `status='Indexed'`
would produce §15/B14 exactly: a row that looks searchable and returns
nothing. Restore sets **`Uploaded`** — literally "on disk, not yet ingested" —
which is the state the Queue button already understands, so re-indexing is the
ordinary path rather than a special case. The response message says so, and the
UI renders that wording rather than a bare "restored".

### 🔴 The consequence of making archive actually delete something

`chunk_count` is read by **four** consumers that do not check status: the case
export, the PDF report, `report_generator`, and the queue's evidence row. Once
archiving really does delete vectors, a retained `chunk_count` counts chunks
that no longer exist, so an archived case's export and report both over-count
its index.

The alternative was to keep the number as history and teach all four readers
that `Archived` means the figure is historical — a value that is only correct
in some states, read by code that does not know about the others. That is the
§18 failure one layer down. So archive now **zeroes** `chunk_count`, and the
invariant is the simple one: **`chunk_count` is what is in the index right
now.** `entity_count` is untouched, because entities live in the database and
archiving never removed them — it is still true. The removed count is recorded
in the audit entry instead, where history belongs.

### Also refused: archiving mid-ingestion

The worker holds the evidence row and keeps writing chunks into the collection
the archive is about to empty. Archiving during a `Queued`/`Running` job would
drop the item out of the case and then write its vectors straight back into an
index nobody is shown. Now a 409, naming the job status and telling the
operator to stop it first.

### A test bug worth recording: the guard that passed only while a cache was warm

The gate — with its §21 parser, correctly — reported **2 failures** in
`verify_prompt_budget.py` while Ollama was **not running**:

```
FAIL  J5 num_ctx is on the wire ...  options carried {}
FAIL  J6 the wire value is the clamped one  wire None vs requested 16384
```

The product was correct. Instrumenting one `generate_response_detailed()` call
showed the truth:

```
[0] /api/show      options = None
[1] /api/show      options = None
[2] /api/generate  options = {'temperature': 0.1, 'num_predict': 1024, 'num_ctx': 16384}
[3] /api/show      options = None
```

`num_ctx: 16384` **was** on the wire. The capture kept a **single slot**, so the
assertion read whichever request happened to be *most recent* — which is not
the request under test. A `/api/show` capability probe is issued **after**
generation, because the response analysis re-reads the window; while Ollama is
up that probe is served from cache and never happens, so the slot still held
`/api/generate` and the guard passed.

> **The guard was passing for the wrong reason, and only a stopped daemon
> revealed it.** With Ollama down, `model_context_limit()` re-probed on every
> call — its cache short-circuited only on a **non-`None`** value — so the slot
> held the probe, whose payload has no `options` key at all.

The capture now records every request and selects by **URL**. Added `J5a`,
which asserts that a `/api/generate` request was observed at all — otherwise
"no `options`" and "no request" are indistinguishable, which is the same
ambiguity that made `store_chunks` return `0` for both success and failure
(B10). **85 assertions, 0 failures, with Ollama stopped.**

### The same finding was a real product cost, not only a test artefact

Three of those four requests were `/api/show`, because an unreadable
capability was never cached at all. Against a daemon that accepts the
connection and then hangs — a real state for Ollama, and the state this box
was in — that is up to 5 s × 3 added to **every query** before the genuine
error can surface.

The cache now short-circuits on a **failure** too, with a deliberately short
5 s TTL so a restarted Ollama is picked up almost immediately (§16's rule: a
failed session must not be permanent). Measured, not assumed:

| | before | after |
|---|---|---|
| requests per `generate_response_detailed()` | 4 | **1** |
| `/api/show` probes over 4 sequential calls | 12 | **1** |
| capability reported | `None` | `None` — unchanged, still honest |

> **Trap, in the fix for that:** the cache's `at` initialised to `0.0`, and
> `time.monotonic()` is measured from an arbitrary origin and is *small* on
> some platforms — so a fresh process could report "unreadable" for the first
> seconds of its life purely because the clock had not reached the sentinel.
> `at is None` now means "never probed" and cannot satisfy the TTL. A cache
> sentinel is an assumption about a clock, and this one was wrong.

### Verification — `tests/verify_evidence_archive.py` (new, 38 assertions)

Outcome assertions only: list contents, database status, HTTP codes. Qdrant is
stubbed, because embedded Qdrant takes an exclusive lock per directory (§15) and
the claims under test are about the archive's contract, not Qdrant's delete
semantics. Sections **A** the regression · **B** hidden, not destroyed ·
**C** restore is honest about the index · **D** the three refusals ·
**E** a failed cleanup must not archive · **F** the delete is scoped to one
item and one collection · **G** an Investigator may archive and a Viewer may
not.

**Verified discriminating:** with `evidence.py` reverted to its pre-fix logic the
suite fails **22** assertions; restored, it passes **38**. One assertion is
named `an Investigator archiving succeeds (pre-fix: 403)` so the old failure is
visible in the failure list itself, not only in this file.

#### Three test bugs of my own, each of which hid a real distinction

- **`keep + [ev_ids[2]]` raised `TypeError`** — `keep` is a string. The suite
  died mid-run, which is the good failure: it stopped rather than printing a
  green summary it had not earned.
- **I asserted `file_path` on the API response.** `EvidenceResponse`
  deliberately does not expose it — a server-side path has no business in a
  client payload — so the assertion was checking the wrong surface. Then my
  replacement compared `_paths_of(...)` **to itself**, which is the vacuous
  `x != 4096 or True` from §21 in a new costume. The honest version captures
  the paths *before* the archive and compares after: "still on disk" is only a
  claim against the prior state.
- **Section F reused section A's recorder**, so it measured four calls of
  accumulated history instead of its own behaviour. A shared accumulator is
  never a witness for the current call.

> Each is §22's habit 2 in reverse: a guard that cannot fail is worse than no
> guard, because it is believed.

### The gate caught a syntax error I introduced, in one pass

While fixing the `chunk_count` invariant I left `evidence.py` with **two**
`details=` arguments in one call — a duplicated block from a bad edit. Six
suites could not even import the app.

Worth recording for two reasons. First, **how**: `py_compile` had passed on that
file minutes earlier, because I compiled after the *previous* edit and did not
repeat it after the next one. Three edits to one file, one compile check,
placed at the wrong point. **Compile after the last edit, not after the first.**

Second, and more useful, **what the gate did with it**:

```
??   verify_service_health.py   counts unreadable (exit 1)
  ...
  GATE COULD NOT READ: verify_evidence_archive.py, verify_file_formats.py, ...
  Treat this run as invalid - the totals above are not trustworthy.
```

It refused to total the run, and said in words that the numbers could not be
trusted. A gate that had fallen back to `0 passed / 0 failed` for the five
unreadable scripts would have printed **405 passed, 2 failed** and exited
non-zero — technically a failure, but with a total that looks like a
measurement. That is TRAP 8's fix (§21) earning its keep on a case nobody
designed for it: not a summary-format change, but a genuinely broken tree.
---

## 24. Audit pass before review — B30, B31, and five defects verification would never have found

A full read of the codebase and a live pass over every page, on the way to a
review. Four of the eleven findings below were **not** found by reading the
code that contained them. They were found by a DOM probe, a metric that
measured the wrong thing, an air-gap requirement, and three test suites that
turned out to be passing for the wrong reason. The pattern is §22's, one level
up: this file keeps recording verification that reported success without
measuring anything, and the places it does that are not obvious from a diff.

### ✅ FIXED B30. A failed search was reported as "nothing matched" — and that clears a suspect

`search_chunks` ended in the shape this file exists to prevent:

```python
except Exception as e:
    print(f"QDRANT SEARCH ERROR: {e}")
    return []
```

`run_rag_query` cannot tell an empty list from a failed search, so a locked
Qdrant directory, a missing collection or a dead embedder produced the sentence
**"Nothing in this case matched that question, and the model returned no
analysis."** That is the exculpatory direction. A B1 or B10 stale row is a
cosmetic problem; this one tells an investigator, in the app's own voice, that
the evidence supporting a suspect is not there. It is the most consequential
instance of the defining defect in the repo, and it had been there since the
vector store was written.

- `search_chunks` now raises `VectorStoreError` with the underlying reason
  attached, exactly as `store_chunks` does (B10's fix, already in the file).
  `StopIteration` is re-raised first, for §15's reason.
- `run_rag_query` catches it and returns an answer that says the search could
  not be run, names the reason, and states explicitly that **nothing has been
  ruled out**. `prompt_stats.retrieval_failed` and `.retrieval_error` make the
  two states distinguishable to a caller. The model is not consulted.

> **Generalisable, and it is the half that was easy to miss:** the honest
> "nothing matched" message did exist — inside the empty-response branch of
> `process_response`. So it was only reachable **if the model happened to
> return nothing**. Handed a question, an entity graph and zero excerpts, a
> chat model will happily produce a paragraph, and the investigator reads it as
> a finding. The app's own statement of what it found must not depend on the
> model's behaviour. There is now an early return for "the search ran and
> nothing survived", which also names *why* — an empty collection and a
> relevance floor that dropped everything are different situations with
> different next steps.

This is also the cheap path: a grounded answer costs a 13,000-token prefill on
CPU, measured at 165 s, and this state is reached by exactly the questions that
have nothing to retrieve.

### The relevance floor, and why the number is not a guess

Qdrant returned `top_k=7` **unconditionally** and `build_prompt` divided the
context allowance between all seven, so a real question about a suspect and a
question of "hi" were answered from the same seven excerpts. Retrieval scoring
exists to be thresholded and it was not.

The scores recorded in `query_logs.chunks_used` on this corpus (12 queries,
ranked within each) put the threshold in evidence rather than in taste:

| query | scores |
|---|---|
| "hi" / "hello" | 0.134 – 0.138 |
| "what is duck?" | 0.060 – 0.076 |
| suspect email / phone | 0.094 – 0.107 |
| operators and hosts | 0.465 – 0.476 |
| suspect behind darknode.io | 0.395 – 0.476 |

There is a **gap between 0.138 and 0.395 with nothing in it**; the floor sits
in that gap (0.25), not on a round number. `verify_retrieval_integrity.py` §F
pins it between the two clusters, so changing it to any value outside the gap
**fails the suite**.

Two caveats recorded in the constant's own comment, so the next person does not
mistake this for settled: the sample is small and several entries are
near-duplicates of "hi"; and cosine similarity is not calibrated across
embedding models, so this threshold is a property of `all-MiniLM-L6-v2` over
this corpus. It is exposed in `prompt_stats` so a surprising answer can be
explained rather than guessed at.

- `RETRIEVAL_TOP_K = 14`, wider than before, because a floor applied after
  retrieval needs candidates to drop. Fetching 14 and discarding the weak ones
  beats fetching 7 mediocre ones.
- `chunks_retrieved` is the count **before** the floor and
  `chunks_below_floor` the count after, so "retrieved nothing" stays
  distinguishable from "retrieved 14 and kept none".
- A chunk with **no score is kept**. The floor is a statement about a
  measurement; refusing to act when there is nothing to compare is correct, and
  silently discarding every chunk from a caller that does not supply scores
  would turn a missing field into "no evidence" — B10's shape, one layer over.

### 🔴 A negative result: the degenerate-chunk filter was not warranted, and I nearly shipped it

The demo corpus is visibly full of filler — 44% of its lines are runs of `=`
and `-`. The obvious fix is to skip degenerate chunks at retrieval. **Measured,
that filter would have dropped 0.0% of chunks**, because no chunk in the corpus
is more than 86% decorative lines (the separator runs are interleaved with real
log lines inside every chunk).

The first version of the measurement said something else — "52% separator
characters", and chunks that "compete for top-k slots" — and that number is
**wrong**. The metric counted ` ` and `\n` as separator characters, so ordinary
prose scored 0.43 and a run of bare `=` scored 0.40. Measuring by **line**,
against `^[=\-_*#~\s]+$`, gives the real figure: 44% of *lines*, and zero
degenerate chunks.

> **Two lessons, both worth more than the filter.** (1) A threshold chosen to
> match a metric that measures the wrong thing is a safeguard that does
> nothing while looking like one — the code-level twin of B22's fabricated
> health card. (2) The filler *dilutes* the embeddings of the chunks it shares
> with; it does not displace them. The relevance floor handles dilution
> correctly and the heuristic would not have. **No filter was added**, and this
> paragraph is here so the next agent does not add it.

### 🔴 TRAP 10 — an air-gap tool was calling `ip-api.com`

`get_geo_data` in `backend/main.py` geolocated IP entities by making an
**outbound HTTPS request to a public geolocation service**, for every batch of
IP entities it was shown. The product's stated requirement is that nothing
leaves the machine. The map also renders the *investigator's* IP-derived
location, which is both an air-gap violation and a privacy problem, and in an
offline deployment it hung for up to 100 s per lookup.

Removed outright. EXIF geolocation — which is read from the evidence file
itself and never leaves the machine — is kept. IP entities now come back with
`lat/lon: null`, `type: "ip_not_geolocated"`, and a new `ip_geolocation` state
object saying `not_attempted`, with `count` and `located: 0`, so the UI can
say *not geolocated* rather than draw a pin at (0, 0). Verified live: 20 ms
instead of up to 100 s, 47 IPs, `state=not_attempted count=47 located=0`.

> **The generalisable form:** an air-gap claim is a property of the *whole*
> dependency graph, including runtime HTTP. `grep` for a hostname finds
> deliberate calls; it does not find a library that phones home, and it says
> nothing about what a `fetch` in a frontend component reaches. This one was in
> a function nobody had read since it was written.

### ✅ FIXED B31. Four identity fields that looked editable and were not

The investigator could type a name into "Investigator Name", "Author",
"Officer name" and "Prepared By", and the server stored **whatever they typed**.
Chain-of-custody records that name as who did the work. A user could attribute
a note, a report, a case or a query to any other user, including an Admin, and
the audit log would agree with them.

The fix is server-authoritative: the authenticated user is recorded for every
attribution, and the client-supplied identity fields are **ignored, not
trusted**. `asked_by`, `created_by`, `author`, `generated_by` and
`ingested_by` are no longer accepted from the body at all.

The four visible name inputs were **replaced with a read-only badge** showing
the signed-in user, rather than left in place and ignored. A field that looks
editable and is not is the B29 defect: the operator believes they said
something, and the record says something else.

`tests/verify_identity_attribution.py` (19 assertions) forges `"admin"` in a
request body and asserts the database says otherwise, then sweeps the routers
for any remaining `body.<identity>`. **Verified discriminating: 19/19 on the
fix, 11 failures on the reverted code.**

### 🔴 TRAP 11 — three test suites were passing through a privilege-escalation hole

`POST /api/auth/register` accepted a `role` in the request body and honoured
it. That is the escalation hole B31's sibling, and §3's own note ("first
registered user becomes Admin; later ones default to Analyst") says the
behaviour is *supposed* to be fixed.

It was not fixed, and it was masking itself: **`verify_queue_api.py`,
`verify_job_stop.py` and `verify_live_stack.py` all registered with
`"role": "Investigator"` and passed** — not because the suite worked, but
because the suite was quietly asking for the privilege it needed. The
escalation is now impossible (the backend assigns Analyst to every later user)
and all three suites **promote in the database** instead.

> A test that passes because the product has a security hole is worse than a
> failing test, because it converts the hole into a fixture. When a test
> *registers a user with a role*, that is a signal to check whether the
> registration endpoint is allowed to honour one — not a convenience.

### ✅ FIXED — the file viewer rendered error pages as evidence

`FileViewer.jsx` fetched with `r.text()` and **no status check**, so a 401, 403
or 500 resolved successfully and its body became the file. The text viewer
showed `{"detail":"Not authorized"}` under a filename. The email viewer parsed
that same body into a message with no `From`, no `Subject` and no `Date` and
presented it as a recovered email. `EmailViewer` also ended in
`.catch(() => setLoading(false))`, so the failure surfaced as "Could not parse
email" — blaming the evidence for what was an auth error.

Both go through one `fetchChecked` that refuses a non-2xx and throws an
axios-shaped error, so the existing `apiErrorMessage` precedence ladder is
reused rather than a second, subtly different one. In a forensic viewer a
fabricated artefact is worse than a visible failure, because it is the one
thing on screen a reviewer cannot sanity-check at a glance.

### ✅ FIXED — four silent `var()` no-ops in the entity graph canvas

`EntityMapPage.jsx` assigned canvas colours from CSS custom properties
(`ctx.fillStyle = 'var(--accent)'` and similar). **An invalid value assigned to
`fillStyle`/`strokeStyle` is a silent no-op** — the previous colour survives, no
error, no log. The graph was drawn in whatever colour happened to be left in
the context. Now read through `readCanvasPalette()` / `useCanvasPalette()` with
a `CANVAS_IS_USABLE_COLOR` test, and the palette is in the dependency array so
a theme change actually repaints.

### ✅ FIXED — CDN fonts and a CDN Leaflet build

`index.html` loaded Inter and JetBrains Mono from `fonts.googleapis.com` and
Leaflet CSS from `unpkg.com`. Two problems: an offline machine gets the system
fallback and a different-looking app, and a forensic workstation silently
phones out on every page load. Both are now local — `@fontsource/inter` (300 to
700) and `@fontsource/jetbrains-mono` (400/500), with `import 'leaflet/dist/
leaflet.css'` in `main.jsx`. **All subsets are kept** (latin, latin-ext,
cyrillic, greek, vietnamese; 547 KB) because the entity names in the evidence
are not reliably ASCII.

> **Grep cannot verify this.** An explanatory HTML comment in the built
> `dist/index.html` still contains the strings `fonts.googleapis` and `unpkg`.
> Verify the *fetchable* `href`/`src` attributes, not the file's text.

### ✅ FIXED — the system prompt told the model the evidence was fake

`SYSTEM_PROMPT` opened with a paragraph asserting that this is "a fictional
Capture the Flag (CTF) training simulation", that all evidence is "entirely
simulated and not real", and that the model "MUST answer all questions ... Do
not refuse to assist."

For a forensic product that is the worst possible opening line: it tells the
model its grounding is imaginary, in a tool whose entire value is that it is
not — and a reviewer will correctly challenge the app for claiming its own
evidence is fabricated. It also invited the exact failure B26 was about, by
pressing the model past its own caution instead of giving it more evidence.

Replaced with an honest version of the intent: *this is real casework, answer
the question, the presence of sensitive material is the reason the case exists
rather than a reason to withhold it, and never invent — an answer you cannot
ground is worse than an answer that says what is missing.* No test referenced
the old text.

### Two more, both the same shape as §24's larger theme

- **A dangling byline.** With `model_used: null` — which is now the correct
  value whenever the question never reached the model — `InvestigatePage`
  rendered `{q.model_used}` unconditionally, leaving `· 0.1s` and implying a
  model had replied. It now prints `No model consulted · 0.1s`. Ninth
  occurrence of §16's rule in this file.
- **Invalid HTML in the artifact list.** `ArtifactsPage.jsx` nested `View` and
  `Flag` `<button>`s inside the row's own `<button>`. A `<button>` inside a
  `<button>` is invalid; the browser hoists the inner ones out of the row, so
  the row's click handler stops covering them and the keyboard cannot reach the
  row at all. The row is now a `div` with `role="button"`, `tabIndex` and an
  `onKeyDown`.

### A negative result worth keeping: `?token=` is not dead

`FileViewer` builds media URLs as
`/api/cases/{id}/evidence/artifacts/{id}/view?token=...`, and I had recorded
that as a dead fallback to be removed. **It is correct and load-bearing.**
`<img>`, `<audio>` and `<video>` cannot set an `Authorization` header on a
`src`, and `evidence.py:1363-1387` accepts the token as a query parameter
precisely for that. Removing it would break inline media viewing for every
viewable artifact. Do not "clean this up".

### A third test bug, and a new shape for §22's habit 1

The full gate came back **931 passed, 2 failed** after the chunk sizes were cut,
and both failures were in `verify_ingestion_modes.py`:

```
FAIL  normal:   chunk count matches chunk_size 6000 - expected 10, got 11
FAIL  accurate: chunk count matches chunk_size 3000 - expected 20, got 22
```

**The product was right and the test was wrong.** `chunk_text` advances by
`chunk_size - overlap`, so the count is `ceil(len / stride)`. The assertion
computed `ceil(len / chunk_size)`, which is only the chunk count when overlap
is **zero**. Overlap is not a rounding artefact — it is what stops a fact
straddling a boundary from being lost, and it was added deliberately to `normal`
(200) and `accurate` (300) in the same change that produced this failure. So
the fix was to the assertion, and deliberately *not* to the product.

The corrected formula is **stricter than the one it replaced**, which matters:
the old expression could not tell "chunk_size reached the pipeline but overlap
was silently dropped" from success, because it never looked at overlap at all.

This is §22's habit 1 in a shape the other two instances did not cover. Those
were literals encoding a *device* fact (`ram_floor_max_mb`, `estimated_tokens <
4096`). This one encoded a **product assumption that a later change removed** —
and nothing about it looked like a device fact, so it would not have been
suspected.

> **When a deliberate product parameter changes, assume some assertion is
> quietly assuming its absence.** Search the tests for the arithmetic before
> touching the table, not after the gate goes red.

Two assertions were added alongside it rather than just correcting the formula:

- `overlap < chunk_size` is asserted, not divided by. A non-positive stride
  makes `chunk_text` never advance and loop for ever, so the failure must name
  the cause instead of raising `ZeroDivisionError`.
- The `len(c.strip()) > 20` trim inside `chunk_text` **is measured to be a
  no-op on this input** (`chunker returned 11, stride arithmetic says 11`)
  before exact equality is claimed. Without that, exact equality is a
  coincidence rather than an assertion — if `BODY` is ever changed to end in
  whitespace the count quietly stops matching and the formula would be blamed
  for something it never claimed.

Also worth recording, since it nearly became a false alarm: the suite's own
exit code is **0** on a clean run. The `Exited with code 1` in that shell
session came from PowerShell's `Select-String`, not from the test. The gate
reads both the summary *and* the exit code, so a suite must be run bare when
the exit code is what is being checked.

### What this session changed, in one place

| | |
|---|---|
| **Fixed** | B30 (search failure vs no match) · B31 (server-authoritative identity) · relevance floor · CTF paragraph · `ip-api.com` · canvas `var()` no-ops · CDN fonts/Leaflet · `FileViewer` error bodies · artifact nested buttons · `model_used` byline |
| **Measured and rejected** | the degenerate-chunk filter (0.0% of chunks would drop) · removing `?token=` |
| **New** | `tests/verify_retrieval_integrity.py` (36 assertions) · `tests/verify_identity_attribution.py` (19) · chunk sizes `fastest` 12000, `normal` 6000/200, `accurate` 3000/300 · `RETRIEVAL_TOP_K` 14 |
| **Negative results** | see the two above — both are traps for the next agent |

### Read before touching these

- **`rag_engine.py`** — §19's budgeter, §20's window, and B30's floor. The
  floor is pinned to a measurement; `verify_retrieval_integrity.py` §F fails if
  it is moved outside the observed gap.
- **`vector_store.py`** — B10 (`store_chunks` raises) and B30 (`search_chunks`
  raises). Both must keep re-raising `StopIteration` first, for §15's reason.
- **anything that renders a field shaped like a measurement.** Nine instances
  in this file; the newest is the byline above.
- **`tests/verify_queue_api.py`, `verify_job_stop.py`, `verify_live_stack.py`** —
  they promote roles **in the database** on purpose. Reopening the
  registration escalation to make a test pass is a regression, not a fix.

---

## 25. The gate went red because the suite was racing a worker — and the suites were writing to the live database

Two findings, both from running the full gate after the chunk sizes were cut.
Neither is a product defect. Both are defects in the instrument that is
supposed to catch product defects, which is the one place this class of error is
least welcome.

### The gate failure that looked like a regression

```
FAIL  patch returns 200 - {"detail":"The ingestion profile is fixed once a
      job starts - it sets the chunk size and embedding batch, and changing
      either mid-run would leave the case half-indexed at mixed granularity.
      Cancel this job and queue it again ..."}
FAIL  refused profile left the stored mode untouched - accurate
```

**The product was right.** That refusal is B16 (§17) working exactly as designed:
changing the profile mid-run would leave a case indexed at mixed granularity,
so the backend answers 400 and says why. The assertion was wrong.

### Why it failed at all: the suite was racing its own worker

`verify_queue_api.py` drives the real app through `with TestClient(app)`.
**Entering that block runs the FastAPI lifespan**, and the lifespan calls
`job_worker.start_worker()`. So the suite was polling for `Queued` jobs — the
same ones it had just created through `/api/queue/add` — with a live thread, for
its entire run. The worker's loop wakes every 2 s; the suite's next request can
easily arrive after that. When it did, the row said `Running`, the refusal was
correct, and the assertion failed against correct behaviour.

The first gate run passed the same assertion and the second one did not. That
intermittency is the finding: **an assertion that depends on a race is a
measurement that reports success without measuring anything** (§22's theme, in
the tool that exists to stop it). The previous green run was the accident.

The fix is to remove the race, not to weaken the assertion — the assertion is
testing a real and important contract:

```python
jw.stop_worker()                      # inside the `with`, after the lifespan
_t = jw._worker_thread
if _t is not None and _t.is_alive():
    _t.join(timeout=30)               # the loop sleeps up to 2 s; not instant
```

> **It has to go *inside* the `with`.** The lifespan runs on entry, so stopping
> the worker before the block means it gets started again immediately after.

Audited rather than assumed: of the four suites that enter the lifespan, only
this one **creates** a `Queued` job and then asserts on its status. The other
three — `verify_job_stop.py`, `verify_evidence_archive.py`,
`verify_identity_attribution.py` — create no jobs at all (`verify_job_stop.py`
inserts its job as `Running` and drives `_process_job` itself), so the stop is
not warranted there and adding it "for symmetry" would be churn on suites that
cannot race.

> **Generalisable:** a suite that enters an app's lifespan inherits everything
> the lifespan starts. Background threads are the part that matters — they do
> not belong to the caller, do not appear in the API, and will happily mutate
> the fixtures the suite is about to assert on. If a test framework offers
> `TestClient(app)` *without* the context manager, the difference is the
> lifespan, and that is usually the whole point.

### 🔴 The suites had been writing to the live forensic database

Found while diagnosing the above, and much the more serious of the two.

```python
db.query(m).filter(m.id.in_(ids)).delete(...)   # job, evidence, case
os.remove(path)                                  # the temp file
```

That cleanup sat at the very end of the happy path, with **no `finally` and no
`atexit`**, and it **never deleted the registered user**. Measured on
`data/forensic.db` before the fix: **92 test accounts** (`modes_*`, `stop_*`,
`arch_*`, `b31_*` — one per suite run) and **249 audit rows** attributed to
usernames that had been deleted, plus an orphaned `API modes` case and its
`apimode_*.txt` evidence. Every run of the gate had been adding to it.

`verify_live_stack.py` hit the identical problem and fixed it with an `atexit`
hook long ago (§14). The other four were never converted. The rows did not break
anything, which is exactly why they accumulated for this long.

> **A test suite that writes to the live database is a defect in its own right**
> — and in this product specifically, because the database *is* the evidence
> record. `verify_service_health.py` already established the rule for itself:
> *"Nothing here touches `data/forensic.db`."* Three of the four suites that
> violate it are the ones that register a user.

New `tests/_purge.py` holds the one implementation, shared by all four. It
records ids and the throwaway account as they are created, and deletes them
from an `atexit` hook, so it fires on a failed assertion, an exception, and
`sys.exit(1)` alike. Two details in it are easy to get wrong and fail
**silently**, which is why they are commented at the definition:

- **Children are deleted before parents.** `Query.delete()` bypasses ORM
  cascades, so the ordering is the only thing between a partial run and a
  foreign-key error.
- **Audit rows carry the username in `performed_by`, not the user id.**
  `_log_auth_event` passes `details["username"]`. Filtering `performed_by` by
  *id* deletes nothing at all and leaves the account's own audit trail
  orphaned behind a name that no longer resolves to anything. This was written
  wrong on the first attempt in `verify_queue_api.py` and only corrected by
  reading the helper — a filter that matches nothing is indistinguishable from
  one that worked.

**Verified by measurement, not by reading the code**: a script counts the
throwaway rows, runs all four suites, and counts again. Delta 0 for users,
audit rows and cases. All four pass — 52 + 17 + 38 + 19 = **126 assertions**.

**Full gate, servers stopped: 940 passed, 0 failed across 15 scripts**, and the
per-suite lines sum to exactly 940. That reconciliation is the check that
matters: a mis-parsed total is a number that does not agree with its own parts,
and §21's TRAP 8 was precisely a total that did not.

> The pre-existing 92 accounts were left alone, deliberately. A test script
> silently deleting rows it did not create is the behaviour these suites were
> just corrected for, and the operator was asked.

### Why this is worth more than the two bugs

§22 listed six bugs that verification caught rather than reading. This is the
seventh instance, and it points the other way: **the verification itself
produced a red result the product did not earn**, one run after a green one that
earned nothing either.

A flaky suite is worse than no suite, because a green one is believed and a red
one is acted on. The day before a review, a red gate that looks like a product
regression is close to the worst possible failure — it invites somebody to
"fix" correct behaviour, and the fix would be to delete the refusal. §21's
TRAP 8 is the same shape one layer out: a summariser that reported 0 failures
for a suite with 15 converted a red run green. Here the parser was fine and the
*input* was noise.

> **So the gate has two independent ways to lie, and they pull in opposite
> directions.** A parser that cannot read the summary turns red into green
> (TRAP 8). A test that depends on a race turns correct into red. Neither is
> detectable by reading the other, and a fix for one does not touch the other.
> Fixing the parser is a parser problem; the only cure for the second is to
> remove the timing dependency, which means knowing which side of the race the
> product is on — and that is a question about the product, not the test.

---

## 26. Re-ingesting the last stale row — and my own instrument reported a fake `0`

The one piece of pre-existing evidence data still disagreeing with itself: the
PDF in Test1 read `status=Indexed, chunk_count=1` while its Qdrant collection
was believed to hold 0 points. A row that looks searchable and returns nothing
is §15/B14 rebuilt from the other side, and an investigator searching there
concludes the evidence was clean.

### I re-ingested it, and my helper said it failed

```
[INGESTION] Done: 5 chunks, 135 entities (pdf, mode=normal)
  row says : status=Indexed  chunk_count=5
  qdrant   : 0 points
VERDICT: STILL DISAGREE
```

Asked Qdrant directly instead of trusting the helper — **5 points, 384-dim,
all tagged with the right `evidence_id`, collection green.** The helper looked
for a collection whose name contains the full case UUID; the real name is
`case_f15d31a9` — the **first 8 characters**. It found no match and returned
`0`, because `0` is what "the collection list was not empty and nothing matched
it" also evaluates to.

> **That is §16's rule, committed by me while writing the rule down**, and it is
> the tenth occurrence of it in this file. A check that cannot distinguish
> "measured, and it is zero" from "looked for the wrong key" reports a
> confident `0` in both cases, and `0` is precisely the reading that looks like
> "the evidence is clean."
>
> **Generalisable:** a helper that *filters* what it found must be able to
> report that the filter excluded everything. `return 0` on an empty match is
> the same `except: return 0` shape as B10, with the exception replaced by a
> `next(..., 0)`. The two scripts disagreed, and the one that disagreed with
> the product was mine.

The re-ingest itself was two mistakes of my own, both instructive:

- **Wrong positional order.** The signature is
  `(evidence_id, case_id, file_path, filename, job_id)`. I passed the case id
  first, so the pipeline was handed a UUID as `file_path`, found no file, and
  **returned successfully in 0.3 s**. A "successful" ingest that read a
  non-existent path is precisely B1's shape reached by a typo rather than a
  bug — and it produced no error, so nothing in the output said otherwise.
- **`ingestion_jobs.evidence_id` is UNIQUE**, so the botched run's job row made
  the second attempt fail on insert. `queue_router.add_to_queue` deletes any
  existing row for the same evidence to satisfy exactly this constraint; the
  script had to do the same rather than invent a second id.

Final state, verified against Qdrant and not against the row: **Indexed,
5 chunks, 135 entities, 5 points in the index.** The row and the index agree.

> The pre-ingest state is now unverifiable — the collection was rewritten, so
> whether it held 1 point or 0 before cannot be recovered, and the original
> "chunk_count=1 vs 0 points" reading was made with an instrument now known to
> be broken. **It should not be reported as a confirmed defect.**

### `entity_count` is a count of mentions, not of rows — and four readers assume rows

`evidence.entity_count = 135`, but only **113** entity rows carry this
`evidence_id`. The 22 are not missing and not duplicates (`GROUP BY name,
entity_type` finds no repeat within the document); they are entities that
already existed in the case from an earlier ingest and were merged rather than
re-inserted. `build_graph` reuses entities across a case, which is correct.

So `entity_count` means *distinct entities this document mentions*, and it is
read as if it meant *entity records attributable to this document* by
`cases.py:1112` (export), `reports.py:174`, `report_generator.py:201` (PDF) and
`queue_router.py:432`. A reviewer who opens the database and counts gets a
different number from the report, with no way to tell which is right.

> **This is B29's `chunk_count` problem in the neighbouring column, and it is
> not fixed.** B29 resolved it by making `chunk_count` mean "what is in the
> index right now", because that was the simple invariant. `entity_count`
> cannot adopt the same invariant without either dropping the count or counting
> rows instead of mentions — and counting rows would report **113 for a
> document that surfaced 135 distinct entities**, which is the opposite error.
> It needs a label change ("entities mentioned" vs "entity records") before a
> reviewer reads the two numbers as one, and that is a decision rather than a
> bug fix. Flagged, not churned the day before a review.

### 🔴 421 of Test1's 534 entities point at evidence that does not exist

```
263  56a19bf1  ORPHAN - no such evidence row
120  fb8cc81b  ORPHAN - no such evidence row
113  3df5c449  exists
 38  d0592b3b  ORPHAN - no such evidence row
```

78 % of the entity graph in the user's own case is populated from evidence
files that were deleted. The entity graph and the entity list both show them,
attributed to the case, and there is no document behind any of them. For a
forensic tool that is worse than a count being off: **the graph asserts links
between entities that the retained evidence does not support.**

The operator was asked about earlier residue and chose to leave it alone, and
that answer is respected — but it was asked about *directories on disk*, and
this is different in kind: it is data the app actively displays. Not deleted,
not hidden, **reported**.

### `ingested_at` means "uploaded at"

`models.py:53` sets `default=datetime.utcnow` at row creation, and
`evidence.py:236/397/438` set it explicitly on all three upload paths — every
one of which also writes `status="Uploaded"`. **The ingestion pipeline never
touches it.** So after the re-ingest just performed, the row reads
`chunk_count=5` written seconds ago beside an `ingested_at` of 2026-09-27.

Harmless today, because no frontend page reads the field and its only consumer
is the ordering at `evidence.py:128` — where upload order is the correct sort.
But the name is a promise the field does not keep, and this file's whole
subject is a field shaped like a measurement that is not one. Renaming it
changes ordering semantics and needs its own decision.

---

## 27. What is still open, in one place

For whoever picks this up next, with nothing hidden:

| | |
|---|---|
| **`entity_count`** | counts mentions, four readers read it as rows. Needs a label, not a code change (§26). |
| **421 orphan entities** | 78 % of Test1's graph, from deleted evidence. Operator chose to leave them; they are still displayed (§26). |
| **`ingested_at`** | is upload time. Unused by the UI, used for ordering (§26). |
| **Test1's disk image** `8fe98ee9` | `Failed` — the truncated `SCHARDT.001` from §6 B1. Correct outcome, needs re-acquisition. |
| **~340 orphan case directories** | under `data/cases/`, from earlier runs. Left alone by the operator's choice. |
| **Re-index required** | chunk sizes are cut, so a case ingested before this session still has 30,000-character chunks. Test1 and the Phantom Trace demo are re-indexed; nothing else is. |
| **`vendor/python/torch-*.whl`** | 152 MB of dead weight — but §8's caution stands: a CUDA build is what GPU transcription needs. |
| **Chunk-size half of §19** | raising the window recovered 5.4×; smaller chunks recover the rest, and need a re-index per case. |
| **`cases.py:968`** | `author = "<imported> (imported)"` — the last client-influenced attribution, judged defensible (§24). |

---

## 28. 🔴 TRAP 12 — a no-op revert is indistinguishable from a decorative guard

§22's habit 2 is the rule this file leans on hardest:

> **Make every new guard able to fail when the fix is reverted.**

The way you check that is to revert the fix and re-run. That check is itself a
measurement, and it can lie in exactly the way every other measurement here has
been caught lying.

### What happened

Added a fixed `seed` to the Ollama request so answers are reproducible, and
wrote `J8` to guard it. Then ran the revert check. The result:

```
=== 1. with the fix ===      86 passed, 0 failed
=== 2. seed removed ===      86 passed, 0 failed      <- "the guard is decorative"
```

Which would have been a serious result: it would have said the seed reaches
nothing, which is **B27's exact shape** — a knob that only feeds the arithmetic.
And the correct conclusion was the opposite. The revert had never happened.

```python
target = '            "seed": settings.ollama_seed,\n'
if target in src: ...        # -> False. It was never True.
```

The file is **CRLF**. The target string ended in a bare `\n`, so the `str.replace`
matched nothing, the file was rewritten unchanged, and the suite was run twice
against **identical** code. The script's own `assert PATTERN in original`
checked only that the seed *existed*, which was true in both states, so it
raised nothing.

With the revert made newline-agnostic and its application **verified**:

```
=== 1. with the fix ===      86 passed, 0 failed
=== 2. seed removed ===      85 passed, 1 failed
      FAIL  J8 a fixed seed is on the wire ... wire seed None vs configured 42
VERDICT: guard is real
```

### 🔴 The trap, stated generally

**A revert that silently fails to apply produces `passes with the fix, passes
without it` — byte-identical to the signature of a guard that cannot fail.**
There is no way to tell the two apart from the suite's output, and the natural
reading of that result is the alarming one.

So "verified discriminating" is not a single measurement. It is two, and the
first one is about the *harness* rather than the suite:

1. **the revert applied** — assert on the *absence* of the change afterwards,
   not the presence of it before. `assert PATTERN in original` proves the fix
   existed; it says nothing about whether you removed it.
2. **the suite went red on that assertion and not another** — the failure line
   should name the reverted behaviour.

A harness that cannot prove (1) has not measured (2), and its verdict is a
confident `0` — the eleventh occurrence of §16's rule in this file, and the
second one committed by me (§26) *while writing the rule down*.

> **Do not trust a "verified discriminating" claim that was not checked twice.**
> §21 and §24 verified theirs by reverting and reading the failure count. That
> was sufficient there because those reverts were done by editing files in the
> editor, where a failed match is visible. A *scripted* revert hides it, because
> the script's job looks like it succeeded.

### Why it belongs here rather than in a footnote

This is the check that guards every other check in this repository. If the
revert harness can silently no-op, then "verified discriminating" is a claim
about a run nobody can reproduce, and the whole edifice rests on a measurement
nobody looked at closely — which is §22's exact theme, one meta-level up.

### What the seed is for, and why the other sampling parameters are absent

`temperature: 0.1` **still samples**. So without a fixed seed, two runs of the
same question against the same evidence return two different answers, and §20
is the proof: its "did the model see the fact?" column answered `no`, then
`YES`, for the *same* clamped request. That column was noise — and it is
precisely why reproducibility could not be claimed from it.

This matters for **this product specifically**: an investigator may paste an
answer into a report, and a report that cannot be re-derived is not evidence.
`OLLAMA_SEED=-1` opts back out (llama.cpp reads a negative seed as random); there
is no reason to except wanting to sample the same question repeatedly.

`top_p`, `top_k` and `repeat_penalty` are deliberately **not** sent. Ollama
already defaults them to 0.9 / 40 / 1.1, so sending them would change nothing
while implying they had been chosen here. They *were* considered: temperature is
already near-greedy, which is right for a factual claim because it keeps the
answer in the retrieved text rather than the model's priors; and the one real
risk at low temperature is **repetition on repetitive evidence** — a prompt full
of log lines is full of repeated timestamps and IPs — which `repeat_penalty` at
its default is already guarding. That reasoning is recorded in the code so the
next reader knows the absence was a decision rather than an oversight.

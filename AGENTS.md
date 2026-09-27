# AGENTS.md — Progress & Operating Guide

> **Audience:** any AI coding agent (Claude Code, Cursor, Copilot, Antigravity, Devin…) picking up this repo.
> **Rule:** read this file *before* changing code. It records verified state, known bugs, and traps that are not
> derivable from the code itself.
>
> Last verified against: `main3` @ `1915171` + the live-stack pass (2026-09-27) —
> §13 covers the ingestion rework, §14 the live end-to-end run and the three
> further bugs it found (B10/B11/B12), and **§15 the stop button, per-case
> Qdrant isolation and the optional-dependency trap (B13/B14/B15)**.
> See §6 and §12 for the forensic-image fixes.

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
meter, a per-core strip and a storage line. Everything else it knows (chassis, BIOS, per-adapter
rows, every volume, every NIC, I/O counters) sits behind a **"Show device details"** disclosure,
because a wall of static specs buries the three live numbers the panel exists for. Nothing was
deleted — a forensics box changes shape between cases, so the operator still needs to be able to
see what was detected.

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
PYTHONPATH=. python tests/verify_ingestion_modes.py   # 39 assertions, ~15 s
PYTHONPATH=. python tests/verify_ws_progress.py       # 15 assertions, ~10 s
PYTHONPATH=. python -W error::RuntimeWarning \
                    tests/verify_ws_progress.py       # also catches coroutine leaks
PYTHONPATH=. python tests/verify_queue_api.py         # 37 assertions, ~5 s
PYTHONPATH=. python tests/verify_job_stop.py          # 17 assertions, ~20 s
PYTHONPATH=. python tests/verify_vector_store.py      # 17 assertions, ~10 s
PYTHONPATH=. python tests/verify_cpu_sampler.py       #  9 assertions, ~10 s
PYTHONPATH=. python tests/verify_gpu_telemetry.py     # 171 assertions, ~20 s
PYTHONPATH=. python tests/verify_live_stack.py        # 26 assertions, ~90 s
```

Windows: `$env:PYTHONPATH="."` then `venv\Scripts\python.exe tests\<name>.py`.

The first seven are self-contained; **305 assertions total**. `verify_live_stack.py`
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



# AGENTS.md — Progress & Operating Guide

> **Audience:** any AI coding agent (Claude Code, Cursor, Copilot, Antigravity, Devin…) picking up this repo.
> **Rule:** read this file *before* changing code. It records verified state, known bugs, and traps that are not
> derivable from the code itself.
>
> Last verified against: `main3` @ `0fa8358` + uncommitted fixes (see §6, §12).

---

## 0. Read this first — branch topology is a trap

This repo has **four long-diverged branches**. `git log` on any one of them tells you almost nothing about
the others. They share only a common ancestor.

| Branch | HEAD | Notes |
|---|---|---|
| `main` | — | GitHub **default branch**. Oldest. Not the working branch. |
| `Main2` | `0687a86` | "Government-grade" amber/steel UI. **Has the docs** (`AGENTS.md`, `CLAUDE.md`, `CFI_Setup_Guide.md`). |
| `main3` | `0fa8358` | **← You are here.** Indigo/violet redesign + light-mode CSS-var refactor. **Docs were lost in the redesign.** |
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
| Embeddings | **SentenceTransformers `all-MiniLM-L6-v2`**, 384-dim | 🔴 `requirements.txt` declares torch/sentence-transformers *absent* (see B4) but `vector_store.py` still imports them — a fresh install per `requirements.txt` will `ImportError`. Unfixed. |
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
remained and `vendor/` bundles a ~2 GB `torch-2.3.0` wheel nothing imports. Both pins
(`torch==2.3.0`, `sentence-transformers==2.7.0`) are now **removed**, with an inline comment warning
future agents not to re-add them. **Remaining:** `vendor/python/torch-2.3.0-*.whl` is still on disk
and should be deleted so the air-gap kit stops shipping dead weight.

### 🔴 OPEN B5. Ollama-offline path wastes 25 s and returns an error string as an answer

`data/forensic.db` shows a `QUERY_MADE` audit entry with
`raw_llm_response = "⚠️ Ollama is offline. Please start Ollama and try again."` and
`response_time_ms = 24708`. The offline check happens *after* the timeout, so the UI shows a
24.7 s "thinking" pause and then stores an error as if it were a model response.
**Fix:** probe Ollama's health endpoint before starting a generation request.

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

## 8. Uncommitted work (do not lose this)

`main3` has a **dirty working tree** — Windows/air-gap porting that was never committed:

```
 M frontend/package.json      + "packageManager": "yarn@4.18.1"
 M requirements.txt           (the corrupted B3 edit)
 M setup.sh                   installs spaCy from vendor/, npm → yarn
 M start.bat                  npm → yarn
?? frontend/.yarn/  frontend/.yarnrc.yml  frontend/yarn.lock
?? setup_windows.bat  start_windows.bat
?? vendor/                    ~40+ wheels + en_core_web_lg/spacy model tarballs
?? yarn.lock
```

`vendor/` is the **air-gap install kit** — it lets `setup.sh` install spaCy and all Python deps with
no network. It is large and untracked; decide whether it belongs in git or a release artefact.

### 🔴 Security action required
`git remote -v` shows the origin URL **embeds a GitHub personal access token**:
```
https://<user>:<PAT>@github.com/Shrishacm/Cognitive-Forensic-Investigator.git
```
It is stored in plaintext in `.git/config` and **must be rotated** — it was also printed into this
repo's terminal history. Rotate the token, then replace the remote with a credential-free URL:
```bash
git remote set-url origin https://github.com/Shrishacm/Cognitive-Forensic-Investigator.git
```

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

1. **Rotate the leaked GitHub PAT** (§8) — security first.
2. **Commit the air-gap/Windows porting work** (§8) so it stops being one `rm -rf` from gone.
3. ~~Fix B1~~ ✅ done — see §12.
4. ~~Fix B2~~ ✅ done — see §12.
5. ~~Fix B3 + B4~~ ✅ done (except deleting the vendored torch wheel) — see §12.
6. **Fix B5** — probe Ollama before starting the request.
7. **Decide the GUI question** (§7) — restore `Main2` layout onto `main3` via token migration.
8. **Refresh `README.md`** against the real feature set, and restore `CLAUDE.md` / `CFI_Setup_Guide.md` from `Main2`.
9. **Keep this file updated** as work lands.

---

## 12. Changelog of agent work

### Uncommitted — raw/forensic image fixes (this session)

Files changed: `backend/modules/forensic_ingestion.py`, `backend/ingestion.py`,
`backend/modules/audit_helper.py`, `requirements.txt`, `AGENTS.md`.

- B1 fixed: real TSK errors now surface; truncation pre-flight; truncated+0-artifact evidence is
  marked `Failed`, not `Indexed`. `walk_filesystem` / `extract_file_content` untouched.
- B2 fixed: EWF vs raw chosen by magic bytes, not file extension.
- B3 fixed: `requirements.txt` rewritten as clean UTF-8.
- B4 fixed: `torch` / `sentence-transformers` pins removed.
- B5 still open.
- `vendor/python/torch-2.3.0-*.whl` still needs deleting (~2 GB dead weight).

**Verification performed:** backend imports OK · `py_compile` OK · against the real
`SCHARDT.001`: correct truncation report + `RuntimeError` carrying the true TSK error (no longer a
silent 0) · synthetic EWF header detected as `ewf` · `requirements.txt` parses with no NUL bytes.

**Not yet verified:** a full end-to-end ingest of a *valid, complete* raw image (would need a real
forensic image or a correctly constructed test fixture). The mount path was confirmed to mount a
valid FAT16 volume successfully; the risk is low because the walk/extract code is unchanged.

**Still uncommitted from before this session:** the air-gap/Windows porting work in §8.

### Still to do

1. **Rotate the leaked GitHub PAT** (§8) — security first.
2. **Commit** the air-gap/Windows work + these fixes.
3. **Delete `vendor/python/torch-2.3.0-*.whl`** (finishes B4).
4. **Fix B5** — probe Ollama health before starting a generation request.
5. **Decide the GUI question** (§7) — restore `Main2` layout onto `main3` via token migration.
6. **Refresh `README.md`** against the real feature set; restore `CLAUDE.md` /
   `CFI_Setup_Guide.md` from `Main2`.
7. **Keep this file updated** as work lands.

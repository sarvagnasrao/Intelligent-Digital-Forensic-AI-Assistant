# Intelligent Digital Forensic AI Assistant

> **An AI-powered digital forensics platform for investigative analysis of evidence — built entirely offline, on your machine.**

---

## Table of Contents

1. [Project Overview](#project-overview)
2. [Features](#features)
3. [System Architecture](#system-architecture)
4. [Tech Stack](#tech-stack)
5. [Prerequisites](#prerequisites)
6. [Quick Setup](#quick-setup)
7. [Manual Installation](#manual-installation)
8. [Running the Application](#running-the-application)
9. [First-Time Setup](#first-time-setup)
10. [Demo Data](#demo-data)
11. [API Documentation](#api-documentation)
12. [Project Structure](#project-structure)
13. [Known Limitations](#known-limitations)
14. [Troubleshooting](#troubleshooting)
15. [Future Work](#future-work)
16. [Academic Context](#academic-context)

---

## Project Overview

**Intelligent Digital Forensic AI Assistant** is a full-stack digital forensics workstation that enables investigators to upload evidence files, automatically extract text and metadata, query that evidence using a local large language model (LLM), and reconstruct timelines and entity relationships — all without sending any data to external servers.

The system implements a **Retrieval-Augmented Generation (RAG)** pipeline: evidence is chunked, embedded into a vector database (Qdrant), and retrieved as context for a locally-running Ollama LLM. Investigators interact with the evidence through a natural-language chat interface, while the backend simultaneously extracts named entities, builds relationship graphs, detects anomalies, scans for credentials, and generates structured forensic reports.

This project was developed as a semester-long final project exploring the intersection of AI, cybersecurity, and human-computer interaction. The application is designed to be deployable on a standalone machine in an air-gapped forensics lab — no internet connection is required after initial setup.

---

## Features

29 screens, all implemented.

### Case Management
- Create, manage, and archive investigation cases with metadata (case number, status, priority, tags)
- Role-based case access control — cases are scoped to authorised investigators, with per-case grants
- Case detail overview with live statistics (evidence count, artifact count, entity count)
- **Case import / export** — move a case bundle between machines
- **Per-case settings page** and **AI-generated case summary**
- **Contradiction detection** — surfaces conflicting statements across evidence

### Evidence Ingestion
- Drag-and-drop upload for multiple file types: **disk images** (E01 / `.001` / DD / raw), **PDF**, **DOCX**, **PPTX**, **XLSX**, **images** (JPEG, PNG, TIFF), **audio/video**, **email** (MSG/EML), **Windows registry hives**, **plain text**
- Background ingestion queue with **live WebSocket progress** and CPU/RAM throttling controls
- Automatic text extraction via `pdfminer`, `python-docx`, `pytesseract` (OCR), `openai-whisper` (audio), `extract-msg` (email), `python-registry` (registry hives)
- SHA-256 hash chain of custody, with an integrity **re-verify** action per evidence item
- Forensic disk image traversal using `pyewf` + `pytsk3` (The Sleuth Kit), with **pre-flight truncation detection** (see [Known Limitations](#known-limitations))
- **Artifact comparison** — diff two extracted artifacts side by side

### AI-Powered Investigation
- Natural-language Q&A against ingested evidence using a **locally running LLM** (Ollama)
- **RAG pipeline**: evidence chunks → Qdrant vector embeddings (384-dim) → semantic search → LLM context injection
- Confidence scores and source citations for every answer
- Persistent query history per case with flag and delete controls
- Adjustable response verbosity and model selection

### Entity Intelligence
- Automatic named-entity recognition (NER) via **spaCy** `en_core_web_lg`
- Entity types: persons, organisations, locations, IP addresses, email addresses, phone numbers, dates
- Frequency tracking, alias grouping (`rapidfuzz`), and manual flagging
- **Interactive force-directed graph** (NetworkX + canvas rendering)
- Cross-case entity search — find the same name or IP across all cases

### Entity Profiles
- One-click AI-generated intelligence profiles for any entity
- Profile includes: background summary, connections, risk indicators, confidence level
- Generated entirely from evidence, no external lookups

### Credential Discovery
- Scans extracted evidence for **passwords, API keys, tokens, and secrets**
- Triage workflow: confirm or mark **false positive**
- Findings surface in a dedicated page and feed the audit trail

### Timeline Reconstruction
- Chronological view of all file system timestamps extracted from evidence
- Created / Modified / Accessed filters
- Sortable and filterable table view

### Anomaly Detection
- Statistical **Shannon entropy** analysis — flags files with unusually high randomness (encrypted/compressed/obfuscated)
- Timestamp anomaly detection — files with modification dates older than creation dates
- Behavioural pattern flagging

### Geographic Intelligence
- EXIF GPS extraction from photographs
- IP address geolocation (offline database)
- Interactive map with clustered pin markers

### Keyword Watchlist
- Define keywords per case (suspect names, IPs, financial terms, handles)
- Automatic hit counting during ingestion and re-indexing
- Category tagging for watchlist entries

### Reports
- One-click generation of structured investigation reports (PDF via ReportLab)
- Report types: Case Summary, Full Investigation, Evidence Inventory, Entity Analysis, Timeline Report
- Persistent report storage with download and delete

### Audit Trail & Activity Log
- Immutable audit log per case — every action recorded (upload, query, report, login)
- Severity levels (`info` / `warning` / `error`) on audit entries
- Global cross-case activity feed on the dashboard
- Full-text search and filtering by action type, user, date range
- CSV export of activity log

### Hardware & Device Awareness
- **Live, non-static auto-detection of the host machine** — CPU model, physical/logical cores and clock; **every** GPU with VRAM and shared-vs-dedicated flag; **every** mounted volume (including removable USB) with fstype, free/total space and an `is_evidence_store` marker; network adapters with MAC/IP/up/virtual state; chassis manufacturer/model/BIOS; battery and laptop detection; swap/pagefile; OS
- Detection is **re-walked** whenever the device fingerprint changes (partition list or NIC list), so a hot-plugged evidence drive or eGPU appears immediately
- Manual **Rescan** button forces a full re-walk on demand
- Panel is shown on both the **Evidence** and **Queue** pages from one shared component
- **Gated by a per-user preference** (`System Health → Show system resources`); when off, the component renders nothing and stops polling

### User Management & Security
- JWT-based authentication with refresh
- Role hierarchy: **Admin → Investigator → Analyst → Viewer**
- **Two-factor authentication (TOTP)** with QR-code enrolment
- Account lockout after 5 consecutive failed login attempts (15-minute cooldown)
- Rate limiting on auth endpoints (slowapi)
- Admin user management: role changes, account activation/deactivation, password reset
- Self-service password change
- **Per-user UI preferences** (persisted server-side, cached locally to avoid UI flash)
- **System health page** — database, Ollama, queue and storage diagnostics
- Dark / light theming, global search, React Error Boundaries

### Developer Experience
- `setup.sh` (macOS + Linux) and `setup_windows.bat` — one-command environment setup
- **Air-gap install kit** in `vendor/` — Python wheels and the spaCy model tarball, so setup needs no network
- `migrate_all.py` — runs every `migrate_*.py` script in order; idempotent
- `seed_demo.py` — realistic demo data seeder for presentations
- `clear_demo_cases.py` — removes seeded demo data
- Hot-reload in development for both frontend (Vite) and backend (uvicorn `--reload`)
- Structured logging to console and audit DB

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│            Intelligent Digital Forensic AI Assistant     │
│                                                          │
│  ┌───────────┐       ┌─────────────────────────────┐    │
│  │  React    │──────▶│      FastAPI Backend         │    │
│  │ Frontend  │◀──────│                             │    │
│  │  (Vite)   │       │  ┌───────────────────────┐  │    │
│  │  :3000    │       │  │     RAG Pipeline       │  │    │
│  └───────────┘       │  │  ┌─────────────────┐   │  │    │
│                      │  │  │    Qdrant        │   │  │    │
│  ┌───────────┐       │  │  │  Vector DB       │   │  │    │
│  │  Ollama   │◀──────│  │  └─────────────────┘   │  │    │
│  │ LLM Local │──────▶│  │  ┌─────────────────┐   │  │    │
│  └───────────┘       │  │  │   NetworkX       │   │  │    │
│                      │  │  │   Graph Engine   │   │  │    │
│  ┌───────────┐       │  │  └─────────────────┘   │  │    │
│  │  SQLite   │◀──────│  └───────────────────────┘  │    │
│  │  14 tables│       │                             │    │
│  └───────────┘       │  ┌───────────────────────┐  │    │
│                      │  │  Ingestion Pipeline    │  │    │
│  ┌───────────┐       │  │  (Background Worker)  │  │    │
│  │ pyewf +   │──────▶│  └───────────────────────┘  │    │
│  │  pytsk3   │       │                             │    │
│  └───────────┘       └─────────────────────────────┘    │
│                                                          │
│  ┌───────────────────────────────────────────────────┐   │
│  │  hardware_probe — live CPU/GPU/volume/NIC/chassis │   │
│  └───────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
Evidence File Upload
        │
        ▼
  Ingestion Queue  ──▶  Background Worker  ──▶  WebSocket progress
        │
        ├──▶  Text Extraction (pdfminer / pytesseract / whisper / pytsk3)
        │
        ├──▶  Metadata Extraction (EXIF / file timestamps / SHA-256)
        │
        ├──▶  NER (spaCy)  ──▶  Entity Table (SQLite)
        │
        ├──▶  Credential Scanning  ──▶  Findings Table
        │
        ├──▶  Entropy + Timestamp Analysis  ──▶  Anomalies
        │
        ├──▶  Chunking + Embedding (Ollama embeddings, 384-dim)  ──▶  Qdrant
        │
        └──▶  Watchlist matching  ──▶  Hit counter update

Investigator Query
        │
        ▼
  Semantic Search (Qdrant)  ──▶  Top-K Chunks Retrieved
        │
        ▼
  Context Assembly + Prompt
        │
        ▼
  Ollama LLM (llama3.2:3b or similar)
        │
        ▼
  Answer + Citations  ──▶  Query Log (SQLite)
```

---

## Tech Stack

### Backend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| API Framework | **FastAPI 0.110** | REST API, async request handling, auto OpenAPI docs |
| ORM | **SQLAlchemy 2.0** | Database models and query builder |
| Database | **SQLite** (14 tables) | Persistent storage for cases, users, evidence, audit logs |
| Vector DB | **Qdrant 1.9** (embedded) | Semantic search over chunked evidence text, per-case storage |
| Embeddings | **Ollama** embedding model (384-dim) | Text-to-vector encoding — no PyTorch in the dependency set |
| LLM Runtime | **Ollama** | Local LLM serving (llama3.2:3b recommended) |
| NLP | **spaCy 3.7** (`en_core_web_lg`) | Named entity recognition |
| Graph Engine | **NetworkX 3.3** | Entity relationship graph construction |
| Auth | **python-jose** + **bcrypt** | JWT tokens + password hashing |
| 2FA | **pyotp** + **qrcode** | TOTP enrolment and QR rendering |
| Rate Limiting | **slowapi** | Brute-force protection on auth endpoints |
| System Metrics | **psutil** | CPU/RAM/disk/network sampling and live hardware probe |
| PDF Parsing | **pdfminer.six** | Text extraction from PDF evidence |
| OCR | **pytesseract** | Text extraction from image evidence |
| Audio | **openai-whisper** + `ffmpeg-python` | Transcription of audio/video evidence |
| Office Docs | **python-docx**, **openpyxl**, **python-pptx** | Word, Excel, PowerPoint parsing |
| Email | **extract-msg** | Outlook MSG file parsing |
| Registry | **python-registry** | Windows registry hive parsing |
| Disk Images | **pyewf** + **pytsk3** | Forensic E01 / raw image traversal |
| EXIF | **exifread** | GPS and metadata from photographs |
| Reports | **ReportLab 4.2** | PDF report generation |
| Fuzzy Match | **rapidfuzz** | Entity alias and deduplication matching |
| Realtime | **websockets** | Live ingestion progress and queue updates |
| Server | **uvicorn 0.29** | ASGI server |

> **Note on PyTorch:** `torch` and `sentence-transformers` are **deliberately absent** from `requirements.txt`. They were removed to stop out-of-memory crashes on modest forensic hardware, and embeddings are served by Ollama instead. Do not re-add them without reading `AGENTS.md` §6 (B4).

### Frontend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | **React 18** | Component-based UI |
| Build Tool | **Vite 5** | Dev server (port **3000**) and bundler |
| Routing | **React Router v6** | Client-side navigation |
| HTTP Client | **axios** | API communication |
| Styling | **Tailwind CSS 3** + CSS custom properties | Utility classes + design-token system (dark/light) |
| Icons | **lucide-react** | Consistent icon set |
| Date Formatting | **date-fns** | Human-readable timestamps |
| Toasts | **react-hot-toast** | Non-blocking user notifications |
| Charts / Graphs | **NetworkX data** + canvas force layout | Entity graph rendering |
| State | React Context + custom hooks | Auth, theme, preferences, WebSocket, notifications |

---

## Prerequisites

| Requirement | Min Version | Windows | macOS | Linux (Ubuntu/Debian) |
|---|---|---|---|---|
| Python | 3.10+ | from python.org | `brew install python3` | `sudo apt install python3 python3-pip python3-venv` |
| Node.js | 18+ | from nodejs.org | `brew install node` | `sudo apt install nodejs npm` |
| Ollama | latest | [ollama.com/download](https://ollama.com) | `brew install ollama` | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Tesseract OCR | 5.0+ | [UB Mannheim build](https://github.com/UB-Mannheim/tesseract/wiki) | `brew install tesseract` | `sudo apt install tesseract-ocr` |
| ffmpeg | 6.0+ | [gyan.dev](https://www.gyan.dev/ffmpeg/builds/) | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| Sleuth Kit + libewf | 4.12+ | bundled wheels in `vendor/` | `brew install sleuthkit libewf` | `sudo apt install libewf-dev ewf-tools sleuthkit` |
| Build tools | — | Visual Studio Build Tools | Xcode CLI tools | `sudo apt install build-essential libssl-dev libffi-dev python3-dev` |

> **pyewf and pytsk3 are optional.** The system degrades gracefully and supports all other file types without them.

### Air-gapped installation

`vendor/` contains pre-downloaded Python wheels and the `en_core_web_lg` spaCy model tarball. Both setup scripts use it when present, so a machine with no internet access can still be provisioned:

```bash
# Linux / macOS
./setup.sh              # installs from vendor/ when the network is unavailable

# Windows
setup_windows.bat
```

### GPU notes

Ollama uses the GPU automatically when a supported one is present. Recommended models by VRAM:

| VRAM | Suggested model |
|---|---|
| 4 GB (e.g. GTX 1050 Ti) | `phi4-mini` |
| 8 GB | `llama3.2:3b` *(default)* |
| 12 GB+ | `qwen2.5:7b` |

Set the model in `.env`:

```env
OLLAMA_MODEL=phi4-mini
```

On Linux with NVIDIA, verify the driver first:

```bash
nvidia-smi   # driver must be present and recent
```

---

## Quick Setup

### Windows

```cmd
setup_windows.bat
start_windows.bat
```

### macOS / Linux

```bash
chmod +x setup.sh
./setup.sh
./start.sh
```

> On Linux, if you hit a permission error, run `chmod +x setup.sh` first.

The setup script will:
- Check for Python 3 and Node.js
- Create a Python virtual environment
- Install all Python dependencies (from `vendor/` when offline)
- Install the spaCy NLP model (`en_core_web_lg`)
- Create required data directories
- Run all database migrations via `backend/migrate_all.py`
- Install frontend packages

---

## Manual Installation

### Step 1 — Python environment

```bash
# Linux / macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate

pip install --upgrade pip setuptools wheel
pip install -r requirements.txt
python -m spacy download en_core_web_lg
```

### Step 2 — Database initialisation

```bash
# Linux / macOS
PYTHONPATH=. python backend/migrate_all.py

# Windows
PYTHONPATH=. venv\Scripts\python.exe backend\migrate_all.py
```

`migrate_all.py` is the master script and is safe to run repeatedly.

### Step 3 — Data directories

```bash
mkdir -p data/cases
```

Per-case Qdrant stores and evidence folders are created automatically under `data/cases/<case_id>/`.

### Step 4 — Frontend

```bash
cd frontend
npm install        # or: yarn install
cd ..
```

### Step 5 — Ollama model

```bash
ollama serve          # terminal 1
ollama pull llama3.2:3b   # terminal 2
```

---

## Running the Application

You need **three terminals** running simultaneously.

### Terminal 1 — Ollama (LLM runtime)

```bash
ollama serve
```

> Skip if Ollama already runs as a system service.

### Terminal 2 — Backend (FastAPI)

```bash
# Linux / macOS
source venv/bin/activate
PYTHONPATH=. uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000

# Windows
call venv\Scripts\activate.bat
set PYTHONPATH=.
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

Backend: **http://localhost:8000**

### Terminal 3 — Frontend (React + Vite)

```bash
cd frontend
npm run dev          # or: yarn dev
```

Frontend: **http://localhost:3000**

> The dev server port is pinned to **3000** in `frontend/vite.config.js`, which proxies `/api` to `http://localhost:8000`. If you see `5173`, that is Vite's automatic port fallback after 3000 was already taken — free the port rather than following the fallback link.

---

## First-Time Setup

1. Open **http://localhost:3000**
2. Click **Register** — the very first account created is automatically assigned the **Admin** role
3. Fill in your name, email, username, and password
4. Log in and you will land on the **Dashboard**
5. Create your first case via the **Cases** screen
6. Upload evidence files in the **Evidence** tab of the case
7. Optional but recommended: enable **2FA** from your profile, and turn on **Show system resources** in **Settings** to see live hardware detection on the Evidence and Queue pages

> **Important:** Secure your Admin credentials. Subsequent registrations default to the **Analyst** role and must be manually promoted by an Admin via **User Management**.

---

## Demo Data

```bash
# Linux / macOS
PYTHONPATH=. python backend/seed_demo.py

# Windows
PYTHONPATH=. venv\Scripts\python.exe backend\seed_demo.py
```

This creates:

| Account | Password | Role |
|---------|----------|------|
| `admin` | `Admin@IDF2025` | Admin |
| `det_markov` | `Markov@2025` | Investigator |
| `analyst_chen` | `Chen@2025` | Analyst |

And seeds **3 cases** — *Operation Phantom Trace* (cybercrime), *Vertex Pharma Leak* (corporate espionage), *Havenport Missing Person* — with entities, notes, watchlist keywords, and audit history.

> The seeder is **idempotent** — safe to run multiple times. To remove seeded data: `PYTHONPATH=. python backend/clear_demo_cases.py`.

---

## API Documentation

FastAPI generates interactive API documentation automatically.

| Interface | URL |
|-----------|-----|
| Swagger UI (interactive) | http://localhost:8000/docs |
| ReDoc (readable) | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/openapi.json |
| Health check | http://localhost:8000/api/status |

### Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Authenticate, receive JWT |
| `POST` | `/api/auth/login-2fa` | Authenticate with a TOTP code |
| `POST` | `/api/auth/register` | Register a new user account |
| `GET` | `/api/auth/me` | Current user profile |
| `POST` | `/api/auth/change-password` | Self-service password change |
| `POST` | `/api/auth/2fa/setup` · `/verify` · `/disable` | TOTP enrolment lifecycle |
| `GET`/`PUT` | `/api/auth/preferences` | Read/update per-user UI preferences |
| `PATCH` | `/api/auth/users/{id}/role` · `/activate` · `/deactivate` · `/reset-password` | Admin user management |
| `GET`/`POST` | `/api/cases` | List / create cases |
| `GET`/`PATCH`/`DELETE` | `/api/cases/{case_id}` | Read, update, delete a case |
| `POST` | `/api/cases/import` · `GET /api/cases/{case_id}/export` | Case portability |
| `POST` | `/api/cases/{case_id}/summary` | AI case summary |
| `POST` | `/api/cases/{case_id}/contradictions` | Contradiction detection |
| `GET`/`PATCH`/`DELETE` | `/api/cases/{case_id}/access` | Case access control grants |
| `POST` | `/api/cases/{case_id}/evidence/upload` | Upload evidence file |
| `GET` | `/api/cases/{case_id}/evidence` | List evidence for a case |
| `POST` | `/api/cases/{case_id}/evidence/{evidence_id}/verify` | Re-verify SHA-256 chain of custody |
| `GET` | `/api/cases/{case_id}/evidence/timeline` | File activity timeline |
| `GET` | `/api/cases/{case_id}/evidence/anomalies` | Entropy / timestamp anomalies |
| `POST` | `/api/cases/{case_id}/evidence/artifacts/compare` | Compare two artifacts |
| `GET` | `/api/cases/{case_id}/evidence/storage-stats` | Storage usage |
| `GET`/`POST`/`PATCH` | `/api/cases/{case_id}/credentials` | Credential findings, confirm / false-positive |
| `GET` | `/api/cases/{case_id}/entities/graph` | Entity relationship graph |
| `POST` | `/api/cases/{case_id}/entities/{id}/profile` | Generate entity intelligence profile |
| `GET` | `/api/cases/{case_id}/entities/{id}/profile` | Read entity profile |
| `POST` | `/api/cases/{case_id}/queries/ask` | Submit a natural-language question |
| `GET`/`PATCH`/`DELETE` | `/api/cases/{case_id}/queries` | Query history, flag, delete |
| `GET`/`POST`/`DELETE` | `/api/cases/{case_id}/notes` | Investigation notes |
| `GET` | `/api/cases/{case_id}/audit` | Per-case audit log |
| `GET`/`POST`/`DELETE` | `/api/cases/{case_id}/reports` | Generate, list, delete reports |
| `GET` | `/api/cases/{case_id}/reports/{id}/download` | Download report PDF |
| `GET`/`POST`/`DELETE` | `/api/cases/{case_id}/watchlist` | Keyword watchlist and hits |
| `GET`/`POST` | `/api/queue/list` · `/api/queue/add` | Ingestion queue status / submission |
| `POST` | `/api/queue/add-bulk` · `/estimate` | Bulk submission and duration estimate |
| `POST` | `/api/queue/{job_id}/start` · `/stop` · `/cancel` · `/force-start` | Job control |
| `GET` | `/api/queue/system-info` | **Live hardware + resource info** |
| `POST` | `/api/queue/system-info/rescan` | Force a full hardware re-scan |
| `GET` | `/api/activity` | Global cross-case activity feed |
| `GET` | `/api/status` | System health (DB + Ollama) |
| `WS` | `/ws/queue` | Live ingestion progress stream |

All endpoints except `/api/auth/login`, `/api/auth/register`, `/api/auth/login-2fa` and `/api/status` require a **Bearer token** in the `Authorization` header. The login endpoint accepts **OAuth2 form-encoded** credentials, not JSON.

---

## Project Structure

```
Intelligent-Digital-Forensic-AI-Assistant/
│
├── setup.sh                    # Automated setup (macOS + Linux)
├── setup_windows.bat           # Automated setup (Windows)
├── start.sh / start.bat        # Launch ollama + backend + frontend
├── start_windows.bat
├── requirements.txt            # Python dependencies (no torch)
├── vendor/                     # Air-gap kit: wheels + spaCy model
├── .env                        # Environment configuration
│
├── backend/
│   ├── main.py                 # FastAPI app, router registration, middleware
│   ├── models.py               # SQLAlchemy ORM models (14 tables)
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── database.py             # DB engine + session factory
│   ├── auth.py                 # JWT issue/verify, bcrypt hashing
│   ├── dependencies.py         # Shared FastAPI dependencies
│   ├── ingestion.py            # Ingestion dispatch + forensic pipeline driver
│   ├── seed_demo.py            # Idempotent demo data seeder
│   ├── clear_demo_cases.py     # Demo data cleanup
│   ├── migrate_all.py          # Master migration runner
│   │
│   ├── routers/                # 12 routers
│   │   ├── auth_router.py      # Auth, 2FA, users, preferences
│   │   ├── cases.py            # Case CRUD, import/export, summary, contradictions
│   │   ├── case_access.py      # Per-case access grants
│   │   ├── evidence.py         # Upload, artifacts, timeline, anomalies, compare
│   │   ├── credentials.py      # Credential findings triage
│   │   ├── entities.py         # NER entities, graph, AI profiles
│   │   ├── queries.py          # RAG ask, history, flagging
│   │   ├── notes.py            # Investigation notes
│   │   ├── audit.py            # Per-case audit log
│   │   ├── reports.py          # PDF report generation
│   │   ├── watchlist.py        # Keyword watchlist + hits
│   │   └── queue_router.py     # Job queue, WebSocket, system-info
│   │
│   ├── modules/                # 18 modules
│   │   ├── forensic_ingestion.py  # pyewf/pytsk3 walk + per-file extraction
│   │   ├── rag_engine.py          # Retrieval + prompt + citation processing
│   │   ├── vector_store.py        # Qdrant wrapper (384-dim)
│   │   ├── ollama_client.py       # Ollama HTTP client (LLM + embeddings)
│   │   ├── graph_builder.py       # NetworkX entity graph
│   │   ├── hardware_probe.py      # Live CPU/GPU/volume/NIC/chassis detection
│   │   ├── resource_governor.py   # RAM/CPU throttling for the worker
│   │   ├── job_worker.py          # Background ingestion worker
│   │   ├── text_parser.py         # Text extraction dispatch
│   │   ├── media_extractor.py     # Audio/video/email/office extraction
│   │   ├── registry_parser.py     # Windows registry hive parsing
│   │   ├── credential_scanner.py  # Password/secret finding
│   │   ├── entropy_analyzer.py    # Shannon entropy
│   │   ├── anomaly_detector.py    # Anomaly rules
│   │   ├── report_generator.py    # ReportLab PDF builder
│   │   ├── time_estimator.py      # Job duration estimates
│   │   ├── file_store.py          # Evidence file storage
│   │   └── audit_helper.py        # Audit entry writer + severity map
│   │
│   └── migrate_*.py            # 16 additive migration scripts
│
├── frontend/
│   ├── index.html
│   ├── vite.config.js          # port 3000, /api → :8000
│   ├── tailwind.config.js
│   ├── package.json
│   │
│   └── src/
│       ├── App.jsx             # Routing + AppLayout (sidebar, statusbar, main)
│       ├── main.jsx            # React entry point
│       ├── index.css           # Design tokens (dark/light custom properties)
│       │
│       ├── api/client.js       # Axios instance + all API functions
│       │
│       ├── context/
│       │   ├── AuthContext.jsx
│       │   └── ThemeContext.jsx
│       │
│       ├── hooks/
│       │   ├── usePreferences.js    # Per-user UI prefs (localStorage cache)
│       │   ├── useWebSocket.js      # Live queue progress
│       │   ├── useNotifications.jsx
│       │   ├── useTilt.js
│       │   └── useCountUp.js
│       │
│       ├── components/
│       │   ├── Sidebar.jsx
│       │   ├── StatusBar.jsx
│       │   ├── PageLayout.jsx
│       │   ├── AppBackground.jsx
│       │   ├── ResourceMonitor.jsx  # Shared live hardware panel (Evidence + Queue)
│       │   ├── FileViewer.jsx
│       │   ├── GlobalSearch.jsx
│       │   ├── ErrorBoundary.jsx
│       │   ├── ProtectedRoute.jsx
│       │   └── cards/ · Badge · ConfirmDialog
│       │
│       └── pages/             # 29 route components
│           ├── LoginPage · RegisterPage · TwoFactorPage
│           ├── DashboardPage · ActivityPage
│           ├── CasesPage · CaseDetailPage · CaseSettingsPage
│           ├── EvidencePage · ArtifactsPage · ComparisonPage
│           ├── InvestigatePage · ContradictionsPage · SummaryPage
│           ├── EntityMapPage · ProfilePage
│           ├── TimelinePage · AnomalyPage · GeoMapPage
│           ├── WatchlistPage · CredentialsPage · NotesPage
│           ├── AuditPage · ReportsPage · QueuePage
│           ├── SystemHealthPage · SettingsPage
│           └── AdminUsersPage · ChangePasswordPage
│
├── data/
│   ├── forensic.db             # SQLite database
│   └── cases/<case_id>/
│       ├── evidence/           # Uploaded evidence + extracted artifacts
│       └── qdrant/             # Per-case vector store
│
└── AGENTS.md                   # Agent-facing progress, known bugs, conventions
```

---

## Known Limitations

| Limitation | Detail |
|------------|--------|
| **Truncated disk images** | A raw/EWF image shorter than the volume it declares cannot be walked — The Sleuth Kit needs the `$MFT`, which lives past EOF. The app now **detects this before starting** and reports the real TSK diagnostic instead of silently reporting "0 artifacts"; evidence in that state is marked `Failed`, not `Indexed`. Partial recovery is still attempted. The image itself must be re-acquired. |
| **Stale import in `vector_store.py`** | `requirements.txt` intentionally omits `torch`/`sentence-transformers`, but `backend/modules/vector_store.py` still contains a top-level import of them. On a machine where those packages are absent, this raises `ImportError` at startup. It is masked on machines that happen to have them installed. Tracked in `AGENTS.md` §2 / B6. |
| **Slow path when Ollama is offline** | A query issued while Ollama is not running waits for the generation timeout (~25 s) before reporting the problem. `GET /api/status` will tell you Ollama's state first. |
| **Local LLM quality** | Response accuracy is bounded by the capability of the selected Ollama model. Smaller models (3B parameters) may hallucinate or miss nuanced connections. |
| **Windows commit limit** | If Ollama fails with `unable to allocate CUDA0 buffer` / `exit status 2`, the cause is usually a disabled or undersized **pagefile**, not VRAM. Enable *Automatic managed pagefile size* and reboot. |
| **Single-node deployment** | The system is designed for a single investigator workstation. It is not load-balanced or horizontally scalable. |
| **SQLite concurrency** | SQLite does not support high write concurrency. Heavy parallel ingestion jobs may queue. Suitable for teams of 1–5 investigators. |
| **Disk image support** | `pyewf` and `pytsk3` require native C libraries. On macOS, installation can fail on certain configurations. On Linux, install `libewf-dev ewf-tools` first. Fallback to file-based evidence is automatic. |
| **macOS GPU reporting** | The hardware probe reports no GPU on macOS rather than guessing. NVIDIA/AMD/Apple Silicon details come from Ollama and the System Information panel. |
| **No email notifications** | Password reset and workflow notifications rely on Admin action rather than SMTP email, by design (air-gapped deployment). |
| **Whisper speed** | Audio transcription via Whisper is slow without a CUDA-capable GPU. Large audio files may take several minutes to ingest. |
| **Map data** | The geographic map requires a Leaflet tile server or internet access for map tiles. In a fully air-gapped environment, a local tile server must be configured. |
| **spaCy NER accuracy** | NER quality depends on the language model. Highly technical forensic jargon, code, or non-English content may not be correctly classified. |

---

## Troubleshooting

### Ollama reports `unable to allocate CUDA0 buffer` or exits with status 2

This is a **Windows memory-commit** problem, not a GPU problem. Check whether the GPU actually has free VRAM, then check the pagefile:

```powershell
# GPU memory
nvidia-smi

# Pagefile state — AutomaticManagedPagefile should be True
Get-CimInstance Win32_ComputerSystem | Select-Object AutomaticManagedPagefile
```

If it is `False`, enable the automatic pagefile and reboot (requires an elevated prompt):

```powershell
wmic computersystem set AutomaticManagedPagefile=True
```

Also close memory-heavy applications — every open browser tab counts.

---

### Ollama not detected / queries time out

```bash
curl http://localhost:11434/api/tags        # Linux / macOS
# or open http://localhost:8000/api/status for the app's own health view
```

Start `ollama serve` first, then retry. Generation is unavailable until the service responds.

---

### Frontend shows a blank page or 404s on `/api`

The dev server must be on **port 3000** and proxying to **8000**. Confirm the backend is running on 8000 and that you opened `http://localhost:3000`, not a stale `5173` URL.

---

### Ollama using CPU instead of GPU (Linux)

```bash
nvidia-smi  # verify driver is present and recent
sudo apt install nvidia-driver-570
sudo reboot
```

Then restart `ollama serve` and confirm the GPU is visible again.

---

### pyewf / pytsk3 not installing

Disk image support needs libewf and The Sleuth Kit. If they fail to build, **all other file types** (PDF, DOCX, audio, images) still work normally.

```bash
# Linux
sudo apt install libewf-dev ewf-tools sleuthkit

# macOS
brew install libewf sleuthkit
```

On Windows, use the prebuilt wheels in `vendor/`.

---

### A disk image reports "0 artifacts"

Almost always a **truncated image**. Compare the file size on disk against the volume size declared in its partition table — if the file is smaller, the copy is incomplete and must be re-acquired. See [Known Limitations](#known-limitations).

---

### Port already in use

```bash
# Linux / macOS
lsof -i :8000
kill -9 <PID>
```

```powershell
# Windows
Get-NetTCPConnection -LocalPort 8000 | Select-Object OwningProcess
Stop-Process -Id <PID>
```

---

### spaCy model missing

```
OSError: [E050] Can't find model 'en_core_web_lg'
```

```bash
python -m spacy download en_core_web_lg
```

For an air-gapped machine, install from `vendor/`.

---

### Migrations fail or tables are missing

Run the master script, which executes every migration in order:

```bash
PYTHONPATH=. python backend/migrate_all.py
```

It is idempotent — run it as many times as needed.

---

### Node.js version too old (Linux)

```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # should print v18+
```

---

## Future Work

- **Multi-language NER** — integrate multilingual spaCy models to support non-English evidence
- **Collaborative investigation** — real-time case sharing between multiple simultaneous investigators
- **YARA rule integration** — scan artifacts against community YARA rule sets for malware signatures
- **Timeline visualisation** — interactive Gantt-style timeline renderer with zoom and filtering
- **Automated anomaly scoring** — ML-based behavioural model trained on known-good file system patterns
- **Docker deployment** — containerised deployment with `docker-compose` for reproducible environments
- **Qdrant cloud mode** — option to connect to a remote Qdrant cluster for large-scale evidence repositories
- **Larger LLM support** — quantised 13B/70B model support for higher-quality analysis
- **Chain-of-custody PDF** — cryptographically signed chain-of-custody documents for court admissibility
- **Stix/TAXII export** — export entity and relationship data in STIX format for threat intelligence platforms

---

## Academic Context

**Course:** Final Year / Capstone Project
**Domain:** Cybersecurity · Artificial Intelligence · Human–Computer Interaction
**Project Type:** Full-stack Software Engineering — Research and Implementation

### Motivation

Digital forensics investigations traditionally require investigators to manually sift through large volumes of files, run separate specialised tools for each task, and mentally synthesise disparate data sources. This project explores whether a unified, AI-augmented platform can reduce investigative time and cognitive load — particularly for analysts who may not be forensics specialists.

### Research Questions

1. Can a locally-deployed RAG pipeline provide forensically useful answers from unstructured evidence files?
2. How can entity extraction and graph visualisation assist in building investigative hypotheses?
3. What user experience patterns best support non-linear investigation workflows?

### Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Fully local AI (Ollama)** | Forensic data is sensitive. Sending evidence to cloud APIs would create legal, evidentiary, and privacy risks. |
| **SQLite over PostgreSQL** | Simplifies deployment — no external database service required. Appropriate for single-workstation scale. |
| **Qdrant over ChromaDB** | Qdrant supports named collections, persistent on-disk storage, and is production-grade for vector search. |
| **React + FastAPI** | Separation of concerns between presentation and computation; FastAPI's async capabilities suit the long-running ingestion pipeline. |
| **Background worker** | Evidence ingestion can take minutes. A background queue prevents API timeouts and allows real-time progress reporting over WebSockets. |
| **Role-based access** | Multi-user investigations require controlled access. The four-tier role model mirrors real-world forensics team structures (Admin / Investigator / Analyst / Viewer). |
| **No PyTorch in the dependency set** | Local embedding models exhausted RAM on modest forensic hardware; Ollama serves embeddings instead, keeping the air-gap kit installable. |
| **Live hardware detection over a static spec** | A forensics workstation gains and loses devices between cases, so hardware and attached volumes are re-probed whenever the device fingerprint changes. |

### Academic References

> *(Replace with your actual bibliography as required by your institution's citation style.)*

- Lewis, P., et al. (2020). *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS 2020.
- Garfinkel, S. L. (2010). *Digital forensics research: The next 10 years*. Digital Investigation, 7, S64–S73.
- Honnibal, M., & Montani, I. (2017). *spaCy 2: Natural language understanding with Bloom embeddings, convolutional neural networks and incremental parsing*.
- Reimers, N., & Gurevych, I. (2019). *Sentence-BERT: Sentence embeddings using siamese BERT-networks*. EMNLP 2019.
- NIST. (2006). *Guide to Integrating Forensic Techniques into Incident Response* (SP 800-86). National Institute of Standards and Technology.

---

## Licence

This project was created for academic purposes. All code is original work unless otherwise cited. Not intended for production forensic use without further validation.

---

*Built for a final year project — pushing the boundaries of what a student project can look like.*

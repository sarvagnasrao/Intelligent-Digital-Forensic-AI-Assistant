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
14. [Future Work](#future-work)
15. [Academic Context](#academic-context)

---

## Project Overview

**Intelligent Digital Forensic AI Assistant** is a full-stack digital forensics workstation that enables investigators to upload evidence files, automatically extract text and metadata, query that evidence using a local large language model (LLM), and reconstruct timelines and entity relationships — all without sending any data to external servers.

The system implements a **Retrieval-Augmented Generation (RAG)** pipeline: evidence is chunked, embedded into a vector database (Qdrant), and retrieved as context for a locally-running Ollama LLM. Investigators interact with the evidence through a natural-language chat interface, while the backend simultaneously extracts named entities, builds relationship graphs, detects anomalies, and generates structured forensic reports.

This project was developed as a semester-long final project exploring the intersection of AI, cybersecurity, and human-computer interaction. The application is designed to be deployable on a standalone machine in an air-gapped forensics lab — no internet connection is required after initial setup.

---

## Features

### Case Management
- Create, manage, and archive investigation cases with metadata (case number, status, priority, tags)
- Role-based case access — cases are scoped to authorised investigators
- Case detail overview with live statistics (evidence count, artifact count, entity count)

### Evidence Ingestion
- Drag-and-drop upload for multiple file types: **disk images** (E01/DD), **PDF**, **DOCX**, **PPTX**, **XLSX**, **images** (JPEG, PNG, TIFF), **audio** (MP3, WAV), **email** (MSG/EML), **plain text**
- Background ingestion queue with real-time progress tracking and CPU throttle controls
- Automatic text extraction via: `pdfminer`, `python-docx`, `pytesseract` (OCR), `openai-whisper` (audio transcription), `extract-msg` (email parsing)
- File integrity verification via SHA-256 hash (chain of custody)
- Forensic disk image traversal using `pyewf` + `pytsk3` (The Sleuth Kit)

### AI-Powered Investigation
- Natural-language Q&A against ingested evidence using a **locally running LLM** (Ollama)
- **RAG pipeline**: evidence chunks → Qdrant vector embeddings → semantic search → LLM context injection
- Confidence scores and source citations for every answer
- Persistent query history per case with flag and delete controls
- Adjustable response verbosity and model selection

### Entity Intelligence
- Automatic named-entity recognition (NER) via **spaCy** `en_core_web_lg`
- Entity types: persons, organisations, locations, IP addresses, email addresses, phone numbers, dates
- Frequency tracking, alias grouping, and manual flagging
- **Interactive force-directed graph** (NetworkX + D3-style canvas rendering)
- Cross-case entity search — find the same name or IP across all cases

### Entity Profiles
- One-click AI-generated intelligence profiles for any entity
- Profile includes: background summary, connections, risk indicators, confidence level
- Generated entirely from evidence, no external lookups

### Timeline Reconstruction
- Chronological view of all file system timestamps extracted from evidence
- Created / Modified / Accessed filters
- Sortable and filterable table view

### Anomaly Detection
- Statistical entropy analysis — flags files with unusually high randomness (encrypted/compressed/obfuscated)
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
- Global cross-case activity feed on the dashboard
- Full-text search and filtering by action type, user, date range
- CSV export of activity log

### User Management & Security
- JWT-based authentication with refresh
- Role hierarchy: **Admin → Investigator → Analyst → Viewer**
- Account lockout after 5 consecutive failed login attempts (15-minute cooldown)
- Rate limiting on auth endpoints (slowapi)
- Admin user management: role changes, account activation/deactivation, password reset
- Self-service password change
- React Error Boundaries — graceful recovery UI on component failures

### Developer Experience
- `setup.sh` — one-command automated environment setup (auto-detects macOS and Linux)
- `seed_demo.py` — realistic demo data seeder for presentations
- Hot-reload in development for both frontend (Vite) and backend (uvicorn `--reload`)
- Structured logging to console and audit DB

---

## System Architecture

```
┌─────────────────────────────────────────────────────────┐
│                 IDF AI Assistant System                 │
│                                                          │
│  ┌───────────┐       ┌─────────────────────────────┐    │
│  │  React    │──────▶│      FastAPI Backend         │    │
│  │ Frontend  │◀──────│                             │    │
│  │  (Vite)   │       │  ┌───────────────────────┐  │    │
│  └───────────┘       │  │     RAG Pipeline       │  │    │
│                      │  │  ┌─────────────────┐   │  │    │
│  ┌───────────┐       │  │  │    Qdrant        │   │  │    │
│  │  Ollama   │◀──────│  │  │  Vector DB       │   │  │    │
│  │ LLM Local │──────▶│  │  └─────────────────┘   │  │    │
│  └───────────┘       │  │  ┌─────────────────┐   │  │    │
│                      │  │  │   NetworkX       │   │  │    │
│  ┌───────────┐       │  │  │   Graph Engine   │   │  │    │
│  │  SQLite   │◀──────│  │  └─────────────────┘   │  │    │
│  │ Database  │       │  └───────────────────────┘  │    │
│  └───────────┘       │                             │    │
│                      │  ┌───────────────────────┐  │    │
│  ┌───────────┐       │  │  Ingestion Pipeline    │  │    │
│  │ pyewf +   │──────▶│  │  (Background Worker)  │  │    │
│  │  pytsk3   │       │  └───────────────────────┘  │    │
│  └───────────┘       └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────┘
```

### Data Flow

```
Evidence File Upload
        │
        ▼
  Ingestion Queue  ──▶  Background Worker
        │
        ├──▶  Text Extraction (pdfminer / pytesseract / whisper / pytsk3)
        │
        ├──▶  Metadata Extraction (EXIF / file timestamps / hashes)
        │
        ├──▶  NER (spaCy)  ──▶  Entity Table (SQLite)
        │
        ├──▶  Chunking + Embedding (sentence-transformers)  ──▶  Qdrant
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
| API Framework | **FastAPI 0.111** | REST API, async request handling, auto OpenAPI docs |
| ORM | **SQLAlchemy 2.0** | Database models and query builder |
| Database | **SQLite** | Persistent storage for cases, users, audit logs |
| Vector DB | **Qdrant 1.9** | Semantic search over chunked evidence text |
| Embeddings | **sentence-transformers 2.7** | Text-to-vector encoding (all-MiniLM-L6-v2) |
| LLM Runtime | **Ollama** | Local LLM serving (llama3.2:3b recommended) |
| NLP | **spaCy 3.7** (`en_core_web_lg`) | Named entity recognition |
| Graph Engine | **NetworkX 3.3** | Entity relationship graph construction |
| Auth | **python-jose** + **bcrypt** | JWT tokens + password hashing |
| Rate Limiting | **slowapi** | Brute-force protection on auth endpoints |
| PDF Parsing | **pdfminer.six** | Text extraction from PDF evidence |
| OCR | **pytesseract** | Text extraction from image evidence |
| Audio | **openai-whisper** | Transcription of audio evidence |
| Office Docs | **python-docx**, **openpyxl**, **python-pptx** | Word, Excel, PowerPoint parsing |
| Email | **extract-msg** | Outlook MSG file parsing |
| Disk Images | **pyewf** + **pytsk3** | Forensic E01/DD image traversal |
| EXIF | **exifread** | GPS and metadata from photographs |
| Reports | **ReportLab 4.2** | PDF report generation |
| Fuzzy Match | **rapidfuzz** | Entity alias and deduplication matching |
| Server | **uvicorn 0.29** | ASGI server |

### Frontend

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Framework | **React 18** | Component-based UI |
| Build Tool | **Vite** | Fast development server and bundler |
| Routing | **React Router v6** | Client-side navigation |
| HTTP Client | **axios** | API communication |
| Styling | **Tailwind CSS** + Vanilla CSS | Utility classes + custom design system |
| Icons | **lucide-react** | Consistent icon set |
| Date Formatting | **date-fns** | Human-readable timestamps |
| Toasts | **react-hot-toast** | Non-blocking user notifications |
| Error Handling | **React Error Boundaries** | Graceful crash recovery per route |

---

## Prerequisites

Ensure the following are installed on your system before proceeding.

| Requirement | Min Version | macOS | Linux (Ubuntu/Debian) |
|---|---|---|---|
| Python | 3.10+ | `brew install python3` | `sudo apt install python3 python3-pip python3-venv` |
| Node.js | 18+ | `brew install node` | `sudo apt install nodejs npm` |
| npm | 9+ | bundled with Node.js | bundled with Node.js |
| Ollama | latest | [ollama.com](https://ollama.com) | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Tesseract OCR | 5.0+ | `brew install tesseract` | `sudo apt install tesseract-ocr` |
| ffmpeg | 6.0+ | `brew install ffmpeg` | `sudo apt install ffmpeg` |
| libewf (disk images) | latest | `brew install libewf` | `sudo apt install libewf-dev ewf-tools` |
| The Sleuth Kit | 4.12+ | `brew install sleuthkit` | `sudo apt install sleuthkit` |
| Build tools | — | Xcode CLI tools | `sudo apt install build-essential libssl-dev libffi-dev python3-dev` |

> **Note:** pyewf and pytsk3 (disk image parsing) are optional. The system degrades gracefully and supports all other file types without them.

### Linux GPU Setup (NVIDIA)

Linux users with NVIDIA GPUs get the best performance from Ollama. Before running setup:

```bash
# Install NVIDIA driver (required for GPU inference)
sudo apt install nvidia-driver-570
sudo reboot

# After reboot, verify GPU is detected
nvidia-smi
# Should show your GPU and Driver Version: 570+
```

Recommended models by GPU VRAM:
- **4 GB VRAM** (e.g. GTX 1050 Ti): `phi4-mini`
- **8 GB VRAM**: `llama3.2:3b` *(default)*
- **12 GB+ VRAM**: `qwen2.5:7b`

Set your chosen model in `.env`:

```env
OLLAMA_MODEL=phi4-mini
```

---

## Quick Setup

The fastest way to get started on a fresh machine. `setup.sh` **auto-detects your operating system** and runs the correct commands for both macOS and Linux automatically:

```bash
# 1. Clone or extract the project
cd IDFA_main3/

# 2. Run the automated setup script
./setup.sh
```

> **Linux users:** If you get a permission error, run `chmod +x setup.sh` first, then `./setup.sh`.

`setup.sh` will:
- Check for Python 3 and Node.js
- Create a Python virtual environment
- Install all Python dependencies
- Download the spaCy NLP model (`en_core_web_lg`)
- Create required data directories
- Run all database migrations
- Install frontend npm packages

---

## Manual Installation

If you prefer to set up manually or the automated script encounters issues:

### Step 1 — Python Environment

```bash
cd IDFA_main3/

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install Python packages
pip install --upgrade pip setuptools wheel
pip install -r requirements.txt

# Download spaCy language model
python3 -m spacy download en_core_web_lg
```

### Step 2 — Database Initialisation

```bash
# Run all migrations with the master script
PYTHONPATH=. python3 backend/migrate_all.py
```

### Step 3 — Data Directories

```bash
mkdir -p data/cases
mkdir -p data/qdrant_store
```

### Step 4 — Frontend

```bash
cd frontend/
npm install
cd ..
```

### Step 5 — Ollama Model

```bash
# Start Ollama service
ollama serve

# Pull a model (in a new terminal)
ollama pull llama3.2:3b
```

> **Linux users with NVIDIA GPU:** See the [Linux GPU Setup](#linux-gpu-setup-nvidia) section above to ensure GPU inference is enabled before pulling a model.

---

## Running the Application

You need **three terminals** running simultaneously. The commands are identical on macOS and Linux.

### Terminal 1 — Ollama (LLM Runtime)

```bash
# Same on macOS and Linux
ollama serve
```

> Skip this step if Ollama is already running as a system service.

### Terminal 2 — Backend (FastAPI)

```bash
# Same on macOS and Linux
cd IDFA_main3/
source venv/bin/activate
PYTHONPATH=. uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The backend will be available at: **http://localhost:8000**

### Terminal 3 — Frontend (React + Vite)

```bash
# Same on macOS and Linux
cd IDFA_main3/frontend/
npm run dev
```

The application will be available at: **http://localhost:5173**

---

## First-Time Setup

1. Open **http://localhost:5173** in your browser
2. Click **Register** — the very first account created is automatically assigned the **Admin** role
3. Fill in your name, email, username, and password
4. Log in and you will land on the **Dashboard**
5. Create your first case via the **Cases** screen
6. Upload evidence files in the **Evidence** tab of the case

> **Important:** Secure your Admin credentials. Subsequent registrations default to the **Analyst** role and must be manually promoted by an Admin via **User Management**.

---

## Demo Data

To quickly populate the system with realistic demo data for presentations:

```bash
source venv/bin/activate
PYTHONPATH=. python3 backend/seed_demo.py
```

This creates:

| Account | Password | Role |
|---------|----------|------|
| `admin` | `Admin@IDF2025` | Admin |
| `det_markov` | `Markov@2025` | Investigator |
| `analyst_chen` | `Chen@2025` | Analyst |

And seeds **3 cases** — *Operation Phantom Trace* (cybercrime), *Vertex Pharma Leak* (corporate espionage), *Havenport Missing Person* — along with entities, notes, watchlist keywords, and audit history.

> The seeder is idempotent — safe to run multiple times without creating duplicate data.

---

## API Documentation

FastAPI generates interactive API documentation automatically.

| Interface | URL |
|-----------|-----|
| Swagger UI (interactive) | http://localhost:8000/docs |
| ReDoc (readable) | http://localhost:8000/redoc |
| OpenAPI JSON | http://localhost:8000/openapi.json |

### Key API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login` | Authenticate and receive JWT token |
| `POST` | `/api/auth/register` | Register a new user account |
| `GET` | `/api/auth/me` | Get current user profile |
| `POST` | `/api/auth/change-password` | Self-service password change |
| `GET` | `/api/cases` | List all accessible cases |
| `POST` | `/api/cases` | Create a new case |
| `GET` | `/api/cases/{id}/evidence` | List evidence for a case |
| `POST` | `/api/cases/{id}/evidence` | Upload evidence file |
| `POST` | `/api/cases/{id}/query` | Submit a natural-language question |
| `GET` | `/api/cases/{id}/entities` | List extracted entities |
| `GET` | `/api/cases/{id}/graph` | Get entity relationship graph |
| `GET` | `/api/cases/{id}/timeline` | Get file activity timeline |
| `GET` | `/api/cases/{id}/artifacts` | List all forensic artifacts |
| `GET` | `/api/cases/{id}/anomalies` | Get anomaly-flagged files |
| `POST` | `/api/cases/{id}/reports` | Generate an investigation report |
| `GET` | `/api/activity` | Global cross-case audit feed |
| `GET` | `/api/queue` | Ingestion job queue status |
| `GET` | `/api/status` | System health (DB + Ollama) |

All endpoints (except `/api/auth/login` and `/api/auth/register`) require a **Bearer token** in the `Authorization` header.

---

## Project Structure

```
IDFA_main3/
│
├── setup.sh                    # Automated setup script (macOS + Linux)
├── requirements.txt            # Python package dependencies
├── .env                        # Environment configuration
│
├── backend/
│   ├── main.py                 # FastAPI app, route registration, middleware
│   ├── models.py               # SQLAlchemy ORM models
│   ├── schemas.py              # Pydantic request/response schemas
│   ├── database.py             # DB engine, session factory, init_db
│   ├── auth.py                 # JWT, password hashing, token verification
│   ├── dependencies.py         # Shared FastAPI dependencies
│   ├── ingestion.py            # Evidence ingestion pipeline + background worker
│   ├── seed_demo.py            # Demo data seeder
│   │
│   ├── routers/
│   │   └── auth_router.py      # Auth endpoints (login, register, users, passwords)
│   │
│   ├── modules/                # Optional ingestion modules
│   │   ├── disk_image.py       # pyewf + pytsk3 E01/DD traversal
│   │   ├── ocr.py              # Tesseract OCR wrapper
│   │   └── audio.py            # Whisper transcription wrapper
│   │
│   └── migrate_*.py            # Incremental DB migration scripts
│
├── frontend/
│   ├── index.html
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── package.json
│   │
│   └── src/
│       ├── App.jsx             # Root app, routing, layout
│       ├── main.jsx            # React entry point
│       ├── index.css           # Global styles and design tokens
│       │
│       ├── api/
│       │   └── client.js       # Axios instance + all API functions
│       │
│       ├── context/
│       │   └── AuthContext.jsx # Authentication state and JWT management
│       │
│       ├── components/
│       │   ├── Sidebar.jsx     # Navigation sidebar with collapse
│       │   ├── StatusBar.jsx   # Top search bar
│       │   ├── PageLayout.jsx  # Shared full-width page wrapper
│       │   ├── AppBackground.jsx
│       │   ├── AnimStatCard.jsx
│       │   ├── Badge.jsx
│       │   ├── ConfirmDialog.jsx
│       │   ├── ErrorBoundary.jsx   # React crash recovery
│       │   └── ProtectedRoute.jsx
│       │
│       ├── constants/
│       │   └── activityMeta.js  # Action type colours and labels
│       │
│       └── pages/
│           ├── LoginPage.jsx
│           ├── RegisterPage.jsx
│           ├── DashboardPage.jsx       # Stats + recent activity
│           ├── CasesPage.jsx           # Case list and creation
│           ├── CaseDetailPage.jsx      # Case overview
│           ├── EvidencePage.jsx        # Upload and manage evidence
│           ├── ArtifactsPage.jsx       # Browse extracted artifacts
│           ├── InvestigatePage.jsx     # AI Q&A interface
│           ├── EntityMapPage.jsx       # Force-directed graph
│           ├── ProfilePage.jsx         # Entity intelligence profiles
│           ├── TimelinePage.jsx        # Chronological file activity
│           ├── AnomalyPage.jsx         # Flagged suspicious files
│           ├── WatchlistPage.jsx       # Keyword monitoring
│           ├── GeoMapPage.jsx          # Geographic visualisation
│           ├── NotesPage.jsx           # Investigation notes
│           ├── AuditPage.jsx           # Per-case audit log
│           ├── ActivityPage.jsx        # Global activity feed
│           ├── ReportsPage.jsx         # Report generation
│           ├── QueuePage.jsx           # Ingestion job queue
│           ├── AdminUsersPage.jsx      # User management
│           └── ChangePasswordPage.jsx  # Self-service password reset
│
└── data/
    ├── cases/                  # Evidence files, keyed by case UUID
    └── qdrant_store/           # Qdrant vector database on-disk storage
```

---

## Known Limitations

| Limitation | Detail |
|------------|--------|
| **Local LLM quality** | Response accuracy is bounded by the capability of the selected Ollama model. Smaller models (3B parameters) may hallucinate or miss nuanced connections. |
| **Single-node deployment** | The system is designed for a single investigator workstation. It is not load-balanced or horizontally scalable in its current form. |
| **SQLite concurrency** | SQLite does not support high write concurrency. Heavy parallel ingestion jobs may queue. Suitable for teams of 1–5 investigators. |
| **Disk image support** | pyewf and pytsk3 require native C libraries. On macOS, installation can fail on certain configurations. On Linux, install `libewf-dev ewf-tools` first. Fallback to file-based evidence is automatic. |
| **No email notifications** | Password reset and workflow notifications rely on Admin action rather than SMTP email, by design (air-gapped deployment). |
| **Whisper speed** | Audio transcription via Whisper is slow without a CUDA-capable GPU. Large audio files may take several minutes to ingest. Linux users with NVIDIA GPUs get significantly faster transcription. |
| **Map data** | The geographic map requires a Leaflet tile server or internet access for map tiles. In a fully air-gapped environment, a local tile server must be configured. |
| **spaCy NER accuracy** | NER quality depends on the language model. Highly technical forensic jargon, code, or non-English content may not be correctly classified. |

---

## Troubleshooting

### Ollama using CPU instead of GPU (Linux)

If inference is slow on Linux, verify your NVIDIA driver is installed and at version 570+:

```bash
nvidia-smi  # Check driver version — must be 570+
sudo apt install nvidia-driver-570
sudo reboot
```

After reboot, run `nvidia-smi` again to confirm the GPU is visible, then restart `ollama serve`.

---

### pyewf not installing

`.E01` disk image support requires libewf. If it fails to build, **all other file types** (PDF, DOCX, audio, images, etc.) still work normally without it.

```bash
# Linux
sudo apt install libewf-dev ewf-tools
pip install libewf-python

# macOS
brew install libewf
pip install libewf-python
```

---

### Port already in use

```bash
# Find and kill whatever is using port 8000
lsof -i :8000
kill -9 <PID>
```

---

### spaCy model missing

If you see `OSError: [E050] Can't find model 'en_core_web_lg'`:

```bash
source venv/bin/activate
python3 -m spacy download en_core_web_lg
```

---

### Permission denied on setup.sh (Linux)

```bash
chmod +x setup.sh
./setup.sh
```

---

### Node.js version too old (Linux)

Ubuntu's default `apt` repository may install an older Node.js. If you need Node 18+:

```bash
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt install -y nodejs
node --version  # Should show v18+
```

---

## Future Work

The following enhancements are planned or proposed for future iterations of this project:

- **Multi-language NER** — integrate multilingual spaCy models to support non-English evidence
- **Collaborative investigation** — real-time case sharing between multiple simultaneous investigators using WebSockets
- **YARA rule integration** — scan artifacts against community YARA rule sets for malware signatures
- **Timeline visualisation** — interactive Gantt-style timeline renderer with zoom and filtering
- **Automated anomaly scoring** — ML-based behavioural model trained on known-good file system patterns
- **Docker deployment** — containerised deployment with `docker-compose` for reproducible environments
- **Qdrant cloud mode** — option to connect to a remote Qdrant cluster for large-scale evidence repositories
- **Larger LLM support** — quantised 13B/70B model support via llama.cpp for higher-quality analysis
- **Chain-of-custody PDF** — cryptographically signed chain-of-custody documents for court admissibility
- **Stix/TAXII export** — export entity and relationship data in Structured Threat Intelligence eXpression (STIX) format for threat intelligence platforms

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
| **Background worker** | Evidence ingestion can take minutes. A background queue prevents API timeouts and allows real-time progress reporting. |
| **Role-based access** | Multi-user investigations require controlled access. The four-tier role model mirrors real-world forensics team structures (Admin / Investigator / Analyst / Viewer). |

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

*Built with ❤ as a final year project — pushing the boundaries of what a student project can look like.*

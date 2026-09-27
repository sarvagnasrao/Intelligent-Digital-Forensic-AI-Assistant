# Setup Guide

**Intelligent Digital Forensic AI Assistant** — an offline, local-only digital-forensics
workstation. Upload evidence → extract text and metadata → index into a vector store →
query with natural language → reconstruct timelines, entity graphs and anomalies.

Nothing leaves the machine. There is no cloud component, no telemetry and no outbound
call anywhere in the product.

---

## 1. What you need first

| Requirement | Version | Notes |
|---|---|---|
| **Python** | 3.10+ (3.12 used) | Needed for the backend. |
| **Node.js** | 18+ (24 used) | Needed only to build/serve the frontend. |
| **Ollama** | any current | The local LLM. [ollama.com](https://ollama.com) |
| Disk | ~3 GB | Plus room for your evidence. |
| GPU | optional | Without one, audio/video transcription runs on the CPU and is slow. |

Check what you have:

```bash
python --version
node --version
ollama --version
```

**Use `npm`, not `yarn`.** `frontend/package-lock.json` is the lockfile of record. The
global `yarn` 1.x on Windows cannot resolve `vite` and dies with
`vite is not recognized`. `setup_windows.bat` and `setup.sh` both use `npm`.

---

## 2. Install

### Windows

```cmd
git clone https://github.com/sarvagnasrao/Intelligent-Digital-Forensic-AI-Assistant.git
cd Intelligent-Digital-Forensic-AI-Assistant
setup_windows.bat
```

Six steps: prerequisites, `.env`, virtualenv, Python packages, frontend packages,
migrations.

### Linux / macOS

```bash
git clone https://github.com/sarvagnasrao/Intelligent-Digital-Forensic-AI-Assistant.git
cd Intelligent-Digital-Forensic-AI-Assistant
chmod +x setup.sh start.sh
./setup.sh
```

On Debian/Ubuntu the forensic disk-image libraries need system packages first:

```bash
sudo apt install libewf-dev ewf-tools sleuthkit
```

### Doing it by hand

<details>
<summary>Windows, step by step</summary>

```cmd
copy .env.example .env
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m spacy download en_core_web_lg
cd frontend && npm install && cd ..
set PYTHONPATH=.
python backend\migrate_all.py
```

</details>

<details>
<summary>Linux / macOS, step by step</summary>

```bash
cp .env.example .env
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
python -m spacy download en_core_web_sm
python -m spacy download en_core_web_lg
(cd frontend && npm install)
PYTHONPATH=. python backend/migrate_all.py
```

</details>

### Air-gapped / fully offline install

`vendor/` holds ~950 MB of pre-downloaded wheels and is **deliberately not in git** —
several files exceed GitHub's 100 MB per-file limit, so committing it would break the
push and bloat history permanently. To install with no network at all, copy the `vendor/`
directory onto the target machine alongside the repo. Both setup scripts detect it and
switch to a fully offline install automatically:

```
vendor/
└── python/     # 138 wheels + the spaCy en_core_web_lg tarball
```

Regenerate it on a connected machine with:

```bash
pip download -r requirements.txt -d vendor/python
python -m spacy download en_core_web_lg    # then move the tarball into vendor/python
```

Without `vendor/`, setup installs from PyPI and needs internet.

> `torch` is **not** in `requirements.txt` and is imported lazily, so the backend starts
> and runs without it. It is only needed for the optional GPU-accelerated transcription
> path. If you want that, install a **CUDA** build of torch yourself — the CPU build
> cannot drive a GPU and the system-health page will tell you so.

---

## 3. Pull the AI model — do not skip this

This is the single most common reason the assistant "works but says nothing".

```bash
ollama serve                 # in its own terminal, leave it running
ollama pull llama3.2:3b      # in another
```

**"Ollama is running" is not the same as "there is a model to answer with."** Ollama
starts happily with zero models installed, and `/api/tags` returns `200` with an empty
list. The app now checks for the model itself and will tell you on the **System Health**
page whether the assistant can actually answer — look for the *Ollama* card, not the
daemon.

To use a different model, set `OLLAMA_MODEL` in `.env`.

---

## 4. Change the secret key

`.env` ships with `SECRET_KEY=CHANGE_ME_GENERATE_A_REAL_KEY`, and **the app starts and
logs in with it** — nothing validates it. That value is published in this repository, so
anyone who has read the repo can forge an administrator token for your instance. On a
forensics workstation that is a real problem, not a formality.

Generate a real one before anyone else touches the machine:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Paste the output into `SECRET_KEY` in `.env`. Changing it invalidates existing sessions,
so do it before you start working.

---

## 5. Run it

```cmd
start_windows.bat        REM Windows
```
```bash
./start.sh               # Linux / macOS
```

Three services start in their own windows and log to `logs/`.

| Service | URL |
|---|---|
| **Frontend** — open this | <http://localhost:3000> |
| Backend API | <http://localhost:8000> |
| Interactive API docs | <http://localhost:8000/docs> |
| Health / service status | <http://localhost:8000/api/status> |
| Ollama | <http://localhost:11434> |

> **Port 3000, not 5173.** `frontend/vite.config.js` pins the dev server to 3000. If 3000
> is busy, Vite falls back to 5173 — trust the URL printed in the frontend window.

### Demo data (optional)

```bash
set PYTHONPATH=.
python backend\seed_demo.py          REM Windows
PYTHONPATH=. python backend/seed_demo.py   # Linux / macOS
```

Idempotent — safe to re-run. Gives you three cases with evidence, entities and a query
history, plus these logins:

| Username | Password | Role |
|---|---|---|
| `admin` | `Admin@IDF2025` | Admin |
| `det_markov` | `Markov@2025` | Detective |
| `analyst_chen` | `Chen@2025` | Analyst |

The **first account you register becomes an Admin**; everyone after that defaults to
Analyst and needs manual promotion.

---

## 6. Check the install worked

```bash
curl http://localhost:8000/api/status
```

Every service is **actually measured** — the database by a real query, the vector store
by counting real collections on disk, the worker by its live thread. Nothing is
hardcoded. Anything that could not be measured is reported as *not verifiable* rather
than as a green tick, so an honest `—` is not a fault.

Also worth confirming:

- <http://localhost:3000> loads and you can log in.
- System Health shows **Ollama → Ready to answer** (not just "daemon running").
- Upload a small PDF, queue it, and watch live progress with a countdown on the Queue
  page.

---

## 7. Where things live

```
data/
├── forensic.db                  SQLite — cases, evidence, entities, audit log
└── cases/<case_id>/
    ├── evidence/                uploaded files
    └── qdrant/                  this case's vector index (per case, never shared)
```

There is **no** `data/qdrant_store` directory. Each case gets its own Qdrant storage
folder, and indexing one case never touches another's.

---

## 8. Running the checks

```bash
set PYTHONPATH=.
python tests\verify_ingestion_modes.py     REM and verify_ws_progress, verify_queue_api,
                                           REM verify_job_stop, verify_forensic_failure,
                                           REM verify_vector_store, verify_cpu_sampler,
                                           REM verify_gpu_telemetry
```

**Stop the backend first.** A running server has its own worker thread, which selects
queued jobs — a test fixture left queued gets executed by a second process, which then
loses the race for the same Qdrant directory. See `tests/README.md`.

---

## 9. If something goes wrong

**"Authentication failed" but the password is right.**
The frontend is telling you it could not reach the backend. With the backend down, Vite's
dev proxy answers `HTTP 500` with an *empty body*, which used to be reported as bad
credentials. Check the backend window and `logs/backend.log`. A genuinely wrong password
now shows the server's own message instead.

**The AI says it did not generate a response.**
Check the System Health page's Ollama card. Almost always one of: Ollama is not running,
or no model is installed (`ollama pull llama3.2:3b`). The app no longer suggests
"try rephrasing your question" for this, because no rewording installs a model.

**A disk image ingests 0 files.**
Usually the image itself, not the app. A truncated acquisition cannot be walked — TSK
needs the `$MFT` and will refuse to mount. The app detects this up front and says so
rather than reporting a cheerful zero. Re-acquire the image.

**`vite is not recognized`.**
You used yarn. Run `npm install` in `frontend/`.

**`no such column: ingestion_jobs.eta_seconds`.**
Your `forensic.db` predates a migration. `create_all` creates tables but never adds
columns to existing ones:

```bash
set PYTHONPATH=.
python backend\migrate_all.py
```

**`Storage folder ... is already accessed by another instance of Qdrant client`.**
Two processes have the same case's Qdrant directory open. Usually a stale backend, or a
test run while the server was up. Stop the duplicates.

**Everything is very slow.**
Check the System Health page's *Resource* figures, then the per-job CPU ceiling and RAM
floor on the Queue page. The default budget is derived from the actual machine. If the
GPU shows as present but *not measurable*, that adapter is reporting no utilisation
counter — a real limitation, not a fault to ignore.

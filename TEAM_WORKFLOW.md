# Team Working Procedure — IDFA

**Project:** Intelligent Digital Forensic AI Assistant
**Repo:** `https://github.com/sarvagnasrao/Intelligent-Digital-Forensic-AI-Assistant`
**Working branch:** `main3`
**Read first:** `AGENTS.md` in the repo root. This document is the *procedure*; `AGENTS.md` is the
*technical record*. Do not start work without reading `AGENTS.md` — it records verified state,
known bugs and traps that are not derivable from the code.

---

## 1. The WhatsApp group protocol

The group is the source of truth for **who is doing what, right now**. Three moments matter.

### 1.1 When you start work — post this

```
Project : Working

👤 <your name>
📌 Task: <the one thing you are doing, in one line>
🌿 Branch: main3
⏱️ ETA: <realistic — hours, not "today">
```

> Rules
> - Post this **before** you touch anything, not after.
> - One task per announcement. If you pick up a second task, post a new `Project : Working`.
> - If someone else already announced the same area, coordinate in the group **before** editing —
>   most lost work here is two people in the same file.

### 1.2 While you work — report progress, errors and improvements

Post during the day, not just at the end. Keep each post short and use these three headings, so
the group can scan it:

```
📊 Progress
- <what works now that didn't before>

🐞 Error found
- <what the error was, and what you did about it>

💡 Improvement
- <something you noticed that should change, but is not in your task>
```

If you find a bug in someone else's area, **do not silently fix it** unless it is blocking you.
Post it. A silent cross-area fix is how two branches diverge and nobody knows why.

### 1.3 When you stop work — post this

```
Project : End

👤 <your name>
📌 Task: <the same line you opened with>
✅ Outcome: <done / partially done / blocked>
📦 Commit: <short hash> — <subject>
📝 Notes: <anything the next person needs to know>
```

> Rules
> - Always post `Project : End`, **even if the work failed or you got blocked**. A silent
>   disappearance leaves the group thinking you are still working on it.
> - If you are blocked, say so in `Outcome` and say what you need.
> - Anything not committed and pushed when you post `End` is **not done**.

---

## 2. Before you start working

Do these in order. Steps 1–4 take about five minutes and prevent most of the problems we have hit.

| # | Step | Command / check |
|---|---|---|
| 1 | Read `AGENTS.md` end to end | — |
| 2 | Get the latest code | `git fetch --all` then `git checkout main3` then `git pull idfa main3` |
| 3 | Make sure your tree is clean before you start | `git status` — must be empty |
| 4 | Start the services | see §3 |
| 5 | Confirm the baseline is green **before** you change anything | see §5 |

> **Step 5 is the one people skip.** If the tests already fail before your change, you cannot
> prove your change is not what broke them. If the baseline is red, stop and post in the group
> before touching code.

---

## 3. Running the project

### Windows
```cmd
setup_windows.bat          :: once, first time only
start_windows.bat          :: ollama + backend + frontend
```

### Linux / macOS
```bash
./setup.sh        # once
./start.sh
```

### Manual
```bash
ollama serve
PYTHONPATH=. uvicorn backend.main:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev
```

| Service | Port |
|---|---|
| Backend (FastAPI) | **8000** |
| Frontend (Vite) | **3000** |
| Ollama | 11434 |

> ⚠️ `start_windows.bat` prints `http://localhost:5173`. That is wrong — `frontend/vite.config.js`
> pins **3000**. 5173 is only the Vite fallback. Always use 3000.

> ⚠️ `PYTHONPATH=.` is required. Without it the backend cannot import `backend.*` and you will
> spend twenty minutes debugging a problem that is really a missing environment variable.

**Demo logins:** `admin` / `Admin@IDF2025` · `det_markov` / `Markov@2025` · `analyst_chen` / `Chen@2025`

---

## 4. While you are working — the rules that matter

### 4.1 Never claim success you have not observed

This is the single most important rule in this document. In a forensic tool, a false "success" is
worse than a crash, because the investigator trusts it.

Three real examples from this repo, all of the same shape:

- A truncated disk image reported **"Completed — 0 artifacts"** and marked the evidence `Indexed`.
  No error was ever shown. The investigator believed the file was processed.
- A failed vector-store call returned `0`, which the pipeline read as "this document had no
  text", so the job finished **"Completed — 0 chunks"** and marked the evidence `Indexed`.
- Progress updated in the database but never reached the browser, because every broadcast was
  being swallowed by a bare `except: pass`.

All three looked like working software. None were. **If the system can fail silently, it will,
and it will look fine.**

So, concretely:
- A failure path must set a **terminal** state (`Failed` / `Stopped`) and show the reason.
- Never let "success" and "produced nothing" be the same value.
- If you catch an exception, do not just log it and continue unless continuing is genuinely
  correct — and if it is, say so in a comment explaining why.

### 4.2 Never swallow an exception silently

```python
# NO
except Exception:
    pass
except Exception as e:
    print(f"error: {e}")

# YES
except Exception as e:
    print(f"[MODULE] what we were doing failed: {e}")
    raise          # or record a real failure state, and say why
```

If the error is genuinely ignorable, write the comment that explains why it is ignorable. Every
`except: pass` in this codebase is a place a bug can hide.

### 4.3 Match the callback contract exactly

We lost a full day to this. The sub-pipelines call:

```python
progress_callback(case_id, job_id, evidence_id, percent, step)   # 5 arguments
```

Passing a 2-argument helper as that callback does not fail loudly — every single call raises
`TypeError` inside a bare `except`, and the database row still advances, so it *looks alive*.
Check the arity at the definition site, not the call site.

### 4.4 Paths and shell

- Always `os.path.join()` / `pathlib`. Never hardcode `/` or `\`.
- **No shell calls from Python** (`grep`, `cat`, `ls`). Use `os`, `shutil`, `glob`.
- On Windows, `pyewf` needs an absolute, normalised path — see `forensic_ingestion.py`.

### 4.5 Migrations are additive only

- Add a new `backend/migrate_*.py` and register it in `backend/migrate_all.py`.
- **Never** edit `models.py` alone and expect an existing database to update.
- Verify idempotency by running it twice.

### 4.6 Branch reality check

`main3` has **diverged from `main` and `Main2`**. `git log` on one tells you nothing about the
others. In particular the two branches use **incompatible CSS variable namespaces** — copying a UI
file between them silently produces invisible or unstyled elements. See `AGENTS.md` §7 before
porting any UI.

### 4.7 Do not commit `vendor/`

`vendor/` is the ~1.1 GB air-gap install kit and is **deliberately gitignored**. It contains files
over GitHub's 100 MB limit; committing it breaks the push permanently. Regenerate it locally with
`pip download -r requirements.txt -d vendor/python`.

### 4.8 Never put a credential in a remote URL

Both remotes are plain HTTPS. If a push suddenly demands credentials, that is a credential-helper
or auth problem to fix locally — **not** a reason to embed a token in the remote URL.

---

## 5. Before you say "done" — the verification gate

**You may not post `Project : End` until all of the following pass.** This is the gate. Run it
from the repo root.

### 5.1 Syntax and imports
```bash
PYTHONPATH=. python -m py_compile <every python file you touched>
PYTHONPATH=. python -c "import backend.main; print('backend OK')"
```

### 5.2 Migrations (only if you touched the schema)
```bash
PYTHONPATH=. python backend/migrate_all.py && PYTHONPATH=. python backend/migrate_all.py
```
Both runs must report the same result. The second run must be a no-op.

### 5.3 Behavioural tests — all four, every time
```bash
PYTHONPATH=. python tests/verify_ingestion_modes.py    # 39 checks
PYTHONPATH=. python -W error::RuntimeWarning tests/verify_ws_progress.py   # 15
PYTHONPATH=. python tests/verify_queue_api.py          # 37
PYTHONPATH=. python tests/verify_live_stack.py         # 26  (needs the stack running)
```

Windows: `$env:PYTHONPATH="."` then `venv\Scripts\python.exe tests\<name>.py`

**117 checks, 0 failures, is the bar.** These run the real pipeline, the real event loop and the
real HTTP API — not mocks. `verify_live_stack.py` additionally crosses a real WebSocket, which is
the only check that covers the seam where the progress bug lived.

> If you add a behaviour, **add a test that fails without your fix.** A test that passes both
> before and after is not a test.

### 5.4 Frontend (only if you touched `frontend/`)
```bash
cd frontend && npm run build
```

### 5.5 Manual check in the browser
Automated checks do not tell you whether a progress bar actually moves. Upload a file, watch the
queue, confirm the bar advances and the status text is sensible.

### 5.6 The honesty check
Before you post, write one sentence: **"I verified this by doing ___."** If you cannot fill that
in, you are not done. Say so in the group instead of guessing.

---

## 6. Committing and pushing

```bash
git add <specific files>          # never `git add -A` in this repo
git status                        # read the staged list before committing
git commit -F <message-file>      # see below
git push idfa main3:main
```

### Writing the commit message

Use a file, not `-m`. The repo's history has been damaged by shell quoting before.

```bash
# write the message to a file first, then:
git commit -F .git/COMMIT_MSG.txt
```

Structure:

```
<Short imperative subject: what changed and why>

<Why it changed — the bug, not the diff. What was broken before
and what is true now. Note anything a future reader would get
wrong without this.>
```

Rules:
- Subject ≤ 70 characters, imperative mood ("Fix", not "Fixed" or "Fixes").
- Body explains **why**. The diff already says what.
- Reference the `AGENTS.md` bug number (e.g. "B7") when fixing a known one.
- **Never** commit secrets, tokens, real case data, or `vendor/`.

### Before you push
- `git status` is clean.
- All five gates in §5 passed.
- The commit message explains why.

---

## 7. Post-work report template

Use this when posting `Project : End`:

```
Project : End

👤 <your name>
📌 Task: <line you opened with>
✅ Outcome: done

🔧 What changed
- <one line per meaningful change>

🐞 Errors found and fixed
- <error> → <fix>

💡 Improvements / concerns
- <anything the team should know, including things you did NOT fix>

✅ Verification
- py_compile: pass
- import backend.main: pass
- migrate_all x2: pass (idempotent)
- tests: 117/117 pass
- vite build: pass
- manual: <what you actually did in the browser>

📦 Commit: <hash> — <subject>
🔀 Pushed: idfa/main3:main

⚠️ Not done / next steps
- <be explicit — this is the most useful part of the report>
```

> **The "Not done" section is not optional.** Reporting partial work accurately is worth far more
> than reporting it as finished. If you found a problem you could not solve, say so — that is
> information, not failure.

---

## 8. Escalation

Post in the group **immediately**, do not wait until your `Project : End`, if:

- The baseline tests fail on a clean checkout and you did not cause it.
- Two people need to edit the same file.
- You need a decision you cannot make yourself (scope, schema, UI direction).
- You discover a bug in an area you are not working in.
- You are about to do something destructive (a migration against real data, deleting cases,
  anything touching `data/`).

---

## 9. Quick reference card

```
START    read AGENTS.md → git pull → git status clean → start services → BASELINE GREEN
WORK     post "Project : Working"   →  follow §4   →  test continuously, not at the end
BLOCKED  post in the group immediately, do not go quiet
VERIFY   §5 gate: py_compile + import + migrate x2 + 117 tests + build + browser
FINISH   commit with a file-based message → git push idfa main3:main
CLOSE    post "Project : End" with outcome, verification and what you did NOT do
```

**The one rule:** never let the system report a success you have not actually seen.

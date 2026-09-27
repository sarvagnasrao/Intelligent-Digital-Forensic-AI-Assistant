# Verification scripts

Executable checks for the parts of the system that are hard to eyeball. Each
one runs the real code — real pipeline, real event loop, real HTTP — and
prints one `PASS`/`FAIL` line per assertion with a non-zero exit code if
anything fails.

Run them from the repository root with `PYTHONPATH` set:

```bash
# Linux / macOS
PYTHONPATH=. venv/bin/python tests/verify_ingestion_modes.py
PYTHONPATH=. venv/bin/python tests/verify_ws_progress.py
PYTHONPATH=. venv/bin/python tests/verify_queue_api.py
PYTHONPATH=. venv/bin/python tests/verify_job_stop.py
PYTHONPATH=. venv/bin/python tests/verify_vector_store.py
PYTHONPATH=. venv/bin/python tests/verify_live_stack.py   # needs the stack running

# Windows
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ingestion_modes.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ws_progress.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_queue_api.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_job_stop.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_vector_store.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_live_stack.py
```

The first five are self-contained. The sixth needs `ollama serve`, uvicorn on
`:8000` and the Vite dev server on `:3000` already running; it waits 90 s for
the backend and skips cleanly if it never comes up.

> **Stop the backend before running the self-contained ones.** A live server on
> the same `data/forensic.db` runs its own worker thread, and that worker
> selects `Queued` jobs — so a fixture left in `Queued` gets executed in a
> second process, which then loses the race for the same per-case Qdrant
> directory and fails with `Storage folder ... is already accessed by another
> instance of Qdrant client`. These scripts insert fixture jobs as `Running`
> for exactly that reason (the worker only ever selects `Queued`), but they
> also share the database with anything you have running.

| Script | What it proves | Cost |
|---|---|---|
| `verify_ingestion_modes.py` | The three ingestion profiles reach the pipeline: same file ingested under `fastest` / `normal` / `accurate` yields 2 / 3 / 8 chunks, matching the configured `chunk_size` exactly. Progress is monotonic, ends at 100, and the profile is persisted on the job. Also asserts **a failed index is never reported as a success**. | ~15 s |
| `verify_ws_progress.py` | Ingestion progress reaches subscribers on the **server's** event loop — the exact defect that made live progress appear broken. Also asserts a strict 5-argument callback (the worker's shape) is honoured. | ~10 s |
| `verify_queue_api.py` | The queue API surface the frontend depends on: the three profiles, a device-derived budget with slider bounds, mode-aware estimates, limit validation, live settings on a running job. | ~5 s |
| `verify_job_stop.py` | The Stop button actually stops. Drives the real `_process_job` on a worker thread, fires `stop_job()` from another thread exactly as the endpoint does, and requires that the job halts, is recorded `Stopped` rather than `Failed`, reverts the evidence to `Uploaded`, and **did not reach 100 %** — a stop that is acknowledged but ignored is otherwise indistinguishable from a job that simply finished. Also pins the HTTP contract, including that `DELETE /queue/{id}/cancel` still refuses a `Running` job. | ~20 s |
| `verify_vector_store.py` | One Qdrant client **per case**, keyed on a normalised path, with real data isolation: indexing case B leaves case A's storage untouched. Plus the optional-dependency contract — `backend.main` and `backend.ingestion` import with `torch` and `sentence_transformers` blocked, and a stop request surfaces as `StopIteration` rather than an indexing failure. | ~10 s |
| `verify_live_stack.py` | End-to-end over a real socket: uploads a file, queues it as `accurate`, and asserts monotonic `INGESTION_PROGRESS` frames actually arrive on `/ws/global` and land on a `Completed` row. | ~90 s |

## Why these exist

`verify_ws_progress.py` was written *after* the bug it guards against was
fixed, and it immediately found a second one. The failure modes it covers
are both silent by construction:

- A callback whose arity does not match its caller, behind a bare
  `except Exception: pass`, produced a job whose database row advanced
  while exactly one WebSocket event was emitted.
- A registered-but-not-spinning event loop accepts scheduled coroutines
  and then never runs them, so the events vanish with no error anywhere.

Neither shows up in a unit test that only asserts the database row moved.
That is why `verify_ws_progress.py` asserts on what arrived on the socket,
and on *which loop* it arrived on.

`verify_ingestion_modes.py` guards a subtler regression: a profile can be
stored on the job row and shown in the UI while the pipeline ignores it.
The chunk-count assertions are what prove the knobs actually arrive.

The same file also guards the opposite failure — a profile that reaches the
pipeline but *fails*. `store_chunks` used to print and return `0`, which the
pipeline read as "this document had no text", so a broken index finished as
`Completed — 0 chunks` with the evidence marked `Indexed`. An investigator
then searches a case that holds nothing and concludes the evidence was clean.
The test forces the store to raise and asserts the job ends `Failed`, with a
reason and a terminal timestamp, and the evidence `Failed` rather than `Indexed`.

`verify_live_stack.py` exists because the first three all drive
`run_ingestion_with_progress` in-process. That proves the pipeline and the
broadcaster are correct, but *not* that uvicorn's own loop delivers the
frames to a real socket — which is exactly the seam the original bug lived
in. This is the only check that crosses it.

`verify_job_stop.py` and `verify_vector_store.py` exist for the same reason,
one session later. The Stop path was **read twice and looked correct end to
end** — endpoint, `threading.Event`, governor, `StopIteration` — and the
button was still useless, because the longest steps in the pipeline never
asked whether the operator had given up. Reading the code could not have
found that; the job had to be interrupted while it was genuinely working.

The same applies to the Qdrant client: `get_client(qdrant_path)` looked like
a cache, and reading it is how the `qdrant_path` argument being *ignored*
stayed invisible for so long. Only calling it with two different paths shows
that both calls return the same object.

Both scripts therefore assert on behaviour under motion — a stop that halts a
real thread mid-flight, chunks written into one case's storage and proven
absent from another's — rather than on the presence of a function call.

## Notes

- `verify_queue_api.py` registers a throwaway user and cleans up every row
  it creates. `/api/auth/login` takes an OAuth2 **form**, not JSON.
- `verify_live_stack.py` also registers a throwaway user, and it has to
  hard-delete its own case: the API's `DELETE /api/cases/{id}` is a *soft*
  delete (`status → Archived`), which is correct for chain of custody and
  wrong for a test. It registers an `atexit` hook so the case is removed on
  every exit path, including a failed assertion.
- TestClient's WebSocket blocks on `receive_json` with no timeout, which is
  why `verify_ws_progress.py` drives the real `ConnectionManager` from a
  worker thread against a real running loop instead. A socket-level test
  that hangs is worse than no test.
- `verify_ws_progress.py` should be run with
  `-W error::RuntimeWarning` to catch an un-awaited coroutine leaking on a
  scheduling failure path.
- Every script that touches a per-case Qdrant directory closes the client
  before deleting it. An open client holds an exclusive lock, so on Windows
  `shutil.rmtree` fails silently and the vector store outlives the case row.
- When polling a row a worker thread is writing, **roll the session back
  between reads.** A SQLAlchemy session holds its read transaction open until
  commit/rollback/close, so a naive poll loop re-reads one snapshot and
  reports the original value forever — it will watch a job run to completion
  and report 0 % throughout.

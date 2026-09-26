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
PYTHONPATH=. venv/bin/python tests/verify_live_stack.py   # needs the stack running

# Windows
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ingestion_modes.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ws_progress.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_queue_api.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_live_stack.py
```

The first three are self-contained. The fourth needs `ollama serve`, uvicorn on
`:8000` and the Vite dev server on `:3000` already running; it waits 90 s for
the backend and skips cleanly if it never comes up.

| Script | What it proves | Cost |
|---|---|---|
| `verify_ingestion_modes.py` | The three ingestion profiles reach the pipeline: same file ingested under `fastest` / `normal` / `accurate` yields 2 / 3 / 8 chunks, matching the configured `chunk_size` exactly. Progress is monotonic, ends at 100, and the profile is persisted on the job. Also asserts **a failed index is never reported as a success**. | ~15 s |
| `verify_ws_progress.py` | Ingestion progress reaches subscribers on the **server's** event loop — the exact defect that made live progress appear broken. Also asserts a strict 5-argument callback (the worker's shape) is honoured. | ~10 s |
| `verify_queue_api.py` | The queue API surface the frontend depends on: the three profiles, a device-derived budget with slider bounds, mode-aware estimates, limit validation, live settings on a running job. | ~5 s |
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

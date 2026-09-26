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

# Windows
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ingestion_modes.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ws_progress.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_queue_api.py
```

| Script | What it proves | Cost |
|---|---|---|
| `verify_ingestion_modes.py` | The three ingestion profiles reach the pipeline: same file ingested under `fastest` / `normal` / `accurate` yields 2 / 3 / 8 chunks, matching the configured `chunk_size` exactly. Progress is monotonic, ends at 100, and the profile is persisted on the job. | ~15 s |
| `verify_ws_progress.py` | Ingestion progress reaches subscribers on the **server's** event loop — the exact defect that made live progress appear broken. Also asserts a strict 5-argument callback (the worker's shape) is honoured. | ~10 s |
| `verify_queue_api.py` | The queue API surface the frontend depends on: the three profiles, a device-derived budget with slider bounds, mode-aware estimates, limit validation, live settings on a running job. | ~5 s |
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

## Notes

- `verify_queue_api.py` registers a throwaway user and cleans up every row
  it creates. `/api/auth/login` takes an OAuth2 **form**, not JSON.
- TestClient's WebSocket blocks on `receive_json` with no timeout, which is
  why `verify_ws_progress.py` drives the real `ConnectionManager` from a
  worker thread against a real running loop instead. A socket-level test
  that hangs is worse than no test.
- `verify_ws_progress.py` should be run with
  `-W error::RuntimeWarning` to catch an un-awaited coroutine leaking on a
  scheduling failure path.

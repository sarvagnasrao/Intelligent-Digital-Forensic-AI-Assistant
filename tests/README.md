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
PYTHONPATH=. venv/bin/python tests/verify_forensic_failure.py
PYTHONPATH=. venv/bin/python tests/verify_vector_store.py
PYTHONPATH=. venv/bin/python tests/verify_cpu_sampler.py
PYTHONPATH=. venv/bin/python tests/verify_gpu_telemetry.py
PYTHONPATH=. venv/bin/python tests/verify_eta.py
PYTHONPATH=. venv/bin/python tests/verify_service_health.py
PYTHONPATH=. venv/bin/python tests/verify_prompt_budget.py
PYTHONPATH=. venv/bin/python tests/verify_evidence_archive.py
PYTHONPATH=. venv/bin/python tests/verify_retrieval_integrity.py
PYTHONPATH=. venv/bin/python tests/verify_identity_attribution.py
PYTHONPATH=. venv/bin/python tests/verify_live_stack.py   # needs the stack running

# Windows
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ingestion_modes.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_ws_progress.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_queue_api.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_job_stop.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_forensic_failure.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_vector_store.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_cpu_sampler.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_gpu_telemetry.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_eta.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_service_health.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_prompt_budget.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_evidence_archive.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_retrieval_integrity.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_identity_attribution.py
$env:PYTHONPATH="."; venv\Scripts\python.exe tests\verify_live_stack.py
```

Fourteen are self-contained — **941 assertions** (9 + 15 + 17 + 17 + 19 + 36 +
38 + 45 + 52 + 59 + 86 + 153 + 171 + 209). `verify_live_stack.py` is the
exception and needs `ollama serve`, uvicorn on `:8000` and the Vite dev server
on `:3000` already running; it waits 90 s for the backend and skips cleanly if
it never comes up.

Read the totals, not the exit code. A gate that reports `0 passed` for a script
which did not run converts a red suite green, which is the one outcome these
scripts exist to prevent.

> **Stop the backend before running the self-contained ones.** A live server on
> the same `data/forensic.db` runs its own worker thread, and that worker
> selects `Queued` jobs — so a fixture left in `Queued` gets executed in a
> second process, which then loses the race for the same per-case Qdrant
> directory and fails with `Storage folder ... is already accessed by another
> instance of Qdrant client`. These scripts insert fixture jobs as `Running`
> for exactly that reason (the worker only ever selects `Queued`), but they
> also share the database with anything you have running.
>
> **Four of them drive the app through `with TestClient(app)`, which runs the
> FastAPI lifespan — so they start a worker thread of their own** that selects
> `Queued` jobs. `verify_queue_api.py` stopped one explicitly after this bit
> it; see the Notes.

| Script | What it proves | Cost |
|---|---|---|
| `verify_ingestion_modes.py` | The three ingestion profiles reach the pipeline: the same file ingested under `fastest` / `normal` / `accurate` yields a chunk count matching `ceil(len / (chunk_size − overlap))` — the *stride*, not the chunk size, which is what the chunker actually advances by. Progress is monotonic, ends at 100, and the profile is persisted on the job. Also asserts **a failed index is never reported as a success**. | ~15 s |
| `verify_prompt_budget.py` | The prompt fits the window Ollama is actually *serving*, not the one it was trained for. These are different numbers (131072 vs 4096 on this box) and conflating them is the whole bug. Asserts `num_ctx` is on the wire and equals the clamped requested value, that the budget and the request derive from the same figure, the two truncation guards behave differently, that a fixed `seed` reaches the wire so the same question gets the same answer twice, and that a model refusal is caught as a missing answer rather than filed as a response. Touches the network: it reads `/api/tags`, `/api/show` and `/api/ps` for real, because the claim under test is what an *operator* can see. | ~30 s |
| `verify_evidence_archive.py` | Archiving must **mean** something. The write was always correct; the read was the lie — archived rows stayed in the default listing, so the operation relabelled rather than hid. Asserts archived items disappear by default and reappear only behind the disclosure, that restore sets `Uploaded` and never `Indexed` (restoring to `Indexed` would recreate the "searchable but empty" defect), that the Qdrant delete is fatal to the archive rather than logged and non-fatal, that `chunk_count` is zeroed because four readers trust it, and that the three refusals (mid-ingest, a Viewer, a failed cleanup) each return their own code. | ~15 s |
| `verify_retrieval_integrity.py` | A **failed** search is not an empty one. `search_chunks` returned `[]` on error, which the RAG engine read as "nothing in this case matched" — the exculpatory direction, and it told an investigator in the app's own voice that the evidence against a suspect was not there. Asserts a search failure raises, that the answer says nothing has been ruled out, and that when the search *succeeds* but the relevance floor drops everything the model is never consulted at all. Also pins the floor between the two measured clusters in `query_logs.chunks_used`, so moving it outside the gap fails. | ~15 s |
| `verify_identity_attribution.py` | Four fields looked editable and were not. The investigator could type a name into "Investigator Name", "Author", "Officer name" and "Prepared By", and the server stored whatever they typed — so a note, a report or a case could be attributed to any other user, including an Admin, and the audit log would agree. Forges `"admin"` in a request body and requires the database to say otherwise, then sweeps the routers for any remaining client-supplied identity field. | ~10 s |
| `verify_ws_progress.py` | Ingestion progress reaches subscribers on the **server's** event loop — the exact defect that made live progress appear broken. Also asserts a strict 5-argument callback (the worker's shape) is honoured. | ~10 s |
| `verify_queue_api.py` | The queue API surface the frontend depends on: the three profiles, a device-derived budget with slider bounds, mode-aware estimates, limit validation, live settings on a running job. Also asserts the **settings endpoint never reports success for something it did not do** — a profile change on a `Running` job is refused *and leaves the stored column untouched*, CPU/RAM stay editable while running, an empty body is refused, and a `Stopped` job is still listed in `/queue/list` and `/queue/history` and can be re-queued with its profile carried forward. | ~5 s |
| `verify_job_stop.py` | The Stop button actually stops. Drives the real `_process_job` on a worker thread, fires `stop_job()` from another thread exactly as the endpoint does, and requires that the job halts, is recorded `Stopped` rather than `Failed`, reverts the evidence to `Uploaded`, and **did not reach 100 %** — a stop that is acknowledged but ignored is otherwise indistinguishable from a job that simply finished. Also pins the HTTP contract, including that `DELETE /queue/{id}/cancel` still refuses a `Running` job. | ~20 s |
| `verify_forensic_failure.py` | A failed **disk-image** ingest must be terminal and must never announce success. Drives the real `_process_job` on a worker thread with an image that has no mountable filesystem, and requires the job `Failed` with the TSK diagnostic and a terminal timestamp, the evidence `Failed` (never `Indexed`), `INGESTION_FAILED` broadcast **and `INGESTION_COMPLETE` not**. Part B requires a user stop inside the walk loop to reach the caller *as a `StopIteration`* — not laundered into a `RuntimeError` and reclassified by substring match — leaving the job `Stopped` and the evidence re-queueable. | ~30 s |
| `verify_vector_store.py` | One Qdrant client **per case**, keyed on a normalised path, with real data isolation: indexing case B leaves case A's storage untouched. Plus the optional-dependency contract — `backend.main` and `backend.ingestion` import with `torch` and `sentence_transformers` blocked, and a stop request surfaces as `StopIteration` rather than an indexing failure. | ~10 s |
| `verify_live_stack.py` | End-to-end over a real socket: uploads a file, queues it as `accurate`, and asserts monotonic `INGESTION_PROGRESS` frames actually arrive on `/ws/global` and land on a `Completed` row. | ~90 s |
| `verify_cpu_sampler.py` | The CPU figure is a real measurement, not a primed constant. Burns all logical cores in **subprocesses** and requires the reported load to climb and then fall, and pins the forced re-scan's worst case below the 300 ms the old blocking sampler cost on every cache miss. | ~10 s |
| `verify_gpu_telemetry.py` | The NVML ABI, end to end. Each entry point gets its own struct and the version handshake; the 32-bit misread is *refused*; a field-order misread is *refused*; both `used` conventions are accepted and normalised; the VRAM ratio divides by a denominator covering the same adapters as its numerator; sysfs byte values are converted; a failed NVML session recovers; and no unmeasurable metric ever becomes `0`. | ~20 s |
| `verify_eta.py` | The live countdown. `elapsed_seconds` was a column nothing ever wrote, so every running job reported `0` — indistinguishable from one that had just started. Drives `EtaTracker` with an injected fake clock and requires: the estimate is `None` (never `0`) when there is neither a prior nor a measurement; `0` only at 100 %; a clean run counts down monotonically; the blend beats naive `elapsed / percent * 100` on an uneven-band job; governor pauses lengthen the quote without exploding it; a drop from 100 % is a restart and reports `None`, not a false `0`; and hostile input (`None`, `"abc"`, `NaN`, `-5`, `500`, a backwards pause counter) never raises. | <1 s |
| `verify_service_health.py` | The measured health behind `GET /api/status` — the endpoint that used to report fiction, with `database` as `os.path.exists()` presented as connectivity and `ollama` as "running" whenever `/api/tags` answered 200 (which it does with an *empty* model list, so a machine that had never pulled a model reported a healthy AI). It runs all six probes against throwaway databases and temporary case trees, and asserts the module's own rule in every direction that matters: a metric that cannot be measured is `None` plus a reason and never a fabricated `0`, `False` or `"ok"`; `state` separates *measured and broken* from *could not measure*; a probe that raises degrades to `unavailable` for that service alone and leaves the other five measured; and the legacy keys `database`, `ollama`, `models` and `cases_dir` — still read by `Sidebar.jsx` — can never be fabricated healthy. It also pins the two fixtures that most easily stop discriminating: the `_MISSING` sentinel (a worker that has never started must not read as "not introspectable") and the bounded directory walk (exceeding the cap yields *no* total, not a partial one). Self-contained and safe to re-run: every assertion points `backend.database.engine` at a throwaway file and the run asserts afterwards that `data/forensic.db` was never opened. It cannot exercise the real worker loop, since that only starts in the FastAPI lifespan — so the no-heartbeat gap (a wedged worker still reads `ok`) stays unproven here. | ~25 s |

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

`verify_gpu_telemetry.py` exists because the NVML binding is the one place in
the project where **the compiler is not checking anything**. A wrong struct
width, a shared `_vN` buffer, or a field order declared backwards all produce a
struct the right size that the driver fills without complaint, and the first two
return `SUCCESS` while doing it. Reading the code cannot find these, because the
code is correct *as written* and wrong *as ABI*. They have to be measured, and
the guards deliberately assert the traps **still exist on this driver** first, so
a guard cannot quietly become decorative if the driver ever changes.

Three lessons from writing it, all of which are ways to write a test that passes
while the behaviour is wrong:

- **A fixture must be able to discriminate.** The VRAM-denominator bug only
  shows when the *unmeasured* adapter has a non-zero total; with a `0`-total
  unmeasured card both denominators are equal and the assertion passes for the
  wrong reason. Prefer a fixture that would fail if the fix were reverted.
- **Prefer outcomes to spies.** An early version asserted `force=True` reached an
  internal call, which would still pass if the rescan path were never wired to
  it. Force a failed session, rescan, require the reading back.
- **`ctypes.Structure` subclassing appends; it does not reorder.** The
  misordered-struct guard has to declare a *standalone* struct, or it is 80
  bytes and silently tests nothing.

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
- Live metrics are **live**. Compare utilisation and VRAM-used with a tolerance,
  never for exact equality against a separately-timed read. `vram_total_mb` *is*
  compared exactly — it is a stable per-adapter constant, and neither a
  mis-joined reading nor a truncated struct produces 4096 by accident.
- Ground truth must come from the **same NVML version** as the code under test.
  v1 folds the driver's reserved region into `used` and v2 reports it separately;
  comparing the probe's v2 reading against a v1 ground truth showed a 92 MB
  discrepancy that was a definition difference, not a bug.
- `x or -1` is a bug in a percentage range check: an idle GPU reports `0` and
  `0 or -1` is `-1`. This appeared twice in this suite, including inside the
  test guarding the null-vs-zero contract. Use an explicit `is not None`.
- Simulating a failed NVML session must also set `_failed_at = time.monotonic()`.
  Failure is no longer terminal, so a failure with no timestamp is one whose
  backoff has already expired — and the next sample re-initialises and succeeds.
- **Assert at the boundary you changed, not the one that is supposed to absorb.**
  `job_worker._process_job` is the *terminal* handler: it catches, marks the row and
  broadcasts, and returns normally by design. A test asserting that it re-raises is
  wrong, and it would prove nothing about the re-raise one layer down. Drive
  `run_ingestion_with_progress` directly for that.
- **Never assert a ratio band over a device-derived number.** `ram_floor_max_mb` is
  free RAM rounded down to a whole GB, so with 2047 MB free the ceiling is 1024, a
  ratio of 0.50. A test asserting "70-100% of free" passed on one run and failed on
  the next for no reason but a different amount of free memory, which reads exactly
  like a regression. Pin the formula instead; a hardcoded 8192 still fails it.
- An assertion on an exception's **type** beats one on its message. A stop sentinel
  wrapped as `RuntimeError("Mount failed: ... stopped by user ...")` still produced
  the right outcome, because the handler above classified it by substring match. The
  test passed for the wrong reason until it checked `isinstance(..., StopIteration)`.
- **Entering `with TestClient(app)` runs the FastAPI lifespan, which starts the
  ingestion worker.** `verify_queue_api.py` asserted a 200 on a `PATCH` against a
  job it had just queued, and failed on some runs and not others: the worker picks
  up `Queued` jobs on a 2 s poll, so if it started the job first the status was
  `Running` and refusing a profile change was the *correct* behaviour. The product
  was right and the assertion lost a race. It now calls `job_worker.stop_worker()`
  and joins the thread — **inside** the `with`, since the lifespan runs on entry.
  An assertion that depends on timing is a measurement that reports success
  without measuring anything.
- `tests/_purge.py` deletes the rows a run created, from an `atexit` hook, so it
  fires on a failed assertion as well as a clean one. The four TestClient suites
  each used to delete their case and evidence at the end of the happy path with
  no `finally` and **never deleted the registered user** — measured at 92 accounts
  and 249 orphaned audit rows in `data/forensic.db`. Note that audit rows carry
  the **username** in `performed_by`, not the user id, so the filter has to match
  on the name or it deletes nothing while appearing to work.
- When a suite writes a **summary**, the gate parses it, so it has to be
  unambiguous. `verify_prompt_budget.py` prints `85 passed, 0 failed` while most
  others print `PASSED: 85    FAILED: 0`; a parser matching only one form reads
  `0` for the other, which turns a red suite green. A suite whose counts cannot be
  read **fails the gate** rather than being skipped.
- **When you verify a guard by reverting the fix, check that the revert
  actually happened.** A scripted revert that matches nothing leaves the file
  unchanged, so the suite runs twice against identical code and reports
  `passes with the fix, passes without it` — which is exactly what a guard that
  cannot fail looks like. This bit `verify_prompt_budget.py` J8 for real: the
  revert string ended in `\n` against a CRLF file, `assert PATTERN in original`
  passed anyway (it only proves the fix existed), and the first verdict was
  "GUARD IS DECORATIVE". It was not. Assert on the **absence** of the change
  after reverting, and check that the failure names the reverted behaviour.
  AGENTS.md §28, TRAP 12.
- A guard that reads a **configuration value** must be checked against the wire,
  not against `settings`. The seed assertion is `payload.options.seed ==
  settings.ollama_seed`, because a value sitting in config proves nothing about
  what Ollama receives — that was B27, a knob that only fed arithmetic.

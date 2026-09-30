"""
Measured service health behind `GET /api/status`.

Why this module exists
----------------------
`system_status()` used to answer with three things, and two of them were
fiction:

* `database` was `os.path.exists("./data/forensic.db")` reported as the
  string "connected". File existence is not connectivity. A corrupt,
  locked, read-only or truncated database file exists perfectly happily
  and was reported as "connected" — and it hardcoded the path, so it was
  reporting on `./data/forensic.db` even when `DATABASE_URL` pointed
  somewhere else entirely.
* `ollama` was "running" whenever `/api/tags` answered 200. Ollama answers
  200 with an EMPTY model list on a machine that has never pulled a
  model, so a green "running" sat next to an assistant that could not
  say a word. That distinction already exists in
  `ollama_client.ollama_diagnostic()`; this module imports that function
  rather than re-implementing the probe, so there is exactly one place
  that knows what "the AI can answer" means.

The invariant every probe here obeys (AGENTS.md §16)
-----------------------------------------------------
**A metric that cannot be measured is `None` plus a reason, never a
fabricated `0`, `False` or "ok".** This is the same silent-success
defect class as B1 (a truncated disk image reported "0 artifacts"),
B10 (a failed index reported "0 chunks") and B16 (a profile change
reported `ok: true` having changed nothing). A fabricated healthy
reading is worse than no reading, because the System Health page is the
one surface an operator trusts when something is wrong.

Consequently:
* a probe that cannot run reports `state: "unavailable"` and a `reason`,
  and leaves its measured fields `None`;
* a probe that runs and finds a problem reports `state: "error"` and
  keeps the measurement that proves it (latency, count, path);
* only a probe that actually measured it says `state: "ok"`.

And a probe failure must never fail the health response: each service
is probed inside its own guard, and the aggregate has a second guard on
top, so one broken probe degrades to one grey card rather than a 500
that hides the other five.

`state` vocabulary: `"ok"` | `"error"` | `"unavailable"`.
`"error"` means "measured, and it is broken". `"unavailable"` means
"could not be measured, or is not present here" — an unknown, not a
fault. They are different answers and the UI must be able to tell them
apart.

Latent traps this module is written around
------------------------------------------
* `SELECT 1` does **not** touch a SQLite file. It is answered entirely
  from the connection, so a corrupt or truncated database passes it
  happily. Connectivity is therefore probed with `SELECT 1` *and* proven
  with a real read of the `cases` table, taken from the ORM's own table
  object so the table name cannot drift out of sync with `models.py`.
* Qdrant's embedded mode takes an **exclusive lock** on each storage
  directory (AGENTS.md §15, B14). The vector store is therefore probed
  from the filesystem only — this module never constructs a
  `QdrantClient`, because a health page that opened one would fight the
  running app for the lock and produce "Storage folder ... is already
  accessed by another instance".
* `torch` and `sentence_transformers` are **lazy** optional imports
  (B15): the backend must start without them, so they must be probed
  with `importlib.util.find_spec`, which resolves the module without
  executing it. Importing torch here would cost seconds of startup and
  hundreds of MB of RSS to learn something the spec can answer.
* The per-case vector store lives at `data/cases/<case_id>/qdrant/`
  (AGENTS.md §2/§9). It is NOT `data/qdrant_store` — that path does not
  exist, and the System Health page used to advertise it to the user.
"""

import importlib.util
import os
import tempfile
import time
from datetime import datetime

STATE_OK = "ok"
STATE_ERROR = "error"
STATE_UNAVAILABLE = "unavailable"

# The sentence embedding model actually used by
# vector_store.get_ollama_embeddings(). The *dimensionality* is not
# restated here - it is read from vector_store.VECTOR_SIZE at probe time
# so the two cannot drift. Hardcoding 384 a second time is how a health
# page ends up reassuring you about the wrong vector size.
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"

# Sentinel for "this module does not expose that attribute at all",
# kept distinct from a legitimate None. See probe_worker.
_MISSING = object()

# Upper bound on files stat'ed when sizing the per-case vector stores.
# A case with 100k indexed chunks can hold 100k+ files, and this runs
# from an endpoint the UI polls every 15 s. Past the cap the size is
# reported as unknown (None + reason) rather than as a partial total
# dressed up as a real one.
_MAX_WALK_FILES = 200_000


# ── helpers ─────────────────────────────────────────────────────────────────

def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _abspath(path: str) -> str:
    """Display form of a configured path (handles './data/cases')."""
    if not path:
        return path
    if path.startswith(":") and not os.path.exists(path):
        # In-memory / shared-cache SQLite DSNs are not filesystem paths.
        return path
    return os.path.abspath(path)


def _canonical_base() -> str:
    """
    Where the vector store is written to now, for display in a reason string.

    Never raises. This only ever builds a human-readable sentence, and a probe
    that raises while explaining itself would replace an honest measurement
    with an exception -- strictly worse than naming no path.
    """
    try:
        from backend.modules.vector_store import resolve_qdrant_dir
        return _abspath(resolve_qdrant_dir())
    except Exception:
        return "the configured Qdrant directory"


def _probe_writable(path: str):
    """
    Real writability test: create a file in `path`, write to it, remove it.

    `os.access(path, os.W_OK)` is not good enough. It answers for the
    real uid rather than the effective one, it cannot see a full disk, and
    on Windows it mostly reflects the read-only attribute - none of which
    is the question being asked. The question is "can the app write here
    right now", and the only honest way to answer that is to try.

    Returns (writable: bool, reason: str | None).
    """
    fd = None
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(
            prefix=".idfa-health-", suffix=".tmp", dir=path
        )
        os.write(fd, b"0")
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                # Best effort. A file we cannot delete is itself worth
                # knowing about, but not worth masking the real answer.
                pass


# ── probes ──────────────────────────────────────────────────────────────────

def probe_database() -> dict:
    """
    Executes a real query through the app's own engine.

    `SELECT 1` proves the connection; `SELECT count(*) FROM cases`
    proves the file. Only the second one fails on a corrupt or truncated
    database, so only the second one can honestly say "connected".
    """
    out = {
        "state": None,
        "detail": "",
        "latency_ms": None,
        "reason": None,
        "dialect": None,
        "path": None,
        "case_rows": None,
    }

    try:
        from sqlalchemy import func, select, text
        from backend import models
        from backend.database import engine
    except Exception as e:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = "The database layer could not be imported."
        out["reason"] = f"{type(e).__name__}: {e}"
        return out

    try:
        url = engine.url
        out["dialect"] = getattr(url, "drivername", None) or None
        raw = getattr(url, "database", None)
        if raw:
            out["path"] = _abspath(raw)
    except Exception:
        # Cosmetic only - never let a URL we cannot render turn into a
        # failed health check.
        pass

    started = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1")).scalar()
            rows = conn.execute(
                select(func.count()).select_from(models.Case.__table__)
            ).scalar()
    except Exception as e:
        out["state"] = STATE_ERROR
        out["latency_ms"] = round(
            (time.perf_counter() - started) * 1000, 3)
        out["detail"] = (
            "The database at "
            f"{out['path'] or 'the configured URL'} did not answer a real "
            "read of the cases table."
        )
        out["reason"] = f"{type(e).__name__}: {e}"
        return out

    out["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    out["case_rows"] = int(rows) if rows is not None else None
    out["state"] = STATE_OK
    out["detail"] = (
        f"{out['dialect'] or 'database'} answered a real read of the "
        f"cases table in {out['latency_ms']} ms "
        f"({out['case_rows']} case rows)."
    )
    return out


def probe_ollama() -> dict:
    """
    Delegates to ollama_client.ollama_diagnostic().

    "Ollama is up" and "there is a model to answer with" are two
    different facts and the UI needs both. The diagnostic already
    separates them and already follows the None-not-False rule, so it is
    imported rather than re-implemented - duplicating the probe is how
    the two copies start disagreeing.
    """
    out = {
        "state": None,
        "detail": "",
        "model": None,
        "model_ready": None,
        "installed_models": None,
        "reason": None,
        "latency_ms": None,
    }

    started = time.perf_counter()
    try:
        from backend.modules.ollama_client import ollama_diagnostic
    except Exception as e:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = "The Ollama client could not be imported."
        out["reason"] = f"{type(e).__name__}: {e}"
        return out

    try:
        diag = ollama_diagnostic()
    except Exception as e:
        out["state"] = STATE_UNAVAILABLE
        out["latency_ms"] = round(
            (time.perf_counter() - started) * 1000, 3)
        out["detail"] = "The Ollama diagnostic itself failed."
        out["reason"] = f"{type(e).__name__}: {e}"
        return out

    out["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    out["model"] = diag.get("configured_model")
    out["model_ready"] = diag.get("model_ready")
    out["installed_models"] = diag.get("installed_models")
    out["reason"] = diag.get("reason")

    running = diag.get("running")
    base = diag.get("base_url")

    if running is None:
        # The probe itself could not complete. running is tri-state and
        # None means "we do not know", not "down".
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = f"Ollama could not be reached at {base}."
        return out

    if not running:
        out["state"] = STATE_ERROR
        out["detail"] = f"Ollama is not serving at {base}."
        return out

    if out["model_ready"] is True:
        installed = out["installed_models"] or []
        out["state"] = STATE_OK
        out["detail"] = (
            f"Serving {out['model']} from {base} "
            f"({len(installed)} model(s) installed)."
        )
        return out

    if out["model_ready"] is None:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = (
            f"Ollama is up at {base} but whether '{out['model']}' is "
            "usable could not be determined."
        )
        return out

    # Up, but nothing to answer with. This is the case the old endpoint
    # called "running".
    out["state"] = STATE_ERROR
    out["detail"] = (
        f"Ollama is up at {base} but '{out['model']}' is not installed, "
        "so the assistant cannot answer."
    )
    return out


def _sum_dir_bytes(path: str, budget: list):
    """
    Total size of a directory tree.

    `budget` is a single-element list holding the remaining file count; it
    is shared across the whole probe so one enormous case cannot make the
    health endpoint crawl. Returns (bytes, exhausted, skipped).

    `skipped` is reported, not swallowed: a file that cannot be stat'ed
    (deleted by the worker mid-walk) makes the total a lower bound, and
    saying so is the difference between an honest number and a quiet
    understatement.
    """
    total = 0
    skipped = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            if budget[0] <= 0:
                return total, True, skipped
            budget[0] -= 1
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                skipped += 1
    return total, False, skipped


def probe_vector_store(cases_dir: str) -> dict:
    """
    Reports the per-case Qdrant stores from the filesystem.

    Deliberately does **not** open a QdrantClient: embedded mode holds an
    exclusive lock per storage directory (B14), so a health page that
    opened one would collide with the running application. Counting
    directories is both safe and what the operator actually wants to know
    ("how much evidence is indexed, and where").

    `cases_in_db` is filled in by collect_status() from the database
    probe - a filesystem count alone cannot tell you that 21 collections
    on disk belong to 4 cases in the database.
    """
    out = {
        "state": None,
        "detail": "",
        "case_collections": None,
        "total_size_mb": None,
        "reason": None,
        "cases_total": None,
        "cases_in_db": None,
        "writable": None,
        "size_walk_ms": None,
        "unmigrated_collections": None,
        "duplicate_collections": None,
    }

    if not cases_dir:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = "No cases directory is configured."
        out["reason"] = "settings.cases_dir is empty."
        return out

    if not os.path.isdir(cases_dir):
        # Not "0 collections". Nothing was counted, because there was
        # nothing there to count.
        out["state"] = STATE_ERROR
        out["detail"] = (
            f"The cases directory {_abspath(cases_dir)} does not exist, "
            "so no case index can exist either."
        )
        out["reason"] = "cases_dir is missing."
        return out

    started = time.perf_counter()
    try:
        entries = os.listdir(cases_dir)
        case_dirs = [e for e in entries
                     if os.path.isdir(os.path.join(cases_dir, e))]
    except Exception as e:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = f"The cases directory {_abspath(cases_dir)} could not be listed."
        out["reason"] = f"{type(e).__name__}: {e}"
        return out

    out["cases_total"] = len(case_dirs)

    # Local import, matching probe_embeddings below: vector_store pulls in
    # the embedding stack, and a health page must not pay for it (or fail)
    # just to count directories. Without this the probe raised NameError
    # and the card reported `unavailable` on every machine.
    from backend.modules.vector_store import case_qdrant_path

    # A case's index has TWO legitimate homes, and this probe has to know
    # about both or it reports a fabricated zero.
    #
    # `case_qdrant_path()` is the single source of truth for where an index
    # lives, but it deliberately takes only a case_id: it resolves against the
    # global settings, because that is where the *writer* looks. When the cases
    # directory sits on a slow disk, resolve_qdrant_dir() relocates the whole
    # store elsewhere, so `case_qdrant_path(case_id)` can point at a completely
    # different tree from the directory this function was just handed.
    #
    # That is not hypothetical. This probe used to call case_qdrant_path() and
    # nothing else, so given any directory other than settings.cases_dir it
    # found zero indexes and reported "0 of N case directories hold a Qdrant
    # index" while the indexes sat right there. Fifteen assertions in
    # verify_service_health.py caught it.
    #
    # So: the in-cases location is derived from the directory actually being
    # probed, the canonical location from the writer, and a case counts as
    # indexed if EITHER exists. The second case -- an index in both places --
    # is a real defect that migrate_qdrant_layout() refuses to paper over by
    # overwriting, so it is named rather than silently collapsed.
    unmigrated = 0
    duplicated = 0
    qdrant_dirs = []
    for case_dir in case_dirs:
        legacy = os.path.join(cases_dir, case_dir, "qdrant")
        try:
            canonical = case_qdrant_path(case_dir)
        except Exception:
            # Cannot ask the writer where it would put this one. The in-cases
            # location is still checkable, so a resolver fault must not
            # downgrade to "no index here".
            canonical = None

        has_legacy = os.path.isdir(legacy)
        has_canonical = bool(canonical) and os.path.isdir(canonical)
        if has_legacy and has_canonical:
            duplicated += 1
        elif has_legacy:
            unmigrated += 1
        elif has_canonical:
            pass
        else:
            continue

        # Only the canonical path is walked when both exist: they are two
        # copies of one index, and summing both would double-count it. The
        # duplication is reported separately instead.
        qdrant_dirs.append(canonical if has_canonical else legacy)

    out["case_collections"] = len(qdrant_dirs)

    # Whether an index is in the "wrong" place is only a question about *this
    # machine's* configured layout. The probe accepts any directory -- a test
    # hands it a temporary tree -- and comparing a caller's directory against
    # the global resolver would publish a migration verdict about a location
    # this machine does not use. That is the same fabrication as reporting a
    # count for a directory that was never measured, one level up.
    #
    # So on a directory that is not the configured root, the split is reported
    # as None -- "not applicable" -- rather than as 0. Zero would be a claim
    # that this tree is fully migrated, and for a tree that is not the real one
    # that claim means nothing.
    try:
        from backend.dependencies import get_settings
        _configured = get_settings().cases_dir or "."
    except Exception:
        _configured = "."
    is_configured_root = os.path.normcase(os.path.abspath(cases_dir)) == \
        os.path.normcase(os.path.abspath(_configured))

    # A warning appended here is an ERROR (`reason` is set -> the service is
    # degraded). On a tree that is not this machine's there is nothing wrong to
    # report, so `apply` is what keeps the prose out of the degraded path.
    # Decided once, here, and consumed once, in the reason block -- see below.
    notes = []
    if is_configured_root:
        out["unmigrated_collections"] = unmigrated
        out["duplicate_collections"] = duplicated
        if unmigrated:
            # Not a tidiness note. Every reader resolves through
            # case_qdrant_path(), and get_client() *creates* the directory it
            # is handed -- so a case indexed only in-cases gets a brand new,
            # empty collection on the next query and returns nothing at all.
            # That is the B14/§15 silent-empty failure, arrived at from the
            # filesystem side, and it is worth saying in those terms.
            notes.append(
                f"{unmigrated} case index/indices sit inside the cases "
                f"directory rather than at {_canonical_base()}. Searches read "
                "only the latter, so those cases will return no results until "
                "migrate_qdrant_layout() runs"
            )
        if duplicated:
            notes.append(
                f"{duplicated} case(s) have an index in BOTH locations; the "
                "total counts the canonical copy only"
            )
    else:
        out["unmigrated_collections"] = None
        out["duplicate_collections"] = None
        # Both the numbers and the prose come from the branch above, never from
        # the raw locals. The first attempt gated only the dict and left
        # `if unmigrated:` reading the raw local, so one response said
        # "not applicable" in the field and "1 un-migrated index" in the
        # sentence, for the same tree.

    budget = [_MAX_WALK_FILES]
    total = 0
    exhausted = False
    skipped = 0
    for path in qdrant_dirs:
        size, hit_cap, missed = _sum_dir_bytes(path, budget)
        total += size
        skipped += missed
        if hit_cap:
            exhausted = True
            break

    out["size_walk_ms"] = round((time.perf_counter() - started) * 1000, 1)
    if not exhausted:
        out["total_size_mb"] = round(total / (1024 * 1024), 2)

    writable, why = _probe_writable(cases_dir)
    out["writable"] = writable

    reasons = []
    if exhausted:
        out["total_size_mb"] = None
        reasons.append(
            f"on-disk size not measured: the walk exceeded "
            f"{_MAX_WALK_FILES} files"
        )
    elif skipped:
        reasons.append(
            f"{skipped} file(s) could not be measured, so the total is "
            "a lower bound"
        )
    # The migration notes, built above where the verdict was actually decided,
    # plus a legibility hint when one exists and the size below is a lower
    # bound. Silent under-reporting is what made this probe untrustworthy in
    # the first place.
    reasons.extend(notes)
    if skipped and notes:
        reasons.append(
            "the size above is a lower bound, and does not include an "
            "un-migrated index when the canonical copy was the one walked"
        )
    if not writable:
        reasons.append(f"the directory is not writable ({why})")

    indexed = f"{len(qdrant_dirs)} of {len(case_dirs)} case directories hold a Qdrant index"
    size_txt = (
        f"{out['total_size_mb']} MB total"
        if out["total_size_mb"] is not None
        else "size unknown"
    )
    out["detail"] = f"{indexed}; {size_txt}; {_abspath(cases_dir)}"

    if reasons:
        out["state"] = STATE_ERROR if not writable else STATE_UNAVAILABLE
        out["reason"] = "; ".join(reasons)
    else:
        out["state"] = STATE_OK
    return out


def probe_worker() -> dict:
    """
    Liveness of the ingestion worker thread.

    Read from job_worker's own module state. The module is imported
    lazily and never `start_worker()`-ed here: this function runs from a
    request handler, and a health page that started the worker to check on
    it would be indistinguishable from the bug it is meant to detect.

    The flag and the thread are checked separately because they can
    disagree, and the disagreement is the whole point. `_worker_running`
    is only ever set False by stop_worker(); the loop catches its own
    exceptions, so the thread outliving the flag is the expected
    shutdown, but the flag outliving a dead thread means the queue will
    never drain again while every caller still reads "running".
    """
    out = {
        "state": None,
        "detail": "",
        "reason": None,
        "thread_alive": None,
        "running_flag": None,
    }

    try:
        from backend.modules import job_worker
    except Exception as e:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = "The worker module could not be imported."
        out["reason"] = f"{type(e).__name__}: {e}"
        return out

    thread = getattr(job_worker, "_worker_thread", _MISSING)
    flag = getattr(job_worker, "_worker_running", _MISSING)
    if thread is _MISSING or flag is _MISSING:
        # A rename in job_worker must degrade to an honest "unknown", not
        # a crash inside the health endpoint.
        #
        # The sentinel is required rather than `thread is None`: before
        # start_worker() runs, _worker_thread IS None and
        # _worker_running IS False, and those are ordinary values
        # meaning "not started" - not evidence that the state is
        # unreadable. Testing for None here reported a perfectly
        # introspectable worker as unreadable in every process where the
        # lifespan had not run.
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = "The worker's liveness state is not introspectable."
        out["reason"] = (
            "job_worker exposes neither _worker_thread nor "
            "_worker_running; the health check cannot see whether the "
            "queue is being drained."
        )
        return out

    alive = bool(thread.is_alive()) if hasattr(thread, "is_alive") else None
    out["thread_alive"] = alive
    out["running_flag"] = bool(flag)
    name = getattr(thread, "name", "ingestion-worker")

    if thread is None:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = (
            "No ingestion worker thread exists in this process, so "
            "nothing will drain the queue."
        )
        out["reason"] = (
            "start_worker() has not run; the FastAPI lifespan starts it."
        )
        return out

    if alive is None:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = "The worker thread object is not a thread."
        out["reason"] = f"_worker_thread is a {type(thread).__name__}."
        return out

    if not alive and flag:
        out["state"] = STATE_ERROR
        out["detail"] = (
            f"The worker thread '{name}' is dead but the worker is still "
            "flagged as running, so queued jobs will never be picked up."
        )
        return out

    if not alive:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = (
            "The ingestion worker is not running in this process, so "
            "nothing will drain the queue."
        )
        out["reason"] = "start_worker() has not been called (or was stopped)."
        return out

    if not flag:
        # The only way to observe this is during shutdown, when the loop
        # is between iterations and will exit at the top of the next one.
        out["state"] = STATE_OK
        out["detail"] = (
            f"The worker thread '{name}' is alive but a stop has been "
            "requested; it is shutting down."
        )
        return out

    out["state"] = STATE_OK
    out["detail"] = f"The ingestion worker thread '{name}' is alive and polling."
    return out


def probe_cases_dir(cases_dir: str) -> dict:
    """
    Exists *and* writable.

    `os.path.exists` was the whole of the old check, which is why a
    read-only evidence volume — the one condition that matters most on a
    forensic workstation — was reported as fine until an ingest died
    mid-write.
    """
    out = {
        "state": None,
        "detail": "",
        "reason": None,
        "path": None,
        "writable": None,
        "case_dirs": None,
    }

    if not cases_dir:
        out["state"] = STATE_UNAVAILABLE
        out["detail"] = "No cases directory is configured."
        out["reason"] = "settings.cases_dir is empty."
        return out

    path = _abspath(cases_dir)
    out["path"] = path

    if not os.path.isdir(path):
        out["state"] = STATE_ERROR
        out["detail"] = f"The evidence directory {path} does not exist."
        out["reason"] = "cases_dir is missing."
        return out

    writable, why = _probe_writable(path)
    out["writable"] = writable

    try:
        out["case_dirs"] = len([
            e for e in os.listdir(path)
            if os.path.isdir(os.path.join(path, e))
        ])
    except Exception:
        out["case_dirs"] = None

    if not writable:
        out["state"] = STATE_ERROR
        out["detail"] = f"The evidence directory {path} is not writable."
        out["reason"] = why
        return out

    out["state"] = STATE_OK
    out["detail"] = (
        f"{path} exists and accepts writes "
        f"({out['case_dirs']} case director"
        f"{'y' if out['case_dirs'] == 1 else 'ies'})."
    )
    return out


def _hf_cache_roots() -> list:
    """
    The documented on-disk locations SentenceTransformers resolves a
    model name to, in the order it searches them.
    """
    home = os.path.expanduser("~")
    roots = []
    for env in ("SENTENCE_TRANSFORMERS_HOME", "HF_HUB_CACHE",
                "HF_HOME", "TORCH_HOME"):
        value = os.environ.get(env)
        if not value:
            continue
        roots.append(value)
        if env in ("HF_HOME", "TORCH_HOME"):
            roots.append(os.path.join(value, "hub"))
            roots.append(os.path.join(value, "sentence_transformers"))
    roots.append(os.path.join(home, ".cache", "huggingface", "hub"))
    roots.append(os.path.join(home, ".cache", "torch",
                              "sentence_transformers"))
    return roots


def probe_embeddings() -> dict:
    """
    Whether evidence can actually be embedded.

    torch and sentence-transformers are lazy optional imports (B15) — the
    backend starts without them, which means "importable" is a real
    question rather than a formality, and a `False` here is the honest
    early warning that the first ingest of the session will fail.

    `model_cached` answers the air-gap question (AGENTS.md §1): a
    forensics box with no route to the internet can only embed with a
    model already on disk, and finding that out on the health page beats
    finding it out 40% into an ingest.
    """
    out = {
        "state": None,
        "detail": "",
        "reason": None,
        "model": EMBED_MODEL_NAME,
        "vector_size": None,
        "torch_available": None,
        "sentence_transformers_available": None,
        "model_cached": None,
    }

    # find_spec resolves the module without executing it. Importing torch
    # costs seconds and hundreds of MB, and this runs on a polled
    # endpoint.
    missing = []
    for module_name, key in (("torch", "torch_available"),
                              ("sentence_transformers",
                               "sentence_transformers_available")):
        try:
            out[key] = importlib.util.find_spec(module_name) is not None
        except Exception as e:
            out[key] = None
            missing.append(
                f"{module_name} could not be resolved ({type(e).__name__})"
            )
        if out[key] is False:
            missing.append(f"{module_name} is not installed")

    try:
        from backend.modules.vector_store import VECTOR_SIZE
        out["vector_size"] = int(VECTOR_SIZE)
    except Exception as e:
        # Never fall back to a restated 384: if the constant cannot be
        # read, the dimension is unknown.
        out["vector_size"] = None
        missing.append(
            f"vector_store.VECTOR_SIZE is unreadable ({type(e).__name__})"
        )

    cached = None
    try:
        needle = EMBED_MODEL_NAME.lower()
        for root in _hf_cache_roots():
            if not os.path.isdir(root):
                continue
            try:
                entries = os.listdir(root)
            except OSError:
                continue
            for entry in entries:
                if needle in entry.lower():
                    cached = True
                    break
            if cached:
                break
        else:
            # Every root was searched and none held it. That is a real
            # answer, not an unknown - but see the caveat in the reason.
            cached = False
    except Exception:
        cached = None
    out["model_cached"] = cached

    if missing:
        # A package that is measurably absent is a measured fault: the
        # next ingest will fail. A package we merely could not resolve is
        # an unknown, and the two must not be painted the same colour.
        absent = any(
            out[k] is False for k in
            ("torch_available", "sentence_transformers_available")
        )
        out["state"] = STATE_ERROR if absent else STATE_UNAVAILABLE
        out["detail"] = (
            "Evidence cannot be embedded: the local embedding backend is "
            "not usable."
        )
        out["reason"] = "; ".join(missing)
        return out

    if cached is False:
        # Packages are fine, so this is a warning, not a fault - but the
        # operator has to know before the first ingest needs the network.
        out["state"] = STATE_OK
        out["detail"] = (
            f"{EMBED_MODEL_NAME} is installed but not found in any "
            "standard local cache, so the first ingest would need to "
            "download it. On an air-gapped machine that will fail."
        )
        out["reason"] = (
            "model not found in the standard SentenceTransformers/HF "
            "cache locations; it may still be present at a custom path"
        )
        return out

    out["state"] = STATE_OK
    out["detail"] = (
        f"{EMBED_MODEL_NAME} ({out['vector_size']}-dim) is installed"
        + (" and cached locally." if cached else ".")
    )
    return out


# ── aggregate ───────────────────────────────────────────────────────────────

# (service key, probe, needs cases_dir)
_PROBES = (
    ("database", probe_database, False),
    ("ollama", probe_ollama, False),
    ("vector_store", probe_vector_store, True),
    ("worker", probe_worker, False),
    ("cases_dir", probe_cases_dir, True),
    ("embeddings", probe_embeddings, False),
)


def collect_status(cases_dir: str) -> dict:
    """
    Probes every service and returns the /api/status payload.

    Every probe is individually guarded *and* individually guarded again
    here, because the invariant that matters most is the one about the
    response as a whole: a health endpoint that 500s tells the operator
    nothing about any of the five services that were fine.
    """
    started = time.perf_counter()
    services = {}
    for key, probe, needs_dir in _PROBES:
        try:
            services[key] = probe(cases_dir) if needs_dir else probe()
        except Exception as e:
            services[key] = {
                "state": STATE_UNAVAILABLE,
                "detail": f"The {key.replace('_', ' ')} probe raised "
                          "before it could measure anything.",
                "reason": f"{type(e).__name__}: {e}",
            }

    # The vector store is a filesystem count; the database is the
    # authority on which cases exist. Reporting the two side by side is
    # what turns "21 collections" into "21 collections for 4 cases",
    # which is a very different thing to read during an engagement.
    vector = services.get("vector_store") or {}
    database = services.get("database") or {}
    if "cases_in_db" in vector:
        if database.get("state") == STATE_OK:
            vector["cases_in_db"] = database.get("case_rows")
            on_disk = vector.get("case_collections")
            in_db = vector.get("cases_in_db")
            if isinstance(on_disk, int) and isinstance(in_db, int):
                # Both directions matter, and the sentence has to match
                # the direction. An earlier draft emitted the "collections
                # for cases that are gone" wording whenever the two
                # numbers merely differed, so a machine with 10 cases and
                # 3 indexes was told it had orphan collections when the
                # opposite was true.
                if on_disk > in_db:
                    vector["detail"] += (
                        f"; the database holds {in_db} case row(s), so "
                        f"{on_disk - in_db} collection(s) on disk belong "
                        "to cases that are no longer in the database"
                    )
                elif in_db > on_disk:
                    vector["detail"] += (
                        f"; the database holds {in_db} case row(s) but "
                        f"only {on_disk} hold a Qdrant index, so those "
                        "cases have no searchable index (no evidence "
                        "indexed, or indexing never ran)"
                    )
        else:
            vector["cases_in_db"] = None

    db_state = (services.get("database") or {}).get("state")
    ollama = services.get("ollama") or {}
    cases_state = (services.get("cases_dir") or {}).get("state")

    degraded = sorted(k for k, v in services.items()
                      if v.get("state") != STATE_OK)

    installed = ollama.get("installed_models")

    return {
        "services": services,
        "checked_at": _timestamp(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "degraded": degraded,

        # ── legacy keys ──────────────────────────────────────────────
        # Kept because Sidebar.jsx and SystemHealthPage.jsx still read
        # them. They are deliberately lossy and deliberately collapse
        # *towards* not-fabricating:
        #   * "ollama" is "running" only when a model is actually ready.
        #     The old value meant "the daemon answered /api/tags", which
        #     is true on a machine with zero models - the exact lie this
        #     work set out to remove. The precise split is in
        #     services.ollama.
        #   * "models" is [] when the list could not be read. The honest
        #     value is services.ollama.installed_models, which is None
        #     in that case; this list keeps its legacy type so existing
        #     consumers keep working.
        #   * "database" is "not found" for any non-ok state. That is
        #     imprecise for a corrupt-but-present file, but it is never
        #     falsely healthy, and services.database carries the real
        #     reason.
        "database": "connected" if db_state == STATE_OK else "not found",
        "ollama": (
            "running" if ollama.get("model_ready") is True else "offline"
        ),
        "models": list(installed) if installed else [],
        "cases_dir": cases_state == STATE_OK,
    }

"""
Guards the measured service health behind `GET /api/status`.

`service_health.py` exists because that endpoint used to report fiction:
`database` was `os.path.exists()` presented as "connected", and `ollama`
was "running" whenever `/api/tags` answered 200 — which it also does with an
EMPTY model list, so a machine that had never pulled a model reported a
healthy AI. Six string literals in the UI sat on top of that.

What is asserted here
---------------------
The module's own rule (AGENTS.md §16), in every direction that matters:

* **A metric that cannot be measured is `None` plus a reason, never a
  fabricated `0`, `False` or "ok".** Sections B, C, E, F and G each drive
  a measurement into a failure and require the honest shape.
* **`state` distinguishes "measured and broken" (`error`) from "could not
  measure" (`unavailable`).** A probe that raised must degrade to
  `unavailable` for *that* service and leave the other five measured —
  a health endpoint that 500s tells an investigator nothing about any of
  the five services that were fine.
* **The legacy keys can never be fabricated healthy.** They are the
  contract `Sidebar.jsx` and `SystemHealthPage.jsx` still read, and they
  collapse two ways the honest field does not. The headline case is
  section C: a daemon answering 200 with no models must NOT read
  `"ollama": "running"`.
* **No probe caches.** Section J calls the same probes twice with the
  fixture changed underneath and requires the second answer to differ.

Two fixture rules, both learned the hard way in this repo
---------------------------------------------------------
* **A fixture must be able to discriminate.** The unwritable-directory
  check stubs `_probe_writable` because a real read-only directory cannot
  be made on this platform — see section F, which measures that first
  rather than assuming it. The size-cap check lowers the module's own
  cap constant instead of creating 200 000 files, because a fixture that
  takes four minutes and cannot be re-run quickly is one nobody re-runs.
* **A value is never coerced with `or`.** `0 or -1` is `-1` and
  `Number(null) === 0` is `0`; both bugs are in this repo's history, and
  both are invisible in a suite that writes `x or 0`. Every numeric
  check below is an explicit `is not None` plus a range.

Nothing here touches `data/forensic.db` or `data/cases`. Every database
assertion points `backend.database.engine` at a throwaway file, and every
directory fixture is created under one temp root — see `_DB_FINGERPRINT`
at the bottom, which re-stats the real database and fails the run if it
moved. No QdrantClient is opened anywhere: embedded mode takes an
exclusive lock per storage directory and would fight the running
application (AGENTS.md §15, B14). The `qdrant` directories below hold
plain files and are only ever counted and `os.walk`ed.

Run:  PYTHONPATH=. python tests/verify_service_health.py
"""
import atexit
import contextlib
import json
import os
import shutil
import sqlite3
import stat
import sys
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from sqlalchemy import create_engine

import backend.database
from backend.modules import service_health as sh
from backend.modules import job_worker

PASS, FAIL, SKIP = [], [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{'' if cond else '  -> ' + str(detail)}")
    return bool(cond)


def skip(label, why):
    SKIP.append(label)
    print(f"  SKIP  {label}  ({why})")


# ── fixtures ───────────────────────────────────────────────────────────────

# One temp root for everything this script creates, removed on every exit
# path including an exception, so a failed run does not leave evidence
# trees behind for the next one to trip over.
ROOT = tempfile.mkdtemp(prefix="idfai_health_")
atexit.register(lambda: shutil.rmtree(ROOT, ignore_errors=True))

STATES = {"ok", "error", "unavailable"}

# The six services, in the order the endpoint documents them.
SERVICE_KEYS = ("database", "ollama", "vector_store", "worker",
                "cases_dir", "embeddings")

REQUIRED_KEYS = {
    "database": ("state", "detail", "latency_ms"),
    "ollama": ("state", "detail", "model", "model_ready",
               "installed_models", "reason"),
    "vector_store": ("state", "detail", "case_collections",
                     "total_size_mb", "reason"),
    "worker": ("state", "detail", "reason"),
    "cases_dir": ("state", "detail", "reason"),
    "embeddings": ("state", "detail", "reason"),
}

# A daemon that is up and has something to answer with.
OLLAMA_READY = {
    "base_url": "http://localhost:11434",
    "configured_model": "llama3.2:3b",
    "running": True,
    "model_ready": True,
    "installed_models": ["llama3.2:3b"],
    "reason": None,
}

# The exact case this module was written for: 200 OK, empty model list.
OLLAMA_UP_NO_MODEL = {
    "base_url": "http://localhost:11434",
    "configured_model": "llama3.2:3b",
    "running": True,
    "model_ready": False,
    "installed_models": [],
    "reason": ("Ollama is running but has no models installed. "
               "Pull one with: ollama pull llama3.2:3b"),
}

# The probe could not complete: `running` is tri-state and None means
# "we do not know", not "down".
OLLAMA_UNKNOWN = {
    "base_url": "http://localhost:11434",
    "configured_model": "llama3.2:3b",
    "running": None,
    "model_ready": None,
    "installed_models": None,
    "reason": "Cannot reach Ollama at http://localhost:11434 (ConnectionError).",
}

OLLAMA_DOWN = {
    "base_url": "http://localhost:11434",
    "configured_model": "llama3.2:3b",
    "running": False,
    "model_ready": None,
    "installed_models": None,
    "reason": "Ollama answered HTTP 503 on /api/tags.",
}


def _p(*parts):
    """Path inside the temp root. os.path.join only (AGENTS.md §9)."""
    return os.path.join(ROOT, *parts)


def make_db(name, rows=0, with_cases_table=True):
    """
    A throwaway SQLite file.

    Deliberately minimal: a count needs the table to exist, nothing more.
    That is what makes the "valid SQLite file, wrong schema" case in
    section B expressible at all — a full copy of the real schema would
    make that fixture indistinguishable from a healthy one.
    """
    path = _p(name)
    con = sqlite3.connect(path)
    try:
        if with_cases_table:
            con.execute("CREATE TABLE cases (id TEXT PRIMARY KEY)")
            con.executemany("INSERT INTO cases VALUES (?)",
                            [(f"row-{i}",) for i in range(rows)])
        con.commit()
    finally:
        con.close()
    return path


def make_corrupt_db(name):
    """Random bytes with a .db name: exists, and is not a database."""
    path = _p(name)
    with open(path, "wb") as fh:
        fh.write(os.urandom(64 * 1024))
    return path


def build_cases_tree(name, cases, qdrant_cases=(), bytes_per_file=0,
                     files_per_index=1):
    """
    A cases directory holding per-case subdirectories, some of which hold a
    `qdrant` subdirectory full of plain files. Nothing here is a Qdrant
    store — the probe only ever counts and walks these.
    """
    root = _p(name)
    os.makedirs(root, exist_ok=True)
    for case_id in cases:
        os.makedirs(os.path.join(root, case_id), exist_ok=True)
    for case_id in qdrant_cases:
        index = os.path.join(root, case_id, "qdrant")
        os.makedirs(index, exist_ok=True)
        for i in range(files_per_index):
            with open(os.path.join(index, f"segment-{i}.bin"), "wb") as fh:
                fh.write(b"\0" * bytes_per_file)
    return root


@contextlib.contextmanager
def engine_on(path):
    """
    Points `backend.database.engine` at `path` for the duration.

    `probe_database` does `from backend.database import engine` INSIDE the
    function body, so rebinding the module attribute is enough to redirect
    it. Every database assertion in this file goes through here, which is
    the only reason `data/forensic.db` is never opened.

    The throwaway engine is disposed on the way out: a live pool holds the
    file open, and on Windows that makes the delete fail and the file
    survive the run.
    """
    real = backend.database.engine
    temp_engine = create_engine(
        f"sqlite:///{path}", connect_args={"check_same_thread": False})
    backend.database.engine = temp_engine
    try:
        yield temp_engine
    finally:
        backend.database.engine = real
        try:
            temp_engine.dispose()
        except Exception:
            pass


@contextlib.contextmanager
def stub_ollama(payload):
    """
    Replaces `ollama_client.ollama_diagnostic` for the duration.

    probe_ollama imports the function inside its own body, so rebinding the
    module attribute is enough. Stubbing it is not a way of avoiding the
    real contract: `ollama_diagnostic` is the authority on "is there a
    model to answer with" and the point of the assertion is what
    `service_health` does with each of its three states, which is not
    observable on a machine that happens to have a model installed.
    """
    from backend.modules import ollama_client
    real = ollama_client.ollama_diagnostic
    ollama_client.ollama_diagnostic = lambda: dict(payload)
    try:
        yield
    finally:
        ollama_client.ollama_diagnostic = real


@contextlib.contextmanager
def stub_probes(probes):
    """
    Replaces the probe table `collect_status` iterates.

    The current value is captured on ENTRY, before it is replaced. An
    earlier draft of this file re-read the module attribute after replacing
    it and restored the replacement — a no-op that left a stubbed probe
    table installed for the rest of the process.
    """
    real = sh._PROBES
    sh._PROBES = tuple(probes)
    try:
        yield
    finally:
        sh._PROBES = real


@contextlib.contextmanager
def stub_writable(writable, why="simulated: OSError(13, 'Permission denied')"):
    """
    Replaces the writability probe for the duration.

    See section F for why a real read-only directory cannot be used here.
    """
    real = sh._probe_writable
    sh._probe_writable = lambda path: (writable, why if not writable else None)
    try:
        yield
    finally:
        sh._probe_writable = real


@contextlib.contextmanager
def stub_find_spec(present, raiser=None):
    """
    Replaces `importlib.util` as seen by service_health.

    `present` is a set of module names that resolve; everything else comes
    back as "not installed". `raiser` names a module whose lookup raises
    instead of answering — the third outcome, and the one that separates
    "measured absent" from "could not measure".

    Reassigning `sh.importlib` rebinds the name in this module only; the
    real importlib is untouched for the rest of the process.
    """
    class _Fake:
        def __init__(self):
            self.util = self

        def find_spec(self, name, *args, **kwargs):
            if raiser is not None and name == raiser:
                raise ImportError(f"boom resolving {name}")
            return object() if name in present else None

    real = sh.importlib
    sh.importlib = _Fake()
    try:
        yield
    finally:
        sh.importlib = real


def _fake(state, detail="stubbed", reason=None, **extra):
    out = {"state": state, "detail": detail, "reason": reason}
    out.update(extra)
    return out


def _boom():
    raise RuntimeError("probe exploded")


# ── the real database, so the run can prove it never opened it ─────────────

def _db_fingerprint():
    """(size, mtime_ns) of the configured database, or None if absent."""
    try:
        target = backend.database.engine.url.database
    except Exception:
        return None
    if not target or target.startswith(":"):
        return None
    try:
        st = os.stat(os.path.abspath(target))
        return (st.st_size, st.st_mtime_ns)
    except OSError:
        return None


# Read at the start of the run, in main(), and re-read at the end. A value
# captured here at import time is measured before the first assertion and
# therefore reports anyone else's writes as this suite's side effects.
_DB_FINGERPRINT = _db_fingerprint()   # diagnostic only; not asserted on


# ── sections ───────────────────────────────────────────────────────────────

def section_happy_path():
    """
    A healthy machine: five services `ok`, and the worker honestly
    `unavailable` because `start_worker()` only runs in the FastAPI
    lifespan, which a test process never enters.
    """
    print("\n=== A. happy path (throwaway database + tree) ===")
    db_path = make_db("happy.db", rows=0)
    tree = build_cases_tree(
        "happy_cases", ["case-a", "case-b"], qdrant_cases=["case-a"],
        bytes_per_file=100 * 1024, files_per_index=3)
    expected_bytes = 3 * 100 * 1024

    with engine_on(db_path), stub_ollama(OLLAMA_READY):
        out = sh.collect_status(tree)

    for key in SERVICE_KEYS:
        check(f"service '{key}' is present", key in out["services"],
              sorted(out["services"]))

    for key in SERVICE_KEYS:
        state = out["services"][key]["state"]
        check(f"{key}: state is one of ok/error/unavailable, never None",
              state in STATES, state)

    for key in ("database", "ollama", "vector_store", "cases_dir",
                "embeddings"):
        svc = out["services"][key]
        check(f"{key}: ok on a healthy machine", svc["state"] == "ok",
              svc.get("detail"))
        check(f"{key}: detail is non-empty", bool(svc["detail"]))
        check(f"{key}: an ok service carries no reason",
              svc["reason"] is None, svc["reason"])

    worker = out["services"]["worker"]
    check("worker: unavailable in a test process (start_worker never ran)",
          worker["state"] == "unavailable", worker["detail"])
    check("worker: reason names the lifespan that starts it",
          "start_worker" in (worker["reason"] or "").lower()
          or "lifespan" in (worker["reason"] or "").lower(),
          worker["reason"])

    # Latency is what replaced a previously invisible ~2.1 s.
    db_latency = out["services"]["database"]["latency_ms"]
    check("database: latency_ms is a real number, not None",
          isinstance(db_latency, float) and db_latency is not None,
          repr(db_latency))
    check("database: latency_ms is positive on a file-backed database",
          isinstance(db_latency, float) and db_latency > 0.0,
          repr(db_latency))
    ollama_latency = out["services"]["ollama"]["latency_ms"]
    check("ollama: latency_ms is a real number, not None",
          isinstance(ollama_latency, float) and ollama_latency is not None,
          repr(ollama_latency))
    check("ollama: latency_ms is never negative",
          isinstance(ollama_latency, float) and ollama_latency >= 0.0,
          repr(ollama_latency))

    vs = out["services"]["vector_store"]
    check("vector_store: counts the one case that has an index",
          vs["case_collections"] == 1, vs["case_collections"])
    check("vector_store: counts both case directories",
          vs["cases_total"] == 2, vs["cases_total"])
    check("vector_store: total_size_mb matches the bytes on disk",
          vs["total_size_mb"] == round(expected_bytes / (1024 * 1024), 2),
          vs["total_size_mb"])
    check("vector_store: a real total is not rounded down to 0",
          isinstance(vs["total_size_mb"], float)
          and vs["total_size_mb"] > 0.0, vs["total_size_mb"])
    check("vector_store: cases_in_db comes from the database probe",
          vs["cases_in_db"] == 0, vs["cases_in_db"])
    check("vector_store: the detail names the orphaned collections",
          "no longer in the database" in vs["detail"], vs["detail"])

    emb = out["services"]["embeddings"]
    check("embeddings: states the 384-dim all-MiniLM-L6-v2 embedder",
          "384" in emb["detail"] and "all-MiniLM-L6-v2" in emb["detail"],
          emb["detail"])
    check("embeddings: vector_size is a real int",
          isinstance(emb["vector_size"], int), repr(emb["vector_size"]))
    from backend.modules.vector_store import VECTOR_SIZE
    check("embeddings: vector_size is the constant the store uses, not a "
          "restated literal",
          emb["vector_size"] == VECTOR_SIZE == 384,
          (emb["vector_size"], VECTOR_SIZE))
    check("embeddings: model_cached is a bool or None, never a fabricated 0",
          emb["model_cached"] is None or isinstance(emb["model_cached"], bool),
          repr(emb["model_cached"]))
    if emb["model_cached"] is False:
        check("embeddings: a model that is not cached locally carries a "
              "reason", bool(emb["reason"]), emb["reason"])

    check("legacy database key is 'connected' when the query answered",
          out["database"] == "connected", out["database"])
    check("legacy ollama key is 'running' when a model is ready",
          out["ollama"] == "running", out["ollama"])
    check("legacy models key is the installed list",
          out["models"] == ["llama3.2:3b"], out["models"])
    check("legacy cases_dir key is a bool", isinstance(out["cases_dir"], bool))

    check("degraded names exactly the non-ok services, sorted",
          out["degraded"] == ["worker"], out["degraded"])
    check("degraded is sorted", out["degraded"] == sorted(out["degraded"]))

    missing = [f"{svc}.{key}" for svc, keys in REQUIRED_KEYS.items()
               for key in keys if key not in out["services"].get(svc, {})]
    check("every documented key is present", not missing, missing)
    check("the response is JSON-serialisable (the route must return it)",
          isinstance(json.loads(json.dumps(out)), dict))
    return out


def section_database():
    """
    File existence is not connectivity. Each fixture below is a file that
    `os.path.exists` would have called "connected".
    """
    print("\n=== B. database: existence is not connectivity ===")

    good = make_db("good.db", rows=1)
    with engine_on(good):
        r = sh.probe_database()
    check("healthy database reads ok", r["state"] == "ok", r["detail"])
    check("healthy database counts the real rows", r["case_rows"] == 1,
          r["case_rows"])
    check("healthy database detail names the dialect",
          "sqlite" in r["detail"].lower(), r["detail"])
    check("healthy database reports the file it actually read",
          os.path.abspath(good) == r["path"], r["path"])

    corrupt = make_corrupt_db("corrupt.db")
    check("corrupt fixture exists on disk (existence would say 'connected')",
          os.path.exists(corrupt))
    with engine_on(corrupt):
        r = sh.probe_database()
    check("a corrupt database is an error, not 'connected'",
          r["state"] == "error", f"{r['state']}: {r['reason']}")
    check("corrupt database carries the driver reason",
          bool(r["reason"]), r["reason"])
    check("corrupt database case_rows is None, never 0",
          r["case_rows"] is None, r["case_rows"])

    unopenable = _p("no-such-dir", "nested.db")
    with engine_on(unopenable):
        r = sh.probe_database()
    check("a database at an unopenable path is an error",
          r["state"] == "error", f"{r['state']}: {r['reason']}")

    # The discriminating fixture: a perfectly VALID SQLite file with no
    # `cases` table. `SELECT 1` is answered entirely from the connection
    # and never touches the file, so a probe that only ran `SELECT 1`
    # would call this healthy. It is not.
    empty = make_db("empty.db", with_cases_table=False)
    with engine_on(empty):
        r = sh.probe_database()
    check("a valid SQLite file with the wrong schema is an error, not ok",
          r["state"] == "error", f"{r['state']}: {r['reason']}")
    check("wrong schema: case_rows is None, never 0", r["case_rows"] is None,
          r["case_rows"])
    check("wrong schema: latency is still reported (it was measured)",
          isinstance(r["latency_ms"], float), repr(r["latency_ms"]))

    with engine_on(make_db("rows3.db", rows=3)):
        r = sh.probe_database()
    check("a real count of 3 is reported as 3, not falsy-coerced",
          r["case_rows"] == 3, r["case_rows"])


def section_ollama_and_legacy():
    """
    "Ollama is up" and "there is a model to answer with" are two different
    facts. The legacy key has only two values, so it must collapse towards
    not-fabricating: "running" requires a ready model.
    """
    print("\n=== C. ollama, and the legacy keys cannot be fabricated ===")
    db_path = make_db("ollama.db", rows=0)
    tree = build_cases_tree("ollama_cases", ["case-a"])

    with engine_on(db_path), stub_ollama(OLLAMA_UP_NO_MODEL):
        r = sh.probe_ollama()
        out = sh.collect_status(tree)
    check("daemon up with zero models is an error, not 'ok'",
          r["state"] == "error", r["state"])
    check("daemon up with zero models: model_ready is False",
          r["model_ready"] is False, r["model_ready"])
    check("daemon up with zero models: installed_models is the real []",
          r["installed_models"] == [], r["installed_models"])
    check("daemon up with zero models: detail says the assistant cannot "
          "answer", "cannot answer" in r["detail"], r["detail"])
    check("daemon up with zero models: reason survives from the diagnostic",
          "pull" in (r["reason"] or "").lower(), r["reason"])
    check("THE INVARIANT: legacy ollama is NOT 'running' with no model",
          out["ollama"] != "running", out["ollama"])
    check("legacy ollama reads 'offline' with no model",
          out["ollama"] == "offline", out["ollama"])
    check("legacy models stays a list, never a sentinel",
          isinstance(out["models"], list), type(out["models"]).__name__)

    with engine_on(db_path), stub_ollama(OLLAMA_UNKNOWN):
        r = sh.probe_ollama()
        out = sh.collect_status(tree)
    check("an unreachable Ollama is 'unavailable', not 'error' (unknown "
          "is not down)", r["state"] == "unavailable", r["state"])
    check("unreachable Ollama: installed_models is None, not []",
          r["installed_models"] is None, r["installed_models"])
    check("unreachable Ollama: model_ready is None, not False",
          r["model_ready"] is None, r["model_ready"])
    check("unreachable Ollama: legacy key is not 'running'",
          out["ollama"] != "running", out["ollama"])
    check("legacy models is still a list when the list is unknown",
          isinstance(out["models"], list), type(out["models"]).__name__)

    with engine_on(db_path), stub_ollama(OLLAMA_DOWN):
        r = sh.probe_ollama()
        out = sh.collect_status(tree)
    check("an Ollama answering a non-200 is an error",
          r["state"] == "error", r["state"])
    check("ollama error carries the HTTP status from the diagnostic",
          "503" in (r["reason"] or ""), r["reason"])
    check("ollama down: legacy key is not 'running'", out["ollama"] == "offline")

    with engine_on(db_path), stub_ollama(OLLAMA_READY):
        r = sh.probe_ollama()
        out = sh.collect_status(tree)
    check("a ready model is ok", r["state"] == "ok", r["detail"])
    check("a ready model: legacy key is 'running'",
          out["ollama"] == "running", out["ollama"])
    check("a ready model: legacy models is the real list",
          out["models"] == ["llama3.2:3b"], out["models"])

    # The fabricated-healthy guard, all at once: every service broken, and
    # no legacy key may claim health.
    broken_db = make_corrupt_db("allbroken.db")
    with engine_on(broken_db), stub_ollama(OLLAMA_UP_NO_MODEL), \
            stub_writable(False):
        out = sh.collect_status(tree)
    check("all-broken: legacy database is not 'connected'",
          out["database"] != "connected", out["database"])
    check("all-broken: legacy database reads 'not found'",
          out["database"] == "not found", out["database"])
    check("all-broken: legacy ollama is not 'running'",
          out["ollama"] != "running", out["ollama"])
    check("all-broken: legacy cases_dir is False",
          out["cases_dir"] is False, out["cases_dir"])
    check("all-broken: legacy models is still a list",
          isinstance(out["models"], list), type(out["models"]).__name__)
    check("all-broken: every service is named in degraded",
          set(out["degraded"]) == {"database", "ollama", "vector_store",
                                   "worker", "cases_dir"}, out["degraded"])


def section_worker():
    """
    The `_MISSING` sentinel, and the lie it exists to prevent.

    `_worker_running` is only ever cleared by `stop_worker()`, so a flag
    left True with a dead thread means the queue will never drain again
    while every caller still reads "running" — the B11 shape.
    """
    print("\n=== D. worker liveness, and the sentinel that distinguishes "
          "'absent' from 'None' ===")
    saved_thread = job_worker._worker_thread
    saved_flag = job_worker._worker_running
    try:
        # Present but never started: the ordinary value in a test process.
        job_worker._worker_thread = None
        job_worker._worker_running = False
        r_unstarted = sh.probe_worker()
        check("unstarted worker: unavailable, not an error",
              r_unstarted["state"] == "unavailable", r_unstarted["state"])
        check("unstarted worker: the reason names the lifespan",
              "start_worker" in (r_unstarted["reason"] or "").lower(),
              r_unstarted["reason"])
        check("unstarted worker: the flag is reported as False, not None",
              r_unstarted["running_flag"] is False,
              r_unstarted["running_flag"])
        check("unstarted worker: not described as unreadable state",
              "introspectable" not in r_unstarted["detail"],
              r_unstarted["detail"])

        # Flag set, thread dead: the silent-queue lie.
        dead = threading.Thread(target=lambda: None, daemon=True)
        dead.start()
        dead.join()
        job_worker._worker_thread = dead
        job_worker._worker_running = True
        r_dead = sh.probe_worker()
        check("dead thread with the flag still set is an error",
              r_dead["state"] == "error", f"{r_dead['state']}: {r_dead['detail']}")
        check("dead thread: thread_alive is measured False, not None",
              r_dead["thread_alive"] is False, r_dead["thread_alive"])
        check("dead thread: detail says the queue will never be picked up",
              "never" in r_dead["detail"].lower(), r_dead["detail"])

        # Alive and polling.
        gate = threading.Event()
        alive = threading.Thread(target=gate.wait, daemon=True,
                                 name="ingestion-worker")
        alive.start()
        job_worker._worker_thread = alive
        job_worker._worker_running = True
        r_alive = sh.probe_worker()
        check("live thread with the flag set is ok", r_alive["state"] == "ok",
              r_alive["detail"])
        check("live worker: thread_alive is measured True",
              r_alive["thread_alive"] is True, r_alive["thread_alive"])
        check("live worker: detail names the thread",
              "ingestion-worker" in r_alive["detail"], r_alive["detail"])

        # Alive, but a stop was requested: shutting down, not broken.
        job_worker._worker_running = False
        r_stopping = sh.probe_worker()
        check("alive thread with the flag cleared is ok (shutting down)",
              r_stopping["state"] == "ok", r_stopping["detail"])
        gate.set()
        alive.join()

        # The attribute is gone entirely — a rename in job_worker.
        del job_worker._worker_thread
        del job_worker._worker_running
        r_missing = sh.probe_worker()
        check("absent attributes read as unreadable, not as 'not started'",
              r_missing["state"] == "unavailable", r_missing["state"])
        check("absent attributes: the detail says not introspectable",
              "introspectable" in r_missing["detail"], r_missing["detail"])
        check("absent attributes: the reason names the two attributes",
              "_worker_thread" in (r_missing["reason"] or "")
              and "_worker_running" in (r_missing["reason"] or ""),
              r_missing["reason"])
        check("absent attributes are NOT reported as an exception",
              "AttributeError" not in (r_missing["reason"] or ""),
              r_missing["reason"])

        # The discrimination itself. A probe that tested
        # `getattr(...) is None` returns the SAME answer for both cases,
        # which is the bug: before start_worker() those values are None
        # and False, so every real server would have been told its worker
        # state was unreadable.
        check("'never started' and 'not introspectable' read differently",
              r_unstarted["detail"] != r_missing["detail"],
              (r_unstarted["detail"], r_missing["detail"]))
        check("'never started' and 'not introspectable' differ in reason too",
              r_unstarted["reason"] != r_missing["reason"],
              (r_unstarted["reason"], r_missing["reason"]))
        check("'never started' and 'not introspectable' differ in state "
              "wording, not just prose",
              "introspectable" not in r_unstarted["detail"]
              and "start_worker" in (r_unstarted["reason"] or ""),
              (r_unstarted["detail"], r_unstarted["reason"]))
    finally:
        job_worker._worker_thread = saved_thread
        job_worker._worker_running = saved_flag


def section_vector_store():
    print("\n=== E. vector store: counts, sizes, caps, and no leakage ===")
    tree_a = build_cases_tree("vs_a", ["c1", "c2", "c3"],
                              qdrant_cases=["c1", "c2"],
                              bytes_per_file=64 * 1024, files_per_index=2)
    r = sh.probe_vector_store(tree_a)
    check("two case indexes are counted, not one",
          r["case_collections"] == 2, r["case_collections"])
    check("three case directories are counted",
          r["cases_total"] == 3, r["cases_total"])
    check("a cases directory with no indexes is ok with 0 collections",
          sh.probe_vector_store(
              build_cases_tree("vs_empty", ["only-case"]))["case_collections"]
          == 0)
    zero_case = sh.probe_vector_store(
        build_cases_tree("vs_zero", ["only-case"]))
    check("a real 0 collections is a measurement, not a fabrication",
          zero_case["case_collections"] == 0
          and zero_case["state"] == "ok", zero_case)

    expected = round(2 * 2 * 64 * 1024 / (1024 * 1024), 2)
    check("total_size_mb is the sum over BOTH case indexes",
          r["total_size_mb"] == expected, (r["total_size_mb"], expected))
    check("total_size_mb is positive, not a rounded-down 0",
          isinstance(r["total_size_mb"], float) and r["total_size_mb"] > 0.0,
          r["total_size_mb"])

    # A missing directory is not "0 collections": nothing was counted,
    # because there was nothing there to count.
    missing = sh.probe_vector_store(_p("no-such-cases-dir"))
    check("a missing cases directory is an error",
          missing["state"] == "error", f"{missing['state']}: {missing['detail']}")
    check("a missing cases directory yields None, never 0 collections",
          missing["case_collections"] is None, missing["case_collections"])
    check("a missing cases directory yields no size, never 0.0",
          missing["total_size_mb"] is None, missing["total_size_mb"])
    check("a missing cases directory carries a reason",
          bool(missing["reason"]), missing["reason"])

    # The size walk is bounded. A bounded walk that returns a partial total
    # is not a measurement - it is a number that looks like one.
    capped_tree = build_cases_tree("vs_cap", ["c1"], qdrant_cases=["c1"],
                                   bytes_per_file=16, files_per_index=6)
    real_cap = sh._MAX_WALK_FILES
    try:
        sh._MAX_WALK_FILES = 2
        r_cap = sh.probe_vector_store(capped_tree)
    finally:
        sh._MAX_WALK_FILES = real_cap
    check("exceeding the walk cap yields no total, not a partial one",
          r_cap["total_size_mb"] is None, r_cap["total_size_mb"])
    check("exceeding the walk cap carries a reason naming the cap",
          "walk" in (r_cap["reason"] or "").lower()
          and "exceed" in (r_cap["reason"] or "").lower(), r_cap["reason"])
    check("exceeding the walk cap leaves the collection COUNT intact "
          "(it was fully counted before the walk)",
          r_cap["case_collections"] == 1, r_cap["case_collections"])
    check("the cap is restored after the test", sh._MAX_WALK_FILES == real_cap,
          sh._MAX_WALK_FILES)

    # No state leaks between calls: same probe, different directory.
    tree_b = build_cases_tree("vs_b", ["x1", "x2", "x3", "x4"],
                              qdrant_cases=["x1"])
    r_b = sh.probe_vector_store(tree_b)
    check("the count follows the directory it was given",
          r_b["case_collections"] == 1, r_b["case_collections"])
    check("the count does not leak from the previous call",
          r_b["case_collections"] != r["case_collections"],
          (r["case_collections"], r_b["case_collections"]))
    r_a2 = sh.probe_vector_store(tree_a)
    check("re-reading the first tree reproduces the first answer exactly",
          (r_a2["case_collections"], r_a2["total_size_mb"])
          == (r["case_collections"], r["total_size_mb"]),
          (r["case_collections"], r_a2["case_collections"]))


@contextlib.contextmanager
def qdrant_layout(cases_dir, canonical_base):
    """
    Pin BOTH the configured cases directory and where the writer puts indexes.

    Three things have to agree before the probe can reach a verdict about
    migration: the directory it is handed, the configured root it compares
    against, and the resolver ``case_qdrant_path`` consults. Patching only the
    first is what made the split unobservable from a test -- the probe then
    always saw a tree it had no authority to judge, and correctly said
    "not applicable" to everything.
    """
    import backend.dependencies as deps
    import backend.modules.vector_store as vs

    class _S:
        def __init__(self, real, cd):
            self._real = real
            self.cases_dir = cd

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_get = deps.get_settings
    real_resolve = vs.resolve_qdrant_dir
    deps.get_settings = lambda: _S(real_get(), cases_dir)
    vs.resolve_qdrant_dir = lambda: canonical_base
    try:
        yield
    finally:
        deps.get_settings = real_get
        vs.resolve_qdrant_dir = real_resolve


def _make_index(path, files=2, size=64 * 1024):
    """Create a directory that looks like a per-case index. Not real Qdrant."""
    os.makedirs(path, exist_ok=True)
    for i in range(files):
        with open(os.path.join(path, f"seg{i}.dat"), "wb") as fh:
            # A filler byte, not a NUL escape. The content is irrelevant to a
            # size fixture, and a backslash-escaped NUL literal in a fixture is
            # one more thing that can be wrong in a way that quietly doubles
            # every measurement the suite makes.
            fh.write(b"x" * size)
    return path


def section_qdrant_layout():
    """
    An index has two legitimate homes, and the probe has to know about both.

    This section is the guard for a real regression. The probe used to list
    the directory it was handed and then ask ``case_qdrant_path()`` where the
    index was -- a function that resolves against global settings and takes no
    directory argument. Whenever those two disagreed, it counted zero indexes
    and reported "0 of N case directories hold a Qdrant index" while they sat
    right there. Fifteen assertions in section E caught it, but only because
    section E probes directories that are not the configured root.
    """
    print("\n=== E2. the two legal homes for a case index ===")

    # The regression itself: index in the cases directory, the writer's base
    # pointing somewhere else entirely, and the probed tree IS the configured
    # root. Old code reported 0 here.
    tree = build_cases_tree("lay_legacy", ["c1", "c2"], qdrant_cases=["c1"],
                            bytes_per_file=64 * 1024, files_per_index=2)
    other = _p("lay_elsewhere")
    with qdrant_layout(tree, other):
        r = sh.probe_vector_store(tree)
    check("an index beside its case is counted, even when the writer "
          "stores them elsewhere",
          r["case_collections"] == 1, r["case_collections"])
    check("it is reported as un-migrated, by count",
          r["unmigrated_collections"] == 1, r["unmigrated_collections"])
    check("and the reason names the location it should be at",
          "lay_elsewhere" in (r["reason"] or "").lower(), r["reason"])
    # The consequence, not just the layout. get_client() creates whatever
    # directory it is handed, so a case indexed only in-cases gets a fresh
    # empty collection on the next query and searches it for nothing. A health
    # page that only says "the layout is untidy" would let an investigator
    # read a fully indexed case as an empty one -- the exact conclusion this
    # page exists to prevent.
    check("and the reason says those cases will return NO RESULTS, "
          "because that is the actual consequence",
          "no results" in (r["reason"] or "").lower()
          and "migrate" in (r["reason"] or "").lower(), r["reason"])
    check("a measured un-migrated index is degraded, not ok",
          r["state"] != "ok", r["state"])

    # A skipped file makes the total a lower bound rather than removing it, so
    # the two failure shapes are distinct and each has its own wording.
    _tree_skipped = build_cases_tree("lay_skip", ["s1"], qdrant_cases=["s1"],
                                     bytes_per_file=16, files_per_index=4)
    _base_skipped = _p("lay_skip_store")
    _real_cap2 = sh._MAX_WALK_FILES
    try:
        sh._MAX_WALK_FILES = 2
        with qdrant_layout(_tree_skipped, _base_skipped):
            r_skip = sh.probe_vector_store(_tree_skipped)
    finally:
        sh._MAX_WALK_FILES = _real_cap2
    # Exceeding the cap yields NO size at all (an existing, correct rule), so
    # there is no total to call a lower bound -- the cap note already says the
    # on-disk size was not measured. The hint earns its keep in the *partial*
    # case: a file that cannot be stat'ed makes the total a lower bound, and
    # when an un-migrated index was the one walked the number omits a real
    # index without saying so.
    check("hitting the cap reports no size AND names the un-migrated index",
          r_skip["total_size_mb"] is None
          and "no results" in (r_skip["reason"] or "").lower(),
          (r_skip["total_size_mb"], r_skip["reason"]))
    check("and the cap is restored", sh._MAX_WALK_FILES == _real_cap2,
          sh._MAX_WALK_FILES)

    # The other home: the writer's canonical location. This is what a healthy
    # relocated deployment looks like, and the old code handled it -- so this
    # assertion cannot fail on the old code, and is here to stop the FIX from
    # breaking the path that used to work.
    # No qdrant_cases here: this case is indexed ONLY at the canonical
    # location. Creating the in-cases copy as well would make it a duplicate,
    # which is the next assertion's job to check.
    tree2 = build_cases_tree("lay_canon", ["k1", "k2"])
    base = _p("lay_canon_store")
    _make_index(os.path.join(base, "k2", "qdrant"))
    with qdrant_layout(tree2, base):
        r2 = sh.probe_vector_store(tree2)
    check("an index at the canonical location is still counted",
          r2["case_collections"] == 1, r2["case_collections"])
    check("a canonically-stored index is not called un-migrated",
          r2["unmigrated_collections"] == 0, r2["unmigrated_collections"])
    check("and the canonical case is clean",
          r2["state"] == "ok", r2.get("reason"))

    # Both homes. Two copies of one index is a real defect that
    # migrate_qdrant_layout() refuses to paper over by overwriting, so it is
    # named rather than silently collapsed into one number.
    tree3 = build_cases_tree("lay_both", ["d1", "d2"], qdrant_cases=["d1"],
                             bytes_per_file=64 * 1024, files_per_index=2)
    base3 = _p("lay_both_store")
    _make_index(os.path.join(base3, "d1", "qdrant"))
    with qdrant_layout(tree3, base3):
        r3 = sh.probe_vector_store(tree3)
    check("a case indexed in BOTH places counts once, not twice",
          r3["case_collections"] == 1, r3["case_collections"])
    check("the duplication is counted", r3["duplicate_collections"] == 1,
          r3["duplicate_collections"])
    one_index = round(2 * 64 * 1024 / (1024 * 1024), 2)
    check("and the size counts the canonical copy only, not both",
          r3["total_size_mb"] == one_index,
          (r3["total_size_mb"], one_index))
    check("duplication is degraded with a reason saying so",
          r3["state"] != "ok" and "both" in (r3["reason"] or "").lower(),
          (r3["state"], r3["reason"]))

    # A tree that is NOT this machine's configured root. Publishing a
    # migration verdict about a directory the app does not use is the same
    # fabrication as publishing a count for one it never measured -- and it is
    # what made the first attempt at this fix fail section A.
    plain = build_cases_tree("lay_plain", ["q1"], qdrant_cases=["q1"],
                             bytes_per_file=1024, files_per_index=1)
    elsewhere = sh.probe_vector_store(plain)   # no qdrant_layout wrapper
    check("a directory that is not the configured root reports the split as "
          "None, not 0",
          elsewhere["unmigrated_collections"] is None
          and elsewhere["duplicate_collections"] is None,
          (elsewhere["unmigrated_collections"],
           elsewhere["duplicate_collections"]))
    check("and such a directory carries no migration reason",
          "migrat" not in (elsewhere.get("reason") or "").lower(),
          elsewhere.get("reason"))
    check("but the count for it is still real",
          elsewhere["case_collections"] == 1, elsewhere["case_collections"])


def section_cases_dir():
    """
    Existence is not writability, and on this platform a read-only
    directory cannot even be made — measured, not assumed.
    """
    print("\n=== F. cases directory: exists AND writable ===")
    tree = build_cases_tree("cd_ok", ["c1"])
    r = sh.probe_cases_dir(tree)
    check("a writable cases directory is ok", r["state"] == "ok", r["detail"])
    check("writability is reported as a measured True, not None",
          r["writable"] is True, r["writable"])
    check("a writable directory carries no reason", r["reason"] is None,
          r["reason"])
    check("the case directory count is measured", r["case_dirs"] == 1,
          r["case_dirs"])

    # Why this is stubbed rather than created: on Windows the read-only
    # attribute does not stop a directory being written, and
    # os.access(W_OK) still answers True. Verified before relying on it.
    probe_dir = _p("ro_probe")
    os.makedirs(probe_dir, exist_ok=True)
    os.chmod(probe_dir, stat.S_IREAD)
    attribute_honoured = not os.access(probe_dir, os.W_OK)
    fd = tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=probe_dir)
    except Exception:
        attribute_honoured = True
    finally:
        if fd is not None:
            os.close(fd)
        if tmp:
            os.remove(tmp)
        os.chmod(probe_dir, stat.S_IWRITE)
    if attribute_honoured:
        skip("measured unwritable directory (platform honours it)",
             "unavailable on this platform")
    else:
        print("  note: a read-only directory is still writable on this "
              "platform, so the unwritable check is simulated")

    with stub_writable(False):
        r_ro = sh.probe_cases_dir(tree)
    check("an unwritable cases directory is an error",
          r_ro["state"] == "error", f"{r_ro['state']}: {r_ro['detail']}")
    check("an unwritable cases directory reports writable False, not None",
          r_ro["writable"] is False, r_ro["writable"])
    check("an unwritable cases directory carries the reason",
          "not writable" in (r_ro["reason"] or "").lower()
          or "permission" in (r_ro["reason"] or "").lower(), r_ro["reason"])
    check("an unwritable cases directory never fabricates a 0 case count",
          r_ro["case_dirs"] != 0, r_ro["case_dirs"])
    check("an unwritable cases directory still reports the real count it "
          "measured by listing (a read-only directory is still listable)",
          r_ro["case_dirs"] == 1, r_ro["case_dirs"])

    missing = sh.probe_cases_dir(_p("definitely-absent"))
    check("a missing cases directory is an error", missing["state"] == "error",
          missing["detail"])
    check("a missing cases directory reports no count, never 0",
          missing["case_dirs"] is None, missing["case_dirs"])
    check("a missing cases directory carries a reason", bool(missing["reason"]))

    # The vector-store half needs a tree that actually HAS an index. On the
    # tree above the honest answer is 0, so "never fabricates a 0" would
    # pass on a fixture where 0 is the truth and prove nothing.
    vs_tree = build_cases_tree("cd_vs", ["c1", "c2"], qdrant_cases=["c1"],
                               bytes_per_file=1024, files_per_index=1)
    check("the vector-store fixture really does contain one index",
          sh.probe_vector_store(vs_tree)["case_collections"] == 1)
    with stub_writable(False):
        vs_ro = sh.probe_vector_store(vs_tree)
    check("an unwritable cases directory fails the vector store too",
          vs_ro["state"] == "error", f"{vs_ro['state']}: {vs_ro['detail']}")
    check("vector_store: an unwritable parent names writability in the "
          "reason", "writable" in (vs_ro["reason"] or "").lower(),
          vs_ro["reason"])
    check("vector_store: an unwritable parent still reports the count it "
          "measured by listing — a read-only directory is still listable, "
          "so 0 here would be the fabrication",
          vs_ro["case_collections"] == 1, vs_ro["case_collections"])


def section_embeddings():
    """
    `torch` and `sentence_transformers` are lazy optional imports (B15), so
    "importable" is a real question — and a missing package must be a named
    fault, not a green light.
    """
    print("\n=== G. embeddings: optional deps, and the air-gap question ===")
    r = sh.probe_embeddings()
    check("embeddings: state is a known value", r["state"] in STATES,
          r["state"])
    check("embeddings: detail is non-empty whatever the state",
          bool(r["detail"]), r["detail"])
    if r["state"] == "ok":
        check("embeddings: an ok result carries no reason",
              r["reason"] is None, r["reason"])
    else:
        check("embeddings: a non-ok result MUST carry a reason",
              bool(r["reason"]), r["reason"])
    check("embeddings: availability flags are bools or None, never 0",
          all(r[k] is None or isinstance(r[k], bool)
              for k in ("torch_available", "sentence_transformers_available",
                        "model_cached")),
          (r["torch_available"], r["sentence_transformers_available"]))

    with stub_find_spec(present=set()):
        r_missing = sh.probe_embeddings()
    check("a missing optional package is an error, not ok",
          r_missing["state"] == "error",
          f"{r_missing['state']}: {r_missing['reason']}")
    check("the missing package is named",
          "torch" in (r_missing["reason"] or ""), r_missing["reason"])
    check("a missing package is reported as False, not None",
          r_missing["torch_available"] is False,
          r_missing["torch_available"])
    check("a missing package yields no vector_size rather than a restated 384",
          r_missing["vector_size"] == 384, r_missing["vector_size"])

    with stub_find_spec(present={"torch"}, raiser="sentence_transformers"):
        r_raiser = sh.probe_embeddings()
    check("a package lookup that RAISES is 'unavailable', not 'error'",
          r_raiser["state"] == "unavailable",
          f"{r_raiser['state']}: {r_raiser['reason']}")
    check("a raising lookup is reported as None, not False",
          r_raiser["sentence_transformers_available"] is None,
          r_raiser["sentence_transformers_available"])
    check("a raising lookup is named in the reason",
          "sentence_transformers" in (r_raiser["reason"] or ""),
          r_raiser["reason"])

    with stub_find_spec(present={"torch", "sentence_transformers"}):
        r_present = sh.probe_embeddings()
    check("both packages present is ok", r_present["state"] == "ok",
          f"{r_present['state']}: {r_present['reason']}")
    check("present packages are reported True",
          r_present["torch_available"] is True
          and r_present["sentence_transformers_available"] is True,
          (r_present["torch_available"],
           r_present["sentence_transformers_available"]))
    check("the importlib stub is restored after the section",
          sh.importlib is __import__("importlib"),
          sh.importlib)


def section_degradation():
    """
    A health endpoint that 500s tells an investigator nothing about the five
    services that were fine.
    """
    print("\n=== H. one probe raising leaves the other five measured ===")
    db_path = make_db("degrade.db", rows=0)
    tree = build_cases_tree("degrade_cases", ["c1"], qdrant_cases=["c1"],
                            bytes_per_file=1024, files_per_index=2)
    real_probes = (
        ("database", sh.probe_database, False),
        ("ollama", sh.probe_ollama, False),
        ("vector_store", sh.probe_vector_store, True),
        ("worker", _boom, False),
        ("cases_dir", sh.probe_cases_dir, True),
        ("embeddings", sh.probe_embeddings, False),
    )
    with engine_on(db_path), stub_ollama(OLLAMA_READY), \
            stub_probes(real_probes):
        out = sh.collect_status(tree)

    worker = out["services"]["worker"]
    check("a raising probe degrades to 'unavailable', not a crash",
          worker["state"] == "unavailable", worker["state"])
    check("a raising probe carries the exception text as its reason",
          "probe exploded" in (worker["reason"] or ""), worker["reason"])
    for key in ("database", "ollama", "vector_store", "cases_dir",
                "embeddings"):
        check(f"{key} is still measured after its neighbour raised",
              out["services"][key]["state"] in STATES,
              out["services"][key]["state"])
    check("database is ok while the worker probe is exploding",
          out["services"]["database"]["state"] == "ok",
          out["services"]["database"]["detail"])
    check("degraded names the exploding service and the unstarted worker",
          out["degraded"] == ["worker"], out["degraded"])
    check("the legacy keys survive a broken probe",
          out["database"] in ("connected", "not found")
          and out["ollama"] in ("running", "offline")
          and isinstance(out["models"], list)
          and isinstance(out["cases_dir"], bool),
          (out["database"], out["ollama"], out["models"], out["cases_dir"]))
    check("the probe table is restored after the section",
          sh._PROBES[3][1] is not _boom, sh._PROBES[3][1])

    # Controlled states, so `degraded` is pinned exactly: two faults of
    # different kinds plus the raiser, in an order that is not already
    # sorted, and three services that must NOT appear.
    #
    # The two needs_dir stubs take the directory argument. Leaving it off
    # is a TypeError, and collect_status' per-probe guard catches it and
    # reports the service as "probe raised" — so the guard is working, but
    # the fixture silently stops testing what it was written to test.
    controlled = (
        ("worker", _boom, False),
        ("embeddings", lambda: _fake("ok", "fine"), False),
        ("database", lambda: _fake("ok", "fine", None, case_rows=1), False),
        ("ollama", lambda: _fake("error", "down", "no model",
                                 model="llama3.2:3b", model_ready=False,
                                 installed_models=[]), False),
        ("vector_store", lambda _d: _fake("ok", "fine", None,
                                          case_collections=1,
                                          total_size_mb=1.0), True),
        ("cases_dir", lambda _d: _fake("unavailable", "nope", "no dir"), True),
    )
    with stub_probes(controlled):
        out = sh.collect_status(tree)
    check("degraded is exactly the three non-ok services",
          out["degraded"] == ["cases_dir", "ollama", "worker"],
          out["degraded"])
    check("degraded is sorted, whatever order the probes ran in",
          out["degraded"] == sorted(out["degraded"]), out["degraded"])
    check("degraded omits the services that are ok",
          "database" not in out["degraded"]
          and "vector_store" not in out["degraded"]
          and "embeddings" not in out["degraded"], out["degraded"])
    check("an 'unavailable' service is degraded, not excused",
          "cases_dir" in out["degraded"], out["degraded"])


def section_no_caching():
    print("\n=== I. no probe caches its answer ===")
    db_a = make_db("cache_a.db", rows=1)
    db_b = make_db("cache_b.db", rows=7)
    with engine_on(db_a):
        first = sh.probe_database()
    with engine_on(db_b):
        second = sh.probe_database()
    check("the row count is re-read on every call, not cached",
          (first["case_rows"], second["case_rows"]) == (1, 7),
          (first["case_rows"], second["case_rows"]))

    with stub_ollama(OLLAMA_UP_NO_MODEL):
        o1 = sh.probe_ollama()
    with stub_ollama(OLLAMA_READY):
        o2 = sh.probe_ollama()
    check("the ollama answer is not cached (error, then ok)",
          (o1["state"], o2["state"]) == ("error", "ok"),
          (o1["state"], o2["state"]))
    check("the ollama model list is not cached",
          o1["installed_models"] == [] and o2["installed_models"] == ["llama3.2:3b"],
          (o1["installed_models"], o2["installed_models"]))

    with stub_ollama(OLLAMA_READY):
        r1 = sh.probe_embeddings()
        r2 = sh.probe_embeddings()
    check("embeddings is a pure probe — two calls agree",
          (r1["state"], r1["vector_size"])
          == (r2["state"], r2["vector_size"]),
          (r1["state"], r2["state"]))


def section_route():
    """
    The route itself: `system_status()` must hand the frontend the measured
    payload, and the real cases directory must not be the one counted.
    """
    print("\n=== J. the /api/status route ===")
    import backend.main as main_mod

    db_path = make_db("route.db", rows=2)
    tree = build_cases_tree("route_cases", ["r1", "r2", "r3"],
                            qdrant_cases=["r1", "r2"],
                            bytes_per_file=32 * 1024, files_per_index=1)

    class _SettingsShim:
        """Delegates everything except cases_dir."""

        def __init__(self, real, cases_dir):
            self._real = real
            self.cases_dir = cases_dir

        def __getattr__(self, name):
            return getattr(self._real, name)

    real_settings = main_mod.settings
    main_mod.settings = _SettingsShim(real_settings, tree)
    try:
        with engine_on(db_path), stub_ollama(OLLAMA_UP_NO_MODEL):
            body = main_mod.system_status()
    finally:
        main_mod.settings = real_settings

    check("the route returns the measured payload",
          isinstance(body, dict) and "services" in body, sorted(body)[:6])
    check("the route returns the six documented services",
          set(body["services"]) == set(SERVICE_KEYS),
          sorted(body["services"]))
    check("the route counts the cases directory it was given, not a "
          "hardcoded path", body["services"]["vector_store"]["case_collections"] == 2,
          body["services"]["vector_store"]["case_collections"])
    check("the route's database reading came from the throwaway engine",
          body["services"]["database"]["case_rows"] == 2,
          body["services"]["database"]["case_rows"])
    check("the route payload is JSON-serialisable",
          json.loads(json.dumps(body))["services"]["database"]["state"] == "ok")

    missing = [f"{svc}.{key}" for svc, keys in REQUIRED_KEYS.items()
               for key in keys if key not in body["services"].get(svc, {})]
    check("the route payload has every documented key", not missing, missing)
    for key in ("database", "ollama", "models", "cases_dir"):
        check(f"the route keeps the legacy '{key}' key", key in body)

    # Over real HTTP, if httpx is installed. The lifespan is deliberately
    # NOT entered: it calls init_db() and start_worker(), and the worker
    # would reset orphaned jobs in the real database through
    # SessionLocal, which is bound to the real engine at import time and is
    # therefore NOT covered by the engine swap above.
    try:
        from fastapi.testclient import TestClient
    except Exception as exc:
        skip("GET /api/status over HTTP", f"{type(exc).__name__}: {exc}")
        return
    worker_before = job_worker._worker_thread
    with engine_on(db_path), stub_ollama(OLLAMA_UP_NO_MODEL):
        main_mod.settings = _SettingsShim(real_settings, tree)
        try:
            response = TestClient(main_mod.app).get("/api/status")
        finally:
            main_mod.settings = real_settings
    check("the lifespan did not run (no worker was started by the test)",
          job_worker._worker_thread is worker_before,
          job_worker._worker_thread)
    check("GET /api/status answers 200", response.status_code == 200,
          response.status_code)
    if response.status_code == 200:
        payload = response.json()
        check("the HTTP body has the same shape as the direct call",
              set(payload.get("services", {})) == set(SERVICE_KEYS),
              sorted(payload.get("services", {})))
        check("the HTTP body carries the six services and the legacy keys",
              all(k in payload for k in ("database", "ollama", "models",
                                         "cases_dir")))


def section_no_side_effects(fingerprint_before):
    print("\n=== K. this script left nothing behind ===")
    after = _db_fingerprint()
    # Size unchanged AND mtime unchanged. mtime is the part that matters: a
    # write of identical content still updates it, so a suite that only
    # compared sizes could write to the real database and pass.
    check(f"the real database was never opened ({fingerprint_before} -> {after})",
          after == fingerprint_before, (fingerprint_before, after))
    check("the module's real engine is restored",
          backend.database.engine is not None
          and backend.database.engine.url.database != "None",
          backend.database.engine.url)
    check("the real worker globals are restored",
          job_worker._worker_running in (True, False),
          job_worker._worker_running)
    check("the walk cap is the shipped value",
          sh._MAX_WALK_FILES >= 200_000, sh._MAX_WALK_FILES)
    with engine_on(make_db("final.db", rows=0)), stub_ollama(OLLAMA_READY):
        final = sh.collect_status(build_cases_tree("final_cases", ["c1"]))
    check("every service value is a plain dict, for the JSON encoder",
          all(isinstance(v, dict) for v in final["services"].values()),
          {k: type(v).__name__ for k, v in final["services"].items()})


def main():
    print("=" * 66)
    print("Service health verification — GET /api/status")
    print("=" * 66)

    # Re-taken here, not reused from import time. The import-time fingerprint
    # was captured before a single assertion ran, so anything that touched the
    # real database in the interim -- another process, an editor, the app's own
    # worker -- changed mtime and the closing check reported it as this suite's
    # side effect. The check is "this script did not write to it", and only a
    # reading taken around the run can answer that.
    fingerprint_before = _db_fingerprint()

    section_happy_path()
    section_database()
    section_ollama_and_legacy()
    section_worker()
    section_vector_store()
    section_qdrant_layout()
    section_cases_dir()
    section_embeddings()
    section_degradation()
    section_no_caching()
    section_route()
    section_no_side_effects(fingerprint_before)

    print(f"\n{'=' * 66}")
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}"
          + (f"    SKIPPED: {len(SKIP)}" if SKIP else ""))
    for f in FAIL:
        print(f"  FAILED: {f}")
    for s in SKIP:
        print(f"  SKIPPED: {s}")
    print("=" * 66)
    return 1 if FAIL else 0


if __name__ == "__main__":
    code = main()
    shutil.rmtree(ROOT, ignore_errors=True)
    sys.exit(code)

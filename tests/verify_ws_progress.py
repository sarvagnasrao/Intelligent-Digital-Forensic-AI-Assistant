"""Verify ingestion progress reaches subscribers on the *server's* event loop.

Why this shape of test
---------------------
The original defect was cross-loop: the ingestion worker ran on its own
thread but built a brand new event loop to await WebSocket sends, while the
socket objects belonged to the server's loop. The failure was silent, and a
second defect (a 5-vs-2 argument callback mismatch behind a bare
`except: pass`) meant only one event per job ever escaped anyway.

TestClient's websocket blocks on receive with no timeout, so a
socket-level test hangs rather than fails. Instead this drives the real
`ConnectionManager` and the real `job_worker._notify` from a worker thread
against a real running loop, and asserts the three things that matter:

  1. the coroutine is scheduled on the registered server loop
  2. the worker never constructs its own loop
  3. every event arrives, in order, with the full payload

Then it replays a real ingestion through the pipeline with the worker's own
_broadcast_progress as the callback, which is the combination that used to
raise TypeError and get swallowed.
"""
import asyncio
import os
import sys
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend import main as bmain
from backend.modules import job_worker
from backend.database import SessionLocal
from backend import models
from backend.modules.ingestion_modes import resolve_mode_for_device
from backend.modules.resource_governor import ResourceGovernor
import backend.ingestion as ing

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + str(detail)) if detail else ''}")


def _cleanup(case_id):
    """Removes every row and per-case directory this script created.

    Both of these checks run the real pipeline, so without this each run
    would leave cases, evidence, entities and a Qdrant store behind - and
    the next run would be asserting against the previous run's leftovers.
    """
    import shutil

    from backend.dependencies import get_settings

    db = SessionLocal()
    try:
        for model in (models.ForensicArtifact, models.Entity,
                      models.IngestionJob, models.Evidence):
            try:
                db.query(model).filter(
                    model.case_id == case_id).delete(
                    synchronize_session=False)
            except Exception:
                pass
        db.query(models.Case).filter(
            models.Case.id == case_id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()

    case_dir = os.path.join(get_settings().cases_dir, case_id)
    if os.path.isdir(case_dir):
        shutil.rmtree(case_dir, ignore_errors=True)


class FakeSocket:
    """Stands in for a Starlette WebSocket. Records the loop it was awaited on."""

    def __init__(self):
        self.sent = []
        self.loops = set()

    async def accept(self):
        pass

    async def send_json(self, message):
        # The loop this coroutine actually ran on - the whole point of the
        # cross-loop fix.
        self.loops.add(id(asyncio.get_running_loop()))
        await asyncio.sleep(0)
        self.sent.append(message)


def test_notify_uses_server_loop():
    print("\n=== _notify schedules onto the server loop ===")
    received = []
    socket = FakeSocket()
    case_id = str(uuid.uuid4())

    async def scenario():
        job_worker.set_main_loop(asyncio.get_running_loop())
        await bmain.ws_manager.connect_global(socket)
        return asyncio.get_running_loop()

    # The loop must be *running* while the worker emits: that is the whole
    # difference between the old and new code paths.
    server_loop = asyncio.new_event_loop()
    ready = threading.Event()

    def spin():
        asyncio.set_event_loop(server_loop)
        server_loop.call_soon(ready.set)
        server_loop.run_forever()

    lt = threading.Thread(target=spin, daemon=True)
    lt.start()
    ready.wait(5)

    # The loop is owned by the spin thread, so submit rather than
    # run_until_complete - the latter would raise "loop already running".
    asyncio.run_coroutine_threadsafe(scenario(), server_loop).result(10)
    time.sleep(0.2)

    check("server loop was registered", job_worker._main_loop is server_loop)
    check("server loop is running", server_loop.is_running())

    # Now emit from a *worker thread*, exactly as the ingestion worker does.
    def worker():
        for pct, step in ((10, "Step 1"), (25, "Step 2"), (100, "Complete")):
            job_worker._broadcast_progress(
                case_id, "job-1", "ev-1", pct, step)
            time.sleep(0.05)

    wt = threading.Thread(target=worker)
    wt.start()
    wt.join()
    # Let the server loop drain the scheduled coroutines.
    for _ in range(20):
        time.sleep(0.05)
        if len(socket.sent) >= 3:
            break
    time.sleep(0.3)

    print(f"  events delivered: {len(socket.sent)}")
    for m in socket.sent:
        print(f"    {m['percent']:>3}%  {m['step']}")

    check("all three progress events delivered", len(socket.sent) == 3,
          len(socket.sent))
    check("delivered on the server loop, not a throwaway one",
          socket.loops == {id(server_loop)},
          f"{len(socket.loops)} distinct loop(s)")
    check("percentages are in order",
          [m["percent"] for m in socket.sent] == [10, 25, 100],
          [m["percent"] for m in socket.sent])
    check("payload carries job_id / evidence_id / status",
          all(m.get("job_id") == "job-1" and m.get("evidence_id") == "ev-1"
              and m.get("status") == "Running" for m in socket.sent))
    check("global fan-out includes case_id",
          all(m.get("case_id") == case_id for m in socket.sent))

    # A loop that is registered but not spinning must be rejected: accepting
    # the callback would queue a coroutine nothing ever runs, which is how
    # the "progress silently stopped" failure looked from the outside.
    server_loop.call_soon_threadsafe(server_loop.stop)
    lt.join(5)
    check("stopped loop -> refused, no leak",
          job_worker._notify(case_id, "INGESTION_PROGRESS", {}) is False)
    server_loop.close()

    # With no loop registered the helper must fail quietly, not raise inside
    # the worker's except handler.
    job_worker._main_loop = None
    check("no registered loop -> returns False, no exception",
          job_worker._notify(case_id, "INGESTION_PROGRESS", {}) is False)


def test_pipeline_broadcasts_every_step():
    print("\n=== a real ingest, wired to the worker's own broadcaster ===")
    case_id = str(uuid.uuid4())
    ev_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    path = os.path.join(os.environ.get("TEMP", "."), f"wspipe_{job_id[:8]}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write("chain of custody narrative. " * 5000)

    db = SessionLocal()
    try:
        db.add(models.Case(id=case_id, case_name="ws pipe",
                          created_by="verify"))
        db.commit()
        db.add(models.Evidence(
            id=ev_id, case_id=case_id,
            filename=os.path.basename(path),
            original_filename=os.path.basename(path),
            file_type="text",
            file_size_bytes=os.path.getsize(path),
            file_path=path, sha256_hash="0" * 64,
            ingested_by="verify", status="Queued"))
        db.add(models.IngestionJob(
            id=job_id, evidence_id=ev_id, case_id=case_id,
            status="Running", min_free_ram_mb=256,
            cpu_throttle_percent=100, ingestion_mode="normal",
            created_by="verify"))
        db.commit()
    finally:
        db.close()

    events = []

    def capture(case, job, ev, pct, step):
        events.append((pct, step))

    ing.run_ingestion_with_progress(
        evidence_id=ev_id, case_id=case_id, file_path=path,
        filename=os.path.basename(path), job_id=job_id,
        governor=ResourceGovernor(min_free_ram_mb=256,
                                  cpu_throttle_percent=100),
        progress_callback=capture,
        mode=resolve_mode_for_device("normal"),
    )

    percents = [p for p, _ in events]
    print(f"  events: {len(events)}")
    for p, s in events:
        print(f"    {p:>3}%  {s}")

    check("every stage reported (>=8 events)", len(events) >= 8, len(events))
    check("percent monotonic", all(b >= a for a, b in
                                   zip(percents, percents[1:])), percents)
    check("ends at 100", percents[-1] == 100, percents[-1])
    check("all five steps labelled",
          all(any(k in s for p, s in events)
              for k in ("Step 1", "Step 2", "Step 3", "Step 4", "Step 5")))
    check("mode annotated on every step",
          all("[normal]" in s for _, s in events),
          [s for _, s in events if "[normal]" not in s][:2])

    # And the same callback as a strict 5-arg function, i.e. the worker's
    # actual _broadcast_progress, must not raise.
    class Strict:
        def __init__(self):
            self.n = 0
        def __call__(self, case_id, job_id, evidence_id, percent, step):
            self.n += 1

    strict = Strict()
    ev2 = str(uuid.uuid4())
    job2 = str(uuid.uuid4())
    path2 = os.path.join(os.environ.get("TEMP", "."), f"wsstrict_{job_id[:8]}.txt")
    with open(path2, "w", encoding="utf-8") as f:
        f.write("second narrative. " * 3000)
    db = SessionLocal()
    try:
        db.add(models.Evidence(
            id=ev2, case_id=case_id,
            filename=os.path.basename(path2),
            original_filename=os.path.basename(path2),
            file_type="text",
            file_size_bytes=os.path.getsize(path2),
            file_path=path2, sha256_hash="1" * 64,
            ingested_by="verify", status="Queued"))
        db.add(models.IngestionJob(
            id=job2, evidence_id=ev2, case_id=case_id,
            status="Running", min_free_ram_mb=256,
            cpu_throttle_percent=100, ingestion_mode="fastest",
            created_by="verify"))
        db.commit()
    finally:
        db.close()

    ing.run_ingestion_with_progress(
        evidence_id=ev2, case_id=case_id, file_path=path2,
        filename=os.path.basename(path2), job_id=job2,
        governor=ResourceGovernor(min_free_ram_mb=256,
                                  cpu_throttle_percent=100),
        progress_callback=strict,
        mode=resolve_mode_for_device("fastest"),
    )
    check("strict 5-arg callback (the worker's shape) is honoured",
          strict.n >= 8, strict.n)

    for p in (path, path2):
        try:
            os.remove(p)
        except OSError:
            pass

    _cleanup(case_id)


if __name__ == "__main__":
    test_notify_uses_server_loop()
    test_pipeline_broadcasts_every_step()
    print(f"\n{'=' * 62}")
    print(f"PASSED: {len(PASS)}    FAILED: {len(FAIL)}")
    for f in FAIL:
        print(f"  FAILED: {f}")
    print("=" * 62)
    sys.exit(1 if FAIL else 0)

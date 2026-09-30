"""
Verifies that the Stop button can actually stop a running ingestion job.

The button is only half the system: the other half is that the signal the
endpoint sends is observed by the thread doing the work, and that the job
reaches a truthful terminal state when it does. All three are asserted here,
because each has failed on its own before:

  * the API contract   - POST /queue/{id}/stop must be the one that works;
                         DELETE /queue/{id}/cancel is documented to refuse a
                         Running job, which is why a UI wired to /cancel
                         showed a red 400 instead of stopping anything.
  * the mechanism      - job_worker.stop_job() sets a threading.Event that
                         the ingestion thread must observe. The worker runs
                         jobs on its own thread, so this is a cross-thread
                         handshake, and it is silent when it breaks: the job
                         simply keeps going.
  * the terminal state - a stop must end as "Stopped", never "Failed" and
                         never a row frozen at whatever percent it reached.

Part A drives the real _process_job (the worker's own entry point, so its
status/broadcast handling is included) on a worker thread and fires the stop
from this thread, which is the same relationship the API has to a running
job. Part B pins the HTTP contract.

Run:  PYTHONPATH=. python tests/verify_job_stop.py
"""
import os
import sys
import time
import uuid
import tempfile
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The Windows console defaults to cp1252 and chokes on the em-dash used in
# the assertion labels. Force UTF-8 rather than silently dropping output.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS, FAIL = [], []

from _purge import Purge                                     # noqa: E402
_PURGE = Purge("verify_job_stop")

# A paragraph repeated enough times to produce roughly 100 chunks at the
# "accurate" chunk size. The size matters: the document path embeds a batch of
# up to 64 chunks, and store_chunks now embeds that batch in slices of 16
# with a stop check between them. Fewer chunks than that would fit in a
# single slice, and the test would then prove only that a stop cannot be
# noticed mid-slice - which is true, and not what is being fixed.
BODY = ("Suspect transferred funds to an offshore account. " * 15000)


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}"
          f"{(' — ' + str(detail)) if detail else ''}")


def _cleanup(case_id, settings):
    """Remove every row and per-case directory the test created."""
    from backend.database import SessionLocal
    from backend import models
    from backend.modules import vector_store
    import shutil

    # Release the per-case Qdrant client first. While one is open the
    # directory is locked, and on Windows shutil.rmtree then fails silently,
    # leaving a vector store on disk for a case that no longer exists.
    try:
        if vector_store.close_client(
                os.path.join(settings.cases_dir, case_id, "qdrant")):
            print(f"  (closed Qdrant client for {case_id[:8]})")
    except Exception:
        pass

    db = SessionLocal()
    try:
        for model in (models.ForensicArtifact, models.Entity,
                      models.IngestionJob, models.Evidence):
            try:
                db.query(model).filter(model.case_id == case_id).delete(
                    synchronize_session=False)
            except Exception:
                db.rollback()
        db.query(models.Case).filter(models.Case.id == case_id).delete(
            synchronize_session=False)
        db.commit()
    except Exception as e:
        print(f"  (cleanup warning: {e})")
        db.rollback()
    finally:
        db.close()
    try:
        shutil.rmtree(os.path.join(settings.cases_dir, case_id),
                      ignore_errors=True)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Part A — the mechanism
# ---------------------------------------------------------------------------

def part_a():
    from backend.database import SessionLocal
    from backend import models
    from backend.modules import job_worker
    import backend.ingestion as ing

    print("\n=== A. stop signal reaches the running job ===")

    # Make each embedding batch slow enough to interrupt. Left alone, this
    # file embeds in a few seconds, so the job can finish before the test can
    # even observe it running - which would make every assertion below pass
    # for the wrong reason. The real store_chunks is still called; only a
    # delay is added in front of it.
    _real_store = ing.store_chunks
    BATCH_DELAY = 0.5

    def _slow_store(**kwargs):
        time.sleep(BATCH_DELAY)
        return _real_store(**kwargs)

    ing.store_chunks = _slow_store

    db = SessionLocal()
    case_id = str(uuid.uuid4())
    # Tracked as soon as it exists so the atexit hook is a real safety net for
    # a run that dies before `_cleanup` at the end of main().
    _PURGE.ids(case_id)
    ev_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    tmp_dir = tempfile.mkdtemp(prefix="idfai_stop_test_")
    src = os.path.join(tmp_dir, "ledger.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write(BODY)

    db.add(models.Case(
        id=case_id, case_number=f"STOP-{uuid.uuid4().hex[:6].upper()}",
        case_name="Stop verification", description="Stop button end-to-end",
        status="Active", created_by="verify"))
    db.add(models.Evidence(
        id=ev_id, case_id=case_id, filename="ledger.txt",
        original_filename="ledger.txt", file_path=src,
        file_size_bytes=os.path.getsize(src), file_type="text",
        sha256_hash="0" * 64, ingested_by="verify", status="Queued"))
    db.add(models.IngestionJob(
        id=job_id, evidence_id=ev_id, case_id=case_id, status="Running",
        progress_percent=0, min_free_ram_mb=256, cpu_throttle_percent=100,
        ingestion_mode="accurate", created_by="verify"))
    db.commit()
    job = db.query(models.IngestionJob).filter(
        models.IngestionJob.id == job_id).first()
    db.close()

    outcome = {}

    def _run():
        """Exactly what the worker loop does for a queued job."""
        try:
            job_worker._process_job(job)
            outcome["exc"] = None
        except BaseException as e:            # noqa: BLE001 - recorded, not swallowed
            outcome["exc"] = e

    t = threading.Thread(target=_run, name="verify-stop", daemon=True)
    t.start()

    # The job is inserted as Running, never Queued, on purpose. _process_job
    # re-queries the row and sets Running itself, and the background worker's
    # _get_next_job only ever selects Queued rows - so a Running fixture is
    # invisible to it. Leaving it Queued means a server already running on
    # this database picks the job up and runs it in a second process, which
    # then fights this thread for the same per-case Qdrant directory and
    # fails with "Storage folder ... is already accessed by another instance".

    # Wait until the pipeline is genuinely in flight. progress_percent is
    # written synchronously by _update_job_progress, so the row is a reliable
    # signal that the worker got past job setup.
    #
    # The session is rolled back on every poll because a SQLAlchemy session
    # holds its read transaction open until commit/rollback/close. Without
    # that, the loop re-reads the same snapshot and reports 0% forever - it
    # watched a job run to completion and never saw any of it.
    s = SessionLocal()
    try:
        seen_percent = 0
        deadline = time.time() + 90
        while time.time() < deadline:
            row = s.query(models.IngestionJob).filter(
                models.IngestionJob.id == job_id).first()
            if row:
                seen_percent = max(seen_percent, row.progress_percent or 0)
            s.rollback()
            if seen_percent >= 40:
                break
            if not t.is_alive():
                break
            time.sleep(0.1)
    finally:
        s.close()

    check("job reached the embedding band before the stop (>=40%)",
          seen_percent >= 40, f"saw {seen_percent}%")
    check("job was still running when the stop was sent", t.is_alive(),
          "already finished" if not t.is_alive() else "")

    t_stop = time.time()
    job_worker.stop_job(job_id)
    check("is_stop_requested flips immediately after stop_job()",
          job_worker.is_stop_requested(job_id))

    t.join(timeout=90)
    elapsed = time.time() - t_stop
    check("worker thread halted after the stop signal", not t.is_alive(),
          f"still running after {elapsed:.1f}s")
    # The bound here is generous on purpose. Stopping is cooperative, so the
    # latency is whatever the in-flight unit of work costs, and that depends
    # on how loaded the machine is - asserting a tight number would make this
    # a benchmark of the host rather than a test of the stop path. The
    # assertion that actually matters is below: that the work was cut short
    # instead of running to completion. This one only catches "hangs for
    # ever", which is the original symptom.
    check("halt did not hang (< 90s)", not t.is_alive() and elapsed < 90,
          f"{elapsed:.1f}s after the stop signal")
    print(f"  (stop latency {elapsed:.1f}s - the in-flight embed slice)")

    exc = outcome.get("exc")
    stopped_exc = (isinstance(exc, StopIteration)
                   or "stopped by user" in str(exc).lower())
    check("pipeline surfaced a stop, not a failure",
          exc is None or stopped_exc,
          f"{type(exc).__name__}: {str(exc)[:90]}" if exc else "returned normally")

    ing.store_chunks = _real_store

    s = SessionLocal()
    try:
        row = s.query(models.IngestionJob).filter(
            models.IngestionJob.id == job_id).first()
        ev = s.query(models.Evidence).filter(
            models.Evidence.id == ev_id).first()
        check("job reached a terminal status", row is not None
              and row.status in ("Stopped", "Completed"), row.status if row else None)
        check("a user stop is recorded as 'Stopped', not 'Failed'",
              row is not None and row.status == "Stopped",
              row.status if row else None)
        check("stopped job has completed_at set",
              row is not None and row.completed_at is not None)
        check("evidence reverted to Uploaded so it can be re-queued",
              ev is not None and ev.status == "Uploaded",
              ev.status if ev else None)

        # The assertion that actually distinguishes a working stop from a
        # job that simply ran to completion. A Stop that is acknowledged but
        # ignored looks exactly like success in every other field: the job
        # ends, and the evidence ends Indexed. What gives it away is that all
        # the work got done - progress reached 100 and the whole document was
        # indexed. So require that the job stopped short of finishing.
        check("stop cut the work short (progress < 100%)",
              row is not None and (row.progress_percent or 0) < 100,
              f"progress={row.progress_percent if row else None}")
        check("evidence was not marked Indexed",
              ev is not None and ev.status != "Indexed",
              ev.status if ev else None)
    finally:
        s.close()

    return case_id


# ---------------------------------------------------------------------------
# Part B — the HTTP contract
# ---------------------------------------------------------------------------

def part_b():
    from fastapi.testclient import TestClient
    from backend.main import app
    from backend.database import SessionLocal
    from backend import models
    from backend.modules import job_worker

    print("\n=== B. HTTP contract ===")

    case_id = str(uuid.uuid4())
    ev_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    src = os.path.join(tempfile.gettempdir(), "stop_contract.txt")

    with TestClient(app) as client:
        email = f"stop_{uuid.uuid4().hex[:8]}@idfai.test"
        _reg = client.post("/api/auth/register", json={
            "username": email, "email": email, "password": "Verify@2026",
            "full_name": "Stop Verifier", "role": "Investigator"})
        # The throwaway account was never deleted, so data/forensic.db grew by
        # one `stop_*` user per run -- see tests/_purge.py. Tracked by id *and*
        # username: the audit row registration writes carries the username in
        # `performed_by`, so deleting by id alone would orphan it.
        try:
            _PURGE.user((_reg.json() or {}).get("id"), email)
        except Exception:
            _PURGE.user(None, email)
        r = client.post("/api/auth/login", data={
            "username": email, "password": "Verify@2026"})
        token = (r.json() or {}).get("access_token")
        if not token:
            r = client.post("/api/auth/login", data={
                "username": "admin", "password": "Admin@IDF2025"})
            token = (r.json() or {}).get("access_token")
        if not token:
            print("  SKIP  could not authenticate")
            return case_id
        H = {"Authorization": f"Bearer {token}"}

        # Promote to Investigator in the database, rather than asking for the
        # role at registration. `/register` used to honour a client-supplied
        # "role", which was a privilege-escalation hole (any anonymous caller
        # could register as Admin); it now assigns Analyst to every user after
        # the first and ignores the request. This suite was relying on that
        # hole to get a privileged token — a test passing because of a
        # vulnerability — so the role is obtained here the way an
        # administrator would grant it. require_role() re-reads `user.role` on
        # every request, so no re-login is needed.
        _db = SessionLocal()
        try:
            _me = _db.query(models.User).filter(
                models.User.username == email).first()
            if _me:
                _me.role = "Investigator"
                _db.commit()
        finally:
            _db.close()

        # The fixture is created only now, on purpose. TestClient's startup
        # runs the real background worker, whose orphan sweep flips any
        # pre-existing Running job back to Queued and then ingests it. A
        # fixture written before the client starts is therefore raced by the
        # worker and stops being Running by the time the endpoints are
        # called, which silently invalidates the status-guarded assertions
        # below. _get_next_job only ever selects Queued rows, so a job
        # inserted as Running after startup is left alone.
        with open(src, "w", encoding="utf-8") as f:
            f.write("contract fixture")
        db = SessionLocal()
        db.add(models.Case(
            id=case_id, case_number=f"STOPC-{uuid.uuid4().hex[:6].upper()}",
            case_name="Stop contract", description="HTTP shape of the stop button",
            status="Active", created_by="verify"))
        db.add(models.Evidence(
            id=ev_id, case_id=case_id, filename="stop_contract.txt",
            original_filename="stop_contract.txt", file_path=src,
            file_size_bytes=os.path.getsize(src), file_type="text",
            sha256_hash="0" * 64, ingested_by="verify", status="Processing"))
        db.add(models.IngestionJob(
            id=job_id, evidence_id=ev_id, case_id=case_id, status="Running",
            progress_percent=50, min_free_ram_mb=256, cpu_throttle_percent=100,
            ingestion_mode="normal", created_by="verify"))
        db.commit()
        db.close()

        # The endpoint the Stop button calls.
        r = client.post(f"/api/queue/{job_id}/stop", headers=H)
        check("POST /queue/{id}/stop returns 200 for a Running job",
              r.status_code == 200, f"{r.status_code} {r.text[:140]}")
        check("POST /stop actually raised the worker's stop flag",
              job_worker.is_stop_requested(job_id),
              "flag not set — the endpoint acknowledged but signalled nothing")

        # The other delete verb must keep refusing, otherwise a UI wired to
        # it looks broken to the operator.
        r = client.delete(f"/api/queue/{job_id}/cancel", headers=H)
        check("DELETE /queue/{id}/cancel still refuses a Running job",
              r.status_code == 400, f"{r.status_code} {r.text[:140]}")

        job_worker._cleanup_job(job_id)

        # A job that already finished must not accept a stop.
        s = SessionLocal()
        try:
            j = s.query(models.IngestionJob).filter(
                models.IngestionJob.id == job_id).first()
            if j:
                j.status = "Completed"
                s.commit()
        finally:
            s.close()
        r = client.post(f"/api/queue/{job_id}/stop", headers=H)
        check("POST /stop rejects a job that is not Running",
              r.status_code == 400, f"{r.status_code}")

        r = client.post("/api/queue/does-not-exist-at-all/stop", headers=H)
        check("POST /stop on an unknown job is 404, not 500",
              r.status_code == 404, f"{r.status_code}")

    return case_id


def main():
    from backend.dependencies import get_settings
    settings = get_settings()
    os.makedirs(settings.cases_dir, exist_ok=True)

    case_ids = []
    for fn in (part_a, part_b):
        try:
            case_ids.append(fn())
        except Exception as e:
            import traceback
            traceback.print_exc()
            check(f"{fn.__name__} completed", False, f"{type(e).__name__}: {e}")
    for cid in case_ids:
        if cid:
            _cleanup(cid, settings)

    print(f"\n{'=' * 60}")
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"    FAILED: {f}")
    print(f"{'=' * 60}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

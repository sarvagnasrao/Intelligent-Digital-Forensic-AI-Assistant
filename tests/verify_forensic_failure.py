"""A failed disk-image ingest must reach a terminal state and never announce success.

Found by a browser pass, not by reading the code. The queue page's settings
panel reported `applied_live: false` for a job the worker was demonstrably
running, which sent me to the backend log - where a job sat at
`Running` / 20% / "Step 3: Walking filesystem" with an empty
`error_message`, while the same log held:

    [FORENSIC] PIPELINE FAILED: Mount failed: Could not open any filesystem ...
    [FORENSIC] PIPELINE FAILED: Mount failed: Could not open any filesystem ...

...and never `[WORKER] Job failed`. The truncated image is B1's own test case
(§6): the truncation pre-flight and the real TSK diagnostic both worked
perfectly. What was broken is everything *after* the failure.

## The defect

§14 fixed B11 - "a failed job stayed Running for ever" - by making the
handlers re-raise instead of returning normally. The document pipeline was
corrected. **The forensic pipeline was not**: the outer handler in
`_run_forensic_with_progress` printed the traceback, marked the *evidence*
failed, and fell off the end of the `except` block. So:

  * the IngestionJob row was never touched - it stayed `Running` at whatever
    percent it had reached, with an empty `error_message`;
  * `run_ingestion_with_progress` saw a normal return, so its own handler
    (which marks the job `Failed` and re-raises) never ran;
  * `job_worker._process_job` saw a normal return too, skipped its failure
    handler, and **broadcast `INGESTION_COMPLETE`** for a job that had failed.

The last one is the worst: a success event went out over the WebSocket for a
job that recovered nothing, while the row sat in `Running` for ever. An
investigator watching that queue concludes the disk image yielded no artifacts
- which, for a truncated evidence copy, is precisely the conclusion B1 exists
to prevent them from drawing.

## The second defect, one layer down

The per-file handler in the walk loop was `except Exception: print; continue`.
`StopIteration` subclasses `Exception`, and `governor.check_and_throttle()`
raises it on a user stop - so a stop was swallowed **once per file** and the
walk carried on across the rest of the image. This is the trap §15 documents,
in the one place §15's fix did not reach.

Both are guarded here as outcomes, not as spies: this drives the real worker
and asserts what the queue row and the WebSocket actually say.
"""
import os
import random
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

PASS, FAIL = [], []


def check(label, cond, detail=""):
    (PASS if cond else FAIL).append(label)
    print(f"  {'PASS' if cond else 'FAIL'}  {label}{(' — ' + str(detail)) if detail else ''}")


def _fixture(db, models, filename, file_path, size):
    """A case + evidence + a job already in Running.

    Running, never Queued, on purpose: `_get_next_job` only ever selects
    `Queued` rows, so a Running fixture is invisible to a worker in another
    process. See AGENTS.md section 10.
    """
    case_id, ev_id, job_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    db.add(models.Case(
        id=case_id, case_number=f"FF-{uuid.uuid4().hex[:6].upper()}",
        case_name="Forensic failure", description="failure must be terminal",
        status="Active", created_by="verify"))
    db.add(models.Evidence(
        id=ev_id, case_id=case_id, filename=filename,
        original_filename=filename, file_path=file_path,
        file_size_bytes=size, file_type="disk-image",
        sha256_hash="0" * 64, ingested_by="verify", status="Processing"))
    db.add(models.IngestionJob(
        id=job_id, evidence_id=ev_id, case_id=case_id, status="Running",
        progress_percent=0, min_free_ram_mb=0, cpu_throttle_percent=100,
        ingestion_mode="normal", created_by="verify"))
    db.commit()
    return case_id, ev_id, job_id


def _purge(db, models, ids):
    for m in (models.IngestionJob, models.Evidence, models.Case):
        db.query(m).filter(m.id.in_(ids)).delete(synchronize_session=False)
    db.commit()


# ---------------------------------------------------------------------------
# Part A — a mount failure is terminal, and says so
# ---------------------------------------------------------------------------

def part_a():
    from backend.database import SessionLocal
    from backend import models
    from backend.modules import job_worker

    print("\n=== A. a disk image that cannot be mounted ends Failed, not Running ===")

    # 4 MB of random bytes. pytsk3 opens any file as an image; there is no
    # partition table and no recognisable filesystem anywhere in it, so
    # _walk_all_filesystems raises with the real TSK diagnostic - which is
    # exactly the path a truncated evidence copy takes.
    tmp = tempfile.mkdtemp(prefix="idfai_ffail_")
    img = os.path.join(tmp, "unmountable.dd")
    with open(img, "wb") as f:
        f.write(bytes(random.getrandbits(8) for _ in range(4 * 1024 * 1024)))

    db = SessionLocal()
    try:
        case_id, ev_id, job_id = _fixture(
            db, models, "unmountable.dd", img, os.path.getsize(img))
        job = db.query(models.IngestionJob).filter(
            models.IngestionJob.id == job_id).first()
    finally:
        db.close()

    # Capture what the queue would have been told over the WebSocket.
    events = []
    real_broadcast = job_worker._broadcast_event

    def _spy(case_id, event_type, payload):
        events.append(event_type)
        return real_broadcast(case_id, event_type, payload)

    job_worker._broadcast_event = _spy
    exc = {}

    def _run():
        try:
            job_worker._process_job(job)
            exc["e"] = None
        except BaseException as e:          # noqa: BLE001 - recorded, not swallowed
            exc["e"] = e

    t = threading.Thread(target=_run, name="verify-ffail-a", daemon=True)
    try:
        t.start()
        t.join(timeout=180)
    finally:
        job_worker._broadcast_event = real_broadcast

    check("the worker thread finished", not t.is_alive(),
          "timed out after 180s")
    # _process_job is the *terminal* handler and is supposed to swallow - its
    # job is to mark the row and broadcast. The property that was actually
    # broken is one layer down, so it is asserted separately in A2 below: that
    # run_ingestion_with_progress re-raises rather than returning normally.

    db = SessionLocal()
    try:
        j = db.query(models.IngestionJob).filter(
            models.IngestionJob.id == job_id).first()
        ev = db.query(models.Evidence).filter(
            models.Evidence.id == ev_id).first()
        status = j.status if j else None
        err = (j.error_message or "") if j else ""
        done = j.completed_at if j else None
        ev_status = ev.status if ev else None
    finally:
        db.close()

    # The core assertion. Before the fix this read "Running".
    check("the job reached a terminal state", status == "Failed", status)
    check("the job is NOT left Running", status != "Running", status)
    check("the job carries an error message", bool(err.strip()),
          err[:100] or "(empty)")
    check("the job has a terminal timestamp", done is not None, done)
    check("the TSK diagnostic survived to the row",
          "filesystem" in err.lower() or "mount" in err.lower(), err[:120])
    check("the evidence is Failed, not Indexed", ev_status == "Failed",
          ev_status)

    check("a failure was broadcast", "INGESTION_FAILED" in events, events)
    check("success was NOT broadcast for a failed job",
          "INGESTION_COMPLETE" not in events, events)

    db = SessionLocal()
    try:
        _purge(db, models, [case_id, ev_id, job_id])
    finally:
        db.close()
    try:
        os.remove(img)
        os.rmdir(tmp)
    except OSError:
        pass


def part_a2():
    """The re-raise itself, at the boundary that was broken.

    Driven directly rather than through the worker, because the worker's own
    handler is a terminal handler and swallows by design — asserting through it
    proves nothing about the re-raise. This asserts the exact property the fix
    restored: `run_ingestion_with_progress` does not return normally when the
    forensic pipeline fails.
    """
    from backend.database import SessionLocal
    from backend import models
    import backend.ingestion as ing

    print("\n=== A2. run_ingestion_with_progress re-raises a mount failure ===")

    tmp = tempfile.mkdtemp(prefix="idfai_ffail_a2_")
    img = os.path.join(tmp, "unmountable2.dd")
    with open(img, "wb") as f:
        f.write(bytes(random.getrandbits(8) for _ in range(2 * 1024 * 1024)))

    db = SessionLocal()
    try:
        case_id, ev_id, job_id = _fixture(
            db, models, "unmountable2.dd", img, os.path.getsize(img))
    finally:
        db.close()

    raised = None
    try:
        ing.run_ingestion_with_progress(
            evidence_id=ev_id, case_id=case_id, file_path=img,
            filename="unmountable2.dd", job_id=job_id)
    except BaseException as e:              # noqa: BLE001 - this is the assertion
        raised = e

    check("the pipeline raised instead of returning normally",
          raised is not None, "returned normally" if raised is None else type(raised).__name__)
    check("the raised error names the mount failure",
          raised is not None and "mount" in str(raised).lower(),
          str(raised)[:90] if raised else "")

    db = SessionLocal()
    try:
        j = db.query(models.IngestionJob).filter(
            models.IngestionJob.id == job_id).first()
        status = j.status if j else None
    finally:
        db.close()
    check("the job was marked Failed on the way out", status == "Failed", status)

    db = SessionLocal()
    try:
        _purge(db, models, [case_id, ev_id, job_id])
    finally:
        db.close()
    try:
        os.remove(img)
        os.rmdir(tmp)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Part B — a user stop is not swallowed by the per-file handler
# ---------------------------------------------------------------------------

def part_b():
    from backend.database import SessionLocal
    from backend import models
    import backend.ingestion as ing

    print("\n=== B. a stop inside the file loop is not swallowed ===")

    tmp = tempfile.mkdtemp(prefix="idfai_ffail_stop_")
    img = os.path.join(tmp, "walk.dd")
    with open(img, "wb") as f:
        f.write(b"\0" * 4096)

    db = SessionLocal()
    try:
        case_id, ev_id, job_id = _fixture(
            db, models, "walk.dd", img, os.path.getsize(img))
    finally:
        db.close()

    # Yield exactly one file, so the walk loop is genuinely entered and the
    # per-file handler is genuinely reached. Before the fix the handler
    # swallowed the sentinel and the function returned normally.
    real_ingest_raw = ing.ingest_raw
    real_extract = ing.extract_file_content

    def _fake_walk(*a, **k):
        yield {"internal_path": "/notes.txt", "filename": "notes.txt",
               "size": 5, "sha256_hash": "0" * 64, "modified": None,
               "accessed": None, "created": None, "born": None}

    def _fake_extract(file_info, *a, **k):
        return {"extracted_text": "a recovered note", "internal_path": "/notes.txt",
                "filename": "notes.txt", "size": 5, "sha256_hash": "0" * 64,
                "modified": None, "accessed": None, "created": None, "born": None,
                "extraction_type": "text"}

    class _StopGovernor:
        """Raises the stop sentinel at the throttle call inside the loop."""
        def check_and_throttle(self):
            raise StopIteration("Ingestion stopped by user")

    ing.ingest_raw = _fake_walk
    ing.extract_file_content = _fake_extract
    outcome = {}
    try:
        ing.run_ingestion_with_progress(
            evidence_id=ev_id, case_id=case_id, file_path=img,
            filename="walk.dd", job_id=job_id, governor=_StopGovernor(),
        )
        outcome["raised"] = None
    except StopIteration as e:
        outcome["raised"] = e
    except BaseException as e:              # noqa: BLE001 - classified below
        outcome["raised"] = e
    finally:
        ing.ingest_raw = real_ingest_raw
        ing.extract_file_content = real_extract

    check("the stop sentinel reached the caller",
          isinstance(outcome.get("raised"), StopIteration),
          type(outcome.get("raised")).__name__)

    db = SessionLocal()
    try:
        j = db.query(models.IngestionJob).filter(
            models.IngestionJob.id == job_id).first()
        ev = db.query(models.Evidence).filter(
            models.Evidence.id == ev_id).first()
        status = j.status if j else None
        ev_status = ev.status if ev else None
    finally:
        db.close()

    # A stop is not a failure. The evidence must stay re-queueable.
    check("the job is Stopped, not Failed", status == "Stopped", status)
    check("the evidence reverted to Uploaded, not Failed",
          ev_status == "Uploaded", ev_status)

    db = SessionLocal()
    try:
        _purge(db, models, [case_id, ev_id, job_id])
    finally:
        db.close()
    try:
        os.remove(img)
        os.rmdir(tmp)
    except OSError:
        pass


def main():
    from backend.database import SessionLocal
    from backend import models

    # Leave no Running row behind if an earlier run died mid-test: the worker
    # resets those to Queued on startup and would then execute them.
    db = SessionLocal()
    try:
        stale = [j.id for j in db.query(models.IngestionJob).filter(
            models.IngestionJob.created_by == "verify",
            models.IngestionJob.status == "Running").all()]
        for jid in stale:
            db.query(models.IngestionJob).filter(
                models.IngestionJob.id == jid).delete(
                    synchronize_session=False)
        db.commit()
    finally:
        db.close()

    part_a()
    part_a2()
    part_b()

    print("\n" + "=" * 62)
    print(f"  {len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        for f in FAIL:
            print(f"    FAILED: {f}")
    print("=" * 62)
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

import threading
import time
import asyncio
from datetime import datetime
from backend.database import SessionLocal
from backend import models
from backend.modules.resource_governor import ResourceGovernor

_worker_thread = None
_worker_running = False
_worker_lock = threading.Lock()

# The server's event loop, captured at startup by set_main_loop(). Worker
# threads schedule their WebSocket sends onto it.
_main_loop = None

# Per-job control: job_id -> threading.Event (set = stop requested)
_job_stop_events: dict = {}
# Per-job override: job_id -> bool (True = bypass resource limits)
_job_overrides: dict = {}
_jobs_lock = threading.Lock()

# Live governors of currently-running jobs: job_id -> ResourceGovernor.
# Registered by _process_job so PATCH /queue/{id}/settings can change the
# limits of a job that is already running. Without this the endpoint
# rewrote the database row and the running governor carried on using the
# values it was constructed with, so "takes effect on next batch" never
# happened for a job that was already past its first batch.
_live_governors: dict = {}


def set_main_loop(loop):
    """
    Called from the FastAPI lifespan with the server's event loop.

    Progress events are produced on a worker thread but the WebSocket
    objects belong to the server loop, so sends have to be scheduled back
    onto it.
    """
    global _main_loop
    _main_loop = loop
    print("[WORKER] Main event loop registered for progress updates")


def _register_governor(job_id: str, governor: ResourceGovernor):
    with _jobs_lock:
        _live_governors[job_id] = governor


def _unregister_governor(job_id: str):
    with _jobs_lock:
        _live_governors.pop(job_id, None)


def update_job_limits(job_id: str, min_free_ram_mb=None,
                      cpu_throttle_percent=None) -> bool:
    """
    Applies new limits to a running job. Returns True if the job was
    running and the change was applied live, False if it was not running
    (in which case the caller has already persisted the values and the
    worker will pick them up when the job starts).
    """
    with _jobs_lock:
        governor = _live_governors.get(job_id)
    if governor is None:
        return False
    governor.update_limits(
        min_free_ram_mb=min_free_ram_mb,
        cpu_throttle_percent=cpu_throttle_percent,
    )
    print(
        f"[WORKER] Live limits for {job_id[:8]}: "
        f"CPU<={governor.cpu_throttle_percent}% "
        f"RAM floor {governor.min_free_ram_mb}MB"
    )
    return True


def governor_snapshot(job_id: str) -> dict:
    """Current throttling state of a running job, for the UI."""
    with _jobs_lock:
        governor = _live_governors.get(job_id)
    if governor is None:
        return {"running": False}
    return {
        "running": True,
        "min_free_ram_mb": governor.min_free_ram_mb,
        "cpu_throttle_percent": governor.cpu_throttle_percent,
        "force_override": governor.force_override,
        "ram_pauses": governor.total_pauses,
        "throttle_seconds": round(governor.total_throttle_seconds, 1),
        "reason": governor.last_reason,
    }


def force_start_job(job_id: str):
    """
    Marks a Queued job as 'override' so the worker picks it up
    immediately, bypassing RAM/CPU resource checks.
    If job is already Running, sets override flag so the governor
    stops throttling/pausing.
    """
    with _jobs_lock:
        _job_overrides[job_id] = True
        # Clear any pending stop for this job
        if job_id in _job_stop_events:
            _job_stop_events[job_id].clear()
    print(f"[WORKER] Force-start override set for job {job_id[:8]}")


def stop_job(job_id: str):
    """
    Requests a graceful stop for a running job.
    Sets a threading.Event the governor checks on each batch.
    The job will be marked Failed/Stopped once the current step finishes.
    """
    with _jobs_lock:
        ev = _job_stop_events.setdefault(job_id, threading.Event())
        ev.set()
        _job_overrides.pop(job_id, None)
    print(f"[WORKER] Stop requested for job {job_id[:8]}")


def is_stop_requested(job_id: str) -> bool:
    with _jobs_lock:
        ev = _job_stop_events.get(job_id)
        return ev is not None and ev.is_set()


def is_override(job_id: str) -> bool:
    with _jobs_lock:
        return _job_overrides.get(job_id, False)


def _cleanup_job(job_id: str):
    with _jobs_lock:
        _job_stop_events.pop(job_id, None)
        _job_overrides.pop(job_id, None)
    _unregister_governor(job_id)

def start_worker():
    """
    Starts the background queue worker
    if not already running.
    Called once on app startup.
    """
    global _worker_thread, _worker_running
    with _worker_lock:
        if (_worker_thread is not None and
            _worker_thread.is_alive()):
            return

        # ── Cleanup Orphaned Jobs ─────────────────────────────────────
        # If the server was restarted while jobs were Running, they will
        # be stuck in Running state in the DB and ignored by the queue.
        # Reset them to Queued so they restart automatically.
        db = SessionLocal()
        try:
            orphans = db.query(models.IngestionJob).filter(
                models.IngestionJob.status == "Running"
            ).all()
            for job in orphans:
                print(f"[WORKER] Resetting orphaned job {job.id[:8]} to Queued")
                job.status = "Queued"
                job.progress_percent = 0
                job.current_step = "Re-queued after server restart"
                
                # Reset evidence status
                ev = db.query(models.Evidence).filter(
                    models.Evidence.id == job.evidence_id
                ).first()
                if ev:
                    ev.status = "Uploaded"
            
            db.commit()
        except Exception as e:
            print(f"[WORKER] Failed to reset orphaned jobs: {e}")
        finally:
            db.close()
        # ──────────────────────────────────────────────────────────────

        _worker_running = True
        _worker_thread = threading.Thread(
            target=_worker_loop,
            daemon=True,
            name="ingestion-worker"
        )
        _worker_thread.start()
        print("[WORKER] Ingestion queue worker started")

def stop_worker():
    """Signals the worker to stop."""
    global _worker_running
    _worker_running = False


def _notify(case_id: str, event_type: str, payload: dict) -> bool:
    """
    Schedules a WebSocket broadcast on the server's event loop and returns
    without waiting for it.

    This used to create a brand new event loop inside the worker thread and
    run _notify_case on it. That cannot work: the WebSocket objects were
    accepted on the server's loop, and awaiting send_json from a different
    loop either raised or silently never reached the client. The result was
    progress that updated in the database but never on screen, and a stream
    of "broadcast_progress error" lines in the backend log.

    Now the coroutine is handed to the server loop with
    run_coroutine_threadsafe, which is the supported way to call into a
    loop you do not own.
    """
    try:
        from backend.main import _notify_case
    except Exception as e:
        print(f"[WS] cannot import _notify_case: {e}")
        return False

    loop = _main_loop
    # is_running() matters as much as is_closed(): a loop that is registered
    # but not spinning accepts the callback and then never executes it, which
    # leaks the coroutine ("was never awaited") and drops the event silently.
    if loop is None or loop.is_closed() or not loop.is_running():
        return False

    coro = _notify_case(case_id, event_type, payload)
    try:
        asyncio.run_coroutine_threadsafe(coro, loop)
        return True
    except Exception as e:
        # Never leave an un-awaited coroutine behind on the failure path.
        try:
            coro.close()
        except Exception:
            pass
        print(f"[WS] schedule {event_type} failed: {e}")
        return False


def _broadcast_progress(case_id: str, job_id: str, evidence_id: str,
                         percent: int, step: str, status: str = "Running"):
    """
    Emits INGESTION_PROGRESS over WebSocket so the frontend
    can update the queue page in real time without polling.
    """
    _notify(case_id, "INGESTION_PROGRESS", {
        "job_id":         job_id,
        "evidence_id":    evidence_id,
        "percent":        percent,
        "step":           step,
        "status":         status,
    })


def _broadcast_event(case_id: str, event_type: str, payload: dict):
    """Generic fire-and-forget broadcast used for complete/failed events."""
    _notify(case_id, event_type, payload)


def _worker_loop():
    """
    Main worker loop. Continuously checks
    for queued jobs and processes them
    one at a time.
    """
    global _worker_running
    print("[WORKER] Worker loop running")

    while _worker_running:
        try:
            job = _get_next_job()
            if job:
                _process_job(job)
            else:
                # No jobs — sleep 2s before checking again
                time.sleep(2)
        except Exception as e:
            print(f"[WORKER] Loop error: {e}")
            time.sleep(10)

def _get_next_job():
    """
    Gets the next queued job.
    Jobs with force_override=True are prioritised.
    """
    db = SessionLocal()
    try:
        # Priority: overridden jobs first
        with _jobs_lock:
            override_ids = [jid for jid, v in _job_overrides.items() if v]
        if override_ids:
            job = db.query(models.IngestionJob).filter(
                models.IngestionJob.id.in_(override_ids),
                models.IngestionJob.status == "Queued"
            ).first()
            if job:
                return job
        # Normal FIFO
        job = db.query(
            models.IngestionJob
        ).filter(
            models.IngestionJob.status == "Queued"
        ).order_by(
            models.IngestionJob.queue_position,
            models.IngestionJob.queued_at
        ).first()
        return job
    finally:
        db.close()

def _process_job(job):
    """Processes a single ingestion job."""
    db = SessionLocal()
    try:
        # Mark as running
        job = db.query(
            models.IngestionJob
        ).filter(
            models.IngestionJob.id == job.id
        ).first()
        if not job:
            return

        job.status = "Running"
        job.started_at = datetime.utcnow()
        job.current_step = "Step 1/5: Starting ingestion"
        db.commit()

        evidence = db.query(
            models.Evidence
        ).filter(
            models.Evidence.id == job.evidence_id
        ).first()
        if not evidence:
            job.status = "Failed"
            job.error_message = "Evidence record not found"
            db.commit()
            return

        evidence.status = "Processing"
        db.commit()

        # Capture identifiers before db closes
        job_id_str    = job.id
        case_id_str   = job.case_id
        evidence_id_s = job.evidence_id
        file_path_s   = evidence.file_path
        filename_s    = evidence.filename
        min_ram       = job.min_free_ram_mb
        cpu_pct       = job.cpu_throttle_percent
        # Absent on rows written before the column existed -> falls back to
        # "normal" inside resolve_mode_for_device.
        mode_key      = getattr(job, "ingestion_mode", None)

        # Resolve the mode against this machine before announcing the job, so
        # the step text can state what will actually happen.
        from backend.modules.ingestion_modes import (
            resolve_mode_for_device, get_mode)
        mode = resolve_mode_for_device(mode_key)
        for warn in mode.get("warnings") or []:
            print(f"[WORKER] Mode '{mode['key']}': {warn}")

        if mode["key"] == "accurate":
            job.current_step = (
                "Step 1/5: Starting ingestion "
                f"(accurate · {mode['whisper_model']} transcription"
                f"{' on GPU' if mode['whisper_gpu'] else ''}"
                f"{' · deleted-file recovery' if mode['include_deleted'] else ''})"
            )
            db.commit()
            _mode_note = f" [mode: {mode['key']}]"
        else:
            _mode_note = ""

        # Broadcast initial start over WebSocket
        _broadcast_progress(
            case_id_str, job_id_str, evidence_id_s,
            0, f"Step 1/5: Starting ingestion{_mode_note}", "Running"
        )

        db.close()

        # Create resource governor —
        # bypass limits if force-override is active
        if is_override(job_id_str):
            governor = ResourceGovernor(
                min_free_ram_mb=0,          # no RAM floor
                cpu_throttle_percent=100,   # full speed
                force_override=True
            )
            print(f"[WORKER] OVERRIDE MODE — resource limits bypassed for {job_id_str[:8]}")
        else:
            governor = ResourceGovernor(
                min_free_ram_mb=min_ram,
                cpu_throttle_percent=cpu_pct
            )

        # Expose the live governor so PATCH /queue/{id}/settings can retune
        # this job while it runs, instead of only writing the row.
        _register_governor(job_id_str, governor)

        # Run ingestion with job tracking + progress broadcast
        from backend.ingestion import run_ingestion_with_progress

        def _stop_check():
            return is_stop_requested(job_id_str)

        try:
            run_ingestion_with_progress(
                evidence_id=evidence_id_s,
                case_id=case_id_str,
                file_path=file_path_s,
                filename=filename_s,
                job_id=job_id_str,
                governor=governor,
                progress_callback=_broadcast_progress,
                stop_check=_stop_check,
                mode=mode
            )
        finally:
            _unregister_governor(job_id_str)

        # ── Emit INGESTION_COMPLETE via WebSocket ───────────────────────────────
        _broadcast_event(
            case_id_str,
            "INGESTION_COMPLETE",
            {
                "evidence_id": evidence_id_s,
                "filename":    filename_s,
                "message":     f"{filename_s} has been ingested",
                "job_id":      job_id_str,
            },
        )
        _cleanup_job(job_id_str)

    except Exception as e:
        print(f"[WORKER] Job failed: {e}")
        import traceback
        traceback.print_exc()
        # Use job_id_str if we got that far, else fall back to job.id
        _jid = locals().get('job_id_str') or getattr(job, 'id', None)
        _cid = locals().get('case_id_str') or getattr(job, 'case_id', None)
        _eid = locals().get('evidence_id_s') or getattr(job, 'evidence_id', None)
        db2 = SessionLocal()
        try:
            if _jid:
                j = db2.query(models.IngestionJob).filter(
                    models.IngestionJob.id == _jid
                ).first()
                if j:
                    j.status = "Stopped" if is_stop_requested(_jid) else "Failed"
                    j.error_message = str(e)
                    j.current_step = "Stopped by user" if is_stop_requested(_jid) else "Failed — see error"
                    db2.commit()
            if _eid:
                ev = db2.query(models.Evidence).filter(
                    models.Evidence.id == _eid
                ).first()
                if ev:
                    ev.status = "Uploaded" if is_stop_requested(_jid) else "Failed"
                    ev.error_message = str(e)
                    db2.commit()
        finally:
            db2.close()

        # ── Emit INGESTION_FAILED via WebSocket ───────────────────────────────
        if _cid:
            _broadcast_event(
                _cid,
                "INGESTION_FAILED",
                {
                    "evidence_id": _eid,
                    "message":     f"Ingestion stopped" if is_stop_requested(_jid) else f"Ingestion failed: {str(e)[:120]}",
                    "job_id":      _jid,
                },
            )
        if _jid:
            _cleanup_job(_jid)
    finally:
        try:
            db.close()
        except:
            pass

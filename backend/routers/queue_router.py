from fastapi import (
    APIRouter, Depends, HTTPException,
    BackgroundTasks)
from sqlalchemy.orm import Session
from backend.database import get_db
from backend import models
from backend.auth import (
    get_current_user, require_investigator, require_analyst)
from backend.modules.time_estimator import (
    estimate_ingestion_time,
    estimate_queue_total)
from backend.modules.resource_governor import (
    get_system_info, suggest_resource_budget)
from backend.modules.hardware_probe import rescan_hardware
from backend.modules.ingestion_modes import (
    describe_modes, get_mode, resolve_mode_for_device,
    suggest_budget, MODE_TIME_FACTOR, DEFAULT_MODE)
from pydantic import BaseModel, Field
from typing import Optional
import uuid
from datetime import datetime

router = APIRouter(
    prefix="/queue",
    tags=["Ingestion Queue"]
)

# Fields describe_modes() already surfaces on the parent object. Repeating
# them inside "effective" would just give the UI two places to read from.
_MODE_UI_FIELDS = frozenset({
    "key", "label", "tagline", "description", "speed", "accuracy",
    "time_factor",
})

class QueueJobRequest(BaseModel):
    evidence_id: str
    case_id: str
    # Both limits are optional now. When omitted they are filled from the
    # live device budget instead of a hardcoded 2 GB / 70%, which is what
    # made the queue form offer a 0-8 GB range on a 16 GB machine.
    min_free_ram_mb: Optional[int] = None
    cpu_throttle_percent: Optional[int] = None
    # 'fastest' | 'normal' | 'accurate'. None resolves to the default.
    ingestion_mode: Optional[str] = None

class BulkQueueRequest(BaseModel):
    jobs: list[QueueJobRequest]

@router.get("/system-info")
def get_system_info_endpoint(
    current_user = Depends(get_current_user)
):
    """
    Returns the live hardware + device inventory of this machine, the
    ingestion profiles on offer, and a resource budget derived from both.

    The inventory is re-scanned whenever the set of attached devices
    changes (see hardware_probe.DEFAULT_TTL_SECONDS), so hot-plugged
    evidence drives and eGPUs show up without restarting the backend.
    Use POST /queue/system-info/rescan to force an immediate re-walk.
    """
    info = get_system_info()
    budget = suggest_budget(info)
    return {
        "system": info,
        # Same payload under a clearer name. The System Resource monitor
        # (Evidence page and Queue page) reads this so both surfaces show
        # an identical hardware description.
        "hardware": info,
        "suggested_budget": budget,
        # The three profiles. Sent from the server so the UI never has to
        # hardcode a label or a description that can drift from the code.
        "modes": describe_modes(),
        "default_mode": "normal",
    }

@router.post("/system-info/rescan")
def rescan_system_info_endpoint(
    current_user = Depends(get_current_user)
):
    """
    Forces an immediate full re-scan of the hardware and device
    inventory, bypassing the short cache. Call this after attaching
    evidence media or an external GPU.
    """
    info = rescan_hardware()
    # Keep the legacy aliases the rest of the codebase expects.
    info["cpu_count"] = info.get("cpu_count_logical") or 0
    info["platform"] = info.get("platform_machine") or "unknown"
    return {
        "system": info,
        "hardware": info,
        "suggested_budget": suggest_budget(info),
        "modes": describe_modes(),
        "default_mode": "normal",
        "rescanned": True
    }

@router.get("/modes")
def list_modes_endpoint(
    current_user = Depends(get_current_user)
):
    """
    The three ingestion profiles, each already resolved against this
    machine so the UI can show which transcription model and how much
    concurrency will actually be used.
    """
    info = get_system_info()
    resolved = []
    for m in describe_modes():
        eff = resolve_mode_for_device(m["key"], info)
        # Send the whole resolved profile rather than a hand-picked subset.
        # A subset is a maintenance trap: the first time someone adds a knob
        # to ingestion_modes.MODES, the UI silently keeps showing the old
        # set and the two disagree about what the job will actually do.
        m["effective"] = {
            k: v for k, v in eff.items() if k not in _MODE_UI_FIELDS}
        resolved.append(m)
    return {
        "modes": resolved,
        "default_mode": DEFAULT_MODE,
        "budget": suggest_budget(info),
    }

@router.post("/estimate")
def estimate_time(
    body: dict,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Estimates ingestion time for one or
    more evidence files.
    Body: {evidence_ids: [...], cpu_throttle_percent: 70,
           ingestion_mode: 'fastest'|'normal'|'accurate'}

    The estimate is mode-aware, so asking for 'accurate' quotes the slower,
    more complete pass rather than the balanced baseline.
    """
    evidence_ids = body.get("evidence_ids", [])
    # Fall back to the device budget rather than a hardcoded 70%, so the
    # throttle shown here matches what the job will actually run under.
    throttle = body.get("cpu_throttle_percent")
    if throttle is None:
        throttle = suggest_budget()["cpu_throttle_percent"]
    mode_key = body.get("ingestion_mode")

    files = []
    for eid in evidence_ids:
        ev = db.query(
            models.Evidence
        ).filter(
            models.Evidence.id == eid
        ).first()
        if ev:
            files.append({
                "filename": ev.filename,
                "file_size_bytes": ev.file_size_bytes
            })

    if not files:
        raise HTTPException(
            status_code=404,
            detail="No evidence found")

    return estimate_queue_total(files, throttle, mode_key)

@router.post("/add")
def add_to_queue(
    body: QueueJobRequest,
    current_user = Depends(require_investigator),
    db: Session = Depends(get_db)
):
    """
    Adds an evidence file to the ingestion queue.
    """
    # Check not already queued
    existing = db.query(
        models.IngestionJob
    ).filter(
        models.IngestionJob.evidence_id == body.evidence_id,
        models.IngestionJob.status.in_(["Queued", "Running"])
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Already in queue")

    # Delete any existing Failed/Completed job to avoid UNIQUE constraint violation
    old_job = db.query(models.IngestionJob).filter(
        models.IngestionJob.evidence_id == body.evidence_id
    ).first()
    if old_job:
        db.delete(old_job)
        db.commit()


    # Resolve the profile, and the device budget for anything the operator
    # did not override. Values left None are filled from the live machine
    # rather than from the old hardcoded 2 GB / 70% defaults.
    mode = resolve_mode_for_device(body.ingestion_mode)
    budget = suggest_budget()

    cpu_pct = body.cpu_throttle_percent
    if cpu_pct is None:
        cpu_pct = budget["cpu_throttle_percent"]
    if not 10 <= int(cpu_pct) <= 100:
        raise HTTPException(
            status_code=400,
            detail="cpu_throttle_percent must be 10-100")

    ram_mb = body.min_free_ram_mb
    if ram_mb is None:
        ram_mb = budget["ram_floor_default_mb"]
    if int(ram_mb) < 0:
        raise HTTPException(
            status_code=400,
            detail="min_free_ram_mb must be >= 0")
    # A floor above the RAM this machine can ever free would park the job
    # in a wait loop indefinitely, so cap it at what is actually available.
    ram_mb = int(min(int(ram_mb), budget["ram_floor_max_mb"]))

    # Get queue position
    max_pos = db.query(
        models.IngestionJob
    ).filter(
        models.IngestionJob.status == "Queued"
    ).count()

    # Get time estimate
    ev = db.query(models.Evidence).filter(
        models.Evidence.id == body.evidence_id
    ).first()
    estimate = None
    if ev:
        est = estimate_ingestion_time(
            ev.filename,
            ev.file_size_bytes,
            cpu_pct,
            mode_key=mode["key"]
        )
        estimate = est["total_seconds"]

    job = models.IngestionJob(
        id=str(uuid.uuid4()),
        evidence_id=body.evidence_id,
        case_id=body.case_id,
        status="Queued",
        queue_position=max_pos,
        min_free_ram_mb=ram_mb,
        cpu_throttle_percent=int(cpu_pct),
        ingestion_mode=mode["key"],
        estimated_seconds=estimate,
        created_by=current_user.username
    )
    db.add(job)

    # Update evidence status to Queued
    if ev:
        ev.status = "Queued"
        ev.ingestion_job_id = job.id
        db.commit()

    return {
        "job_id": job.id,
        "queue_position": max_pos + 1,
        "ingestion_mode": mode["key"],
        "cpu_throttle_percent": int(cpu_pct),
        "min_free_ram_mb": ram_mb,
        "estimated_seconds": estimate,
        "estimated_human": _fmt(estimate) if estimate else "Unknown",
        "mode_warnings": mode.get("warnings") or [],
        "budget": budget,
    }

@router.post("/add-bulk")
def add_bulk_to_queue(
    body: BulkQueueRequest,
    current_user = Depends(require_investigator),
    db: Session = Depends(get_db)
):
    """Adds multiple files to queue."""
    results = []
    for job_req in body.jobs:
        try:
            # Reuse add logic
            result = add_to_queue(job_req, current_user, db)
            results.append({
                "evidence_id": job_req.evidence_id,
                "success": True,
                **result
            })
        except HTTPException as e:
            results.append({
                "evidence_id": job_req.evidence_id,
                "success": False,
                "error": e.detail
            })
    return {"results": results}

@router.get("")
def get_queue(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns all jobs in the queue."""
    jobs = db.query(
        models.IngestionJob
    ).filter(
        models.IngestionJob.status.in_(["Queued", "Running", "Paused"])
    ).order_by(
        models.IngestionJob.queue_position
    ).all()

    return [{
        "id": j.id,
        "evidence_id": j.evidence_id,
        "case_id": j.case_id,
        "status": j.status,
        "queue_position": j.queue_position,
        "progress_percent": j.progress_percent,
        "current_step": j.current_step,
        "estimated_seconds": j.estimated_seconds,
        "started_at": str(j.started_at) if j.started_at else None,
        "cpu_throttle_percent": j.cpu_throttle_percent,
        "min_free_ram_mb": j.min_free_ram_mb
    } for j in jobs]

@router.get("/history")
def get_queue_history(
    limit: int = 20,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Returns completed/failed jobs."""
    jobs = db.query(
        models.IngestionJob
    ).filter(
        models.IngestionJob.status.in_(["Completed", "Failed", "Cancelled"])
    ).order_by(
        models.IngestionJob.completed_at.desc()
    ).limit(limit).all()

    return [{
        "id": j.id,
        "evidence_id": j.evidence_id,
        "status": j.status,
        "progress_percent": j.progress_percent,
        "current_step": j.current_step,
        "estimated_seconds": j.estimated_seconds,
        "started_at": str(j.started_at) if j.started_at else None,
        "completed_at": str(j.completed_at) if j.completed_at else None,
        "error_message": j.error_message
    } for j in jobs]

@router.get("/list")
def list_all_jobs(
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Returns ALL jobs (active + history) in a single call.
    Used by the Queue Management page to power its unified table.
    Active jobs first (Running, Queued, Paused), then Completed/Failed/Cancelled
    ordered by most-recently-finished.
    """
    # Active jobs — all statuses except terminal ones
    active = db.query(models.IngestionJob).filter(
        models.IngestionJob.status.in_(["Queued", "Running", "Paused"])
    ).order_by(models.IngestionJob.queue_position).all()

    # History — most recent first, cap at 50 to keep payload small
    history = db.query(models.IngestionJob).filter(
        models.IngestionJob.status.in_(["Completed", "Failed", "Cancelled"])
    ).order_by(models.IngestionJob.completed_at.desc()).limit(50).all()

    def _row(j):
        # Try to pull filename from the linked evidence record for display
        ev = db.query(models.Evidence).filter(
            models.Evidence.id == j.evidence_id
        ).first()
        # Live throttling state, so the queue can explain a stalled job
        # instead of just showing a percentage that is not moving.
        from backend.modules.job_worker import governor_snapshot
        gov = governor_snapshot(j.id)
        return {
            "id": j.id,
            "evidence_id": j.evidence_id,
            "case_id": j.case_id,
            "status": j.status,
            "queue_position": j.queue_position,
            "progress_percent": j.progress_percent,
            "progress": j.progress_percent,   # alias for frontend compat
            "current_step": j.current_step,
            "ingestion_mode": j.ingestion_mode or "normal",
            "estimated_seconds": j.estimated_seconds,
            "elapsed_seconds": j.elapsed_seconds,
            "started_at": str(j.started_at) if j.started_at else None,
            "completed_at": str(j.completed_at) if j.completed_at else None,
            "error_message": j.error_message,
            "created_by": j.created_by,
            "cpu_throttle_percent": j.cpu_throttle_percent,
            "min_free_ram_mb": j.min_free_ram_mb,
            "governor": gov,
            # Evidence display fields
            "filename": ev.filename if ev else None,
            "original_filename": ev.filename if ev else None,
            "chunk_count": ev.chunk_count if ev else None,
            "entity_count": ev.entity_count if ev else None,
        }

    return [_row(j) for j in active + history]

@router.delete("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    current_user = Depends(require_investigator),
    db: Session = Depends(get_db)
):
    """Cancels a queued job."""
    job = db.query(
        models.IngestionJob
    ).filter(
        models.IngestionJob.id == job_id
    ).first()
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found")
    if job.status == "Running":
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a running job. Wait for it to complete or restart the server."
        )
    job.status = "Cancelled"
    job.completed_at = datetime.utcnow()
    # Reset evidence status
    ev = db.query(
        models.Evidence
    ).filter(
        models.Evidence.id == job.evidence_id
    ).first()
    if ev:
        ev.status = "Uploaded"
    db.commit()
    return {"success": True}

@router.delete("/{job_id}")
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_user = Depends(require_analyst)
):
    """
    Permanently removes a completed, failed, or cancelled job from history.
    Running jobs cannot be deleted — stop or cancel them first.
    """
    job = db.query(
        models.IngestionJob
    ).filter(
        models.IngestionJob.id == job_id
    ).first()
    if not job:
        raise HTTPException(
            status_code=404,
            detail="Job not found")
    if job.status == "Running":
        raise HTTPException(
            status_code=400,
            detail="Cannot delete a running job — stop it first")
    db.delete(job)
    db.commit()
    return {"message": "Job removed from history"}

def _fmt(seconds) -> str:
    if not seconds:
        return "Unknown"
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        return f"{h}h {m}m"


# ---------------------------------------------------------------------------
# Force-start (manual override — bypasses resource limits)
# ---------------------------------------------------------------------------

@router.post("/{job_id}/force-start")
def force_start_job_endpoint(
    job_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Immediately starts or resumes a Queued job, bypassing all
    CPU/RAM resource limits. Use when time-critical or when very
    little work remains. The job runs at full speed regardless of
    available system resources.
    """
    job = db.query(models.IngestionJob).filter(
        models.IngestionJob.id == job_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("Queued", "Running"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is {job.status} — can only force-start Queued or Running jobs"
        )

    from backend.modules.job_worker import force_start_job
    force_start_job(job_id)

    # Update DB to reflect override mode
    job.current_step = (job.current_step or "") + " [OVERRIDE]"
    db.commit()

    return {
        "ok": True,
        "job_id": job_id,
        "message": "Force-start override activated — resource limits bypassed",
    }


# ---------------------------------------------------------------------------
# Stop (graceful stop of a running job)
# ---------------------------------------------------------------------------

@router.post("/{job_id}/stop")
def stop_job_endpoint(
    job_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Requests a graceful stop of a running ingestion job.
    The current processing batch completes, then the job is marked
    Stopped and the evidence reverts to Uploaded status so it can be
    re-queued later.
    """
    job = db.query(models.IngestionJob).filter(
        models.IngestionJob.id == job_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "Running":
        raise HTTPException(
            status_code=400,
            detail=f"Job is {job.status} — can only stop Running jobs"
        )

    from backend.modules.job_worker import stop_job
    stop_job(job_id)

    job.current_step = "Stopping…"
    db.commit()

    return {
        "ok": True,
        "job_id": job_id,
        "message": "Stop signal sent — job will halt after current batch",
    }


# ---------------------------------------------------------------------------
# Update settings (live resource spec edit for Queued or Running jobs)
# ---------------------------------------------------------------------------

@router.patch("/{job_id}/settings")
def update_job_settings(
    job_id: str,
    body: dict,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Update CPU throttle % and/or min free RAM for a job at any time.
    For Running jobs the new limits take effect on the next batch check.
    Body: { cpu_throttle_percent?: int, min_free_ram_mb?: int }
    """
    job = db.query(models.IngestionJob).filter(
        models.IngestionJob.id == job_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status not in ("Queued", "Running"):
        raise HTTPException(
            status_code=400,
            detail=f"Job is {job.status} — can only edit Queued or Running jobs"
        )

    changed = []
    live_applied = False
    if "cpu_throttle_percent" in body:
        v = int(body["cpu_throttle_percent"])
        if not 10 <= v <= 100:
            raise HTTPException(
                status_code=400,
                detail="cpu_throttle_percent must be 10-100"
            )
        job.cpu_throttle_percent = v
        changed.append(f"CPU→{v}%")

    if "min_free_ram_mb" in body:
        v = int(body["min_free_ram_mb"])
        if v < 0:
            raise HTTPException(
                status_code=400,
                detail="min_free_ram_mb must be ≥ 0"
            )
        # Never accept a floor the machine could not satisfy.
        budget = suggest_budget()
        v = int(min(v, budget["ram_floor_max_mb"]))
        job.min_free_ram_mb = v
        changed.append(f"RAM floor→{v}MB")

    if "ingestion_mode" in body:
        mode = resolve_mode_for_device(body["ingestion_mode"])
        job.ingestion_mode = mode["key"]
        changed.append(f"mode→{mode['key']}")

    db.commit()

    # A queued job has no governor yet, so the row above is enough - the
    # worker reads it at start. A running job does, so push the new limits
    # into the live governor too; otherwise the edit only ever showed up in
    # the database while the job carried on with the old numbers.
    if job.status == "Running":
        from backend.modules.job_worker import update_job_limits
        live_applied = update_job_limits(
            job.id,
            min_free_ram_mb=job.min_free_ram_mb,
            cpu_throttle_percent=job.cpu_throttle_percent,
        )

    return {
        "ok": True,
        "job_id": job_id,
        "changed": changed,
        "cpu_throttle_percent": job.cpu_throttle_percent,
        "min_free_ram_mb": job.min_free_ram_mb,
        "ingestion_mode": job.ingestion_mode or "normal",
        "applied_live": live_applied,
        "note": (
            "Applied to the running job immediately."
            if live_applied else
            "Saved. Takes effect when the job starts."
        ),
    }

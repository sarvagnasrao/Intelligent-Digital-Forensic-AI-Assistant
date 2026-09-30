from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    UploadFile,
    File,
    Form,
    BackgroundTasks,
)
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session
from backend.database import get_db
from backend import models, schemas
from backend.dependencies import get_settings
from backend.auth import (
    get_current_user,
    require_viewer,
    require_analyst,
    require_investigator,
    require_admin
)
import uuid
import os
import hashlib
import aiofiles
import json
import socket
import threading
from datetime import datetime
from backend.modules.file_store import (
    get_mime_type,
    get_case_storage_stats)
from backend.modules.file_formats import (
    UPLOAD_EXTENSIONS as ALLOWED_EXTENSIONS,
    FORENSIC_IMAGE_EXTENSIONS,
    accept_string,
    category_for,
    describe_groups,
    is_forensic_image,
    is_supported_upload,
    normalize_extension,
    warn_on_mismatch,
)

router = APIRouter(
    prefix="/api/cases/{case_id}/evidence",
    tags=["Evidence"],
)

# The accepted-format policy lives in backend/modules/file_formats.py, not
# here. It used to be a hand-maintained 31-entry set in this file that was
# narrower than what the extraction cascade could already read, so the gate
# refused .log, .csv, .json and .xml - formats the pipeline handled perfectly
# well - and the frontend's file picker filtered them out before the request
# was ever sent. Kept as an alias so existing importers still resolve.
_CATEGORICAL_EXTENSIONS = ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Helper: create audit log
# ---------------------------------------------------------------------------

def _create_audit(
    db: Session,
    action_type: str,
    performed_by: str,
    details: dict,
    case_id: str = None,
):
    audit = models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type=action_type,
        performed_by=performed_by,
        performed_at=datetime.utcnow(),
        details=json.dumps(details),
        machine_id=socket.gethostname(),
    )
    db.add(audit)
    db.commit()


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence
# ---------------------------------------------------------------------------

@router.get("", response_model=list[schemas.EvidenceResponse])
def list_evidence(
    case_id: str,
    include_archived: bool = False,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Return evidence items for a case.

    Archived items are EXCLUDED by default, and that is the whole point of
    them: archiving is how an investigator takes an item out of the active
    investigation, and the confirm dialog promises exactly that ("It will be
    removed from active investigations").

    This filter was absent, so archiving set status='Archived' and the row was
    still returned and still rendered. The action succeeded, the toast said
    "Evidence archived", and nothing visibly happened -- a state change
    indistinguishable from a failed click. Archived items were not removed
    from the case; they were only relabelled.

    `include_archived=true` brings them back. It is a parameter rather than a
    second endpoint so that "how much is hidden" and "what is hidden" are
    answered by the same query that lists them, and cannot disagree.
    """
    try:
        db_case = db.query(models.Case).filter(models.Case.id == case_id).first()
        if not db_case:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Case not found",
                    detail=f"No case with id={case_id}",
                ).model_dump(),
            )

        query = db.query(models.Evidence).filter(
            models.Evidence.case_id == case_id)
        if not include_archived:
            query = query.filter(models.Evidence.status != "Archived")
        evidence_list = query.order_by(
            models.Evidence.ingested_at.desc()).all()
        return evidence_list
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve evidence",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/evidence/upload
# ---------------------------------------------------------------------------

@router.post("/upload", response_model=schemas.EvidenceResponse, status_code=201)
async def upload_evidence(
    case_id: str,
    file: UploadFile = File(...),
    include_deleted: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """
    Upload an evidence file for a case.
    Saves to disk, computes SHA-256, records in DB, writes audit log,
    then leaves extraction to the queue.
    Accepts every format in backend/modules/file_formats.py - documents,
    plain text, logs, CSV/JSON/XML, config, source, subtitles, email,
    office, images, audio, video, SQLite databases, and forensic disk
    images. For disk images, include_deleted=True will attempt
    to recover deleted files from the filesystem.
    """
    try:
        settings = get_settings()

        # 1. Verify case exists
        db_case = db.query(models.Case).filter(models.Case.id == case_id).first()
        if not db_case:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Case not found",
                    detail=f"No case with id={case_id}",
                ).model_dump(),
            )

        # 2. Verify file extension
        original_filename = file.filename or "unknown"
        ext = normalize_extension(original_filename)
        if not is_supported_upload(original_filename):
            raise HTTPException(
                status_code=400,
                detail=schemas.ErrorResponse(
                    error="Invalid file type",
                    detail=(
                        f"Unsupported file type: {ext or 'none'}. "
                        f"Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                    ),
                ).model_dump(),
            )
        warn_on_mismatch()

        # 3. Generate evidence ID
        evidence_id = str(uuid.uuid4())

        # 4. Save file to disk using aiofiles
        safe_filename = f"{evidence_id}_{original_filename}"
        file_path = os.path.join(
            settings.cases_dir, case_id, "evidence", safe_filename
        )
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Streamed rather than `content = await file.read()`. Accepting
        # .log and .csv means accepting files that are routinely hundreds of
        # megabytes, and buffering the whole body in memory to write it to
        # disk is how the upload worker runs the machine out of RAM. The
        # SHA-256 is taken from the same pass, which also removes the
        # redundant full re-read that used to follow.
        file_size_bytes = 0
        sha256 = hashlib.sha256()
        async with aiofiles.open(file_path, "wb") as out_file:
            while True:
                chunk = await file.read(4 * 1024 * 1024)  # 4 MB
                if not chunk:
                    break
                await out_file.write(chunk)
                sha256.update(chunk)
                file_size_bytes += len(chunk)

        hash_value = sha256.hexdigest()

        # Determine file_type from extension
        file_type = ext.lstrip(".")

        # 5. Create Evidence record in DB with status "Uploaded"
        db_evidence = models.Evidence(
            id=evidence_id,
            case_id=case_id,
            filename=safe_filename,
            original_filename=original_filename,
            file_type=file_type,
            file_size_bytes=file_size_bytes,
            file_path=file_path,
            sha256_hash=hash_value,
            ingested_at=datetime.utcnow(),
            # Was a required multipart form field (`ingested_by: str =
            # Form(...)`), written into Evidence.ingested_by and into the
            # FILE_UPLOADED audit entry. So the name recorded against an
            # upload - which is a chain-of-custody fact, not a label - was
            # a string typed into the request. It was removed from the
            # signature entirely rather than ignored: a required field
            # that decides nothing is a trap, and on the *chain of
            # custody* record the whole point is that it decides
            # something true.
            ingested_by=current_user.username,
            status="Uploaded",
            chunk_count=0,
            entity_count=0,
        )
        db.add(db_evidence)
        db.commit()
        db.refresh(db_evidence)

        # 6. Create AuditLog entry
        _create_audit(
            db=db,
            action_type="FILE_UPLOADED",
            performed_by=current_user.username,
            details={
                "filename": original_filename,
                "file_size": file_size_bytes,
                "sha256_hash": hash_value,
                "evidence_id": evidence_id,
            },
            case_id=case_id,
        )

        # 7. Removed background ingestion thread (now handled by queue)

        # 8. Return EvidenceResponse immediately
        return db_evidence

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to upload evidence",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/evidence/upload_multi
# ---------------------------------------------------------------------------

from typing import List

@router.post("/upload_multi", response_model=schemas.EvidenceResponse, status_code=201)
async def upload_multi_evidence(
    case_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """
    Upload several files at once.

    Split disk-image segments (.001, .002, ...) are concatenated into a
    single image, because a split set is one artefact and the pytsk3 walk
    needs it whole. Everything else is stored as its own evidence item.

    This endpoint used to concatenate unconditionally, so selecting three
    log files produced one .dd blob and handed it to the forensic walk - which
    cannot mount it, and reported the failure with nothing to show for three
    files that were each perfectly ingestable. It also stored the bare
    filename in Evidence.file_path instead of the full path, so the job
    worker could not open the file it was asked to ingest and the
    chain-of-custody check reported the evidence as missing.

    Returns the combined image when there is one, otherwise the first stored
    item, so the response shape is unchanged.
    """
    try:
        settings = get_settings()

        db_case = db.query(models.Case).filter(models.Case.id == case_id).first()
        if not db_case:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Case not found",
                    detail=f"No case with id={case_id}",
                ).model_dump(),
            )

        if not files:
            raise HTTPException(status_code=400, detail="No files provided")

        # Same gate as the single-file endpoint. Drag-and-drop bypasses the
        # input's accept filter, so the server is the only real check.
        for f in files:
            name = f.filename or "unknown"
            if not is_supported_upload(name):
                bad = normalize_extension(name)
                raise HTTPException(
                    status_code=400,
                    detail=schemas.ErrorResponse(
                        error="Invalid file type",
                        detail=(
                            f"Unsupported file type: {bad or 'none'} "
                            f"in {name}. Supported: "
                            f"{', '.join(sorted(ALLOWED_EXTENSIONS))}"
                        ),
                    ).model_dump(),
                )

        image_files = [f for f in files if is_forensic_image(f.filename or "")]
        plain_files = [f for f in files if f not in image_files]

        created = []

        # --- split disk image segments -> one combined image ---
        if image_files:
            # Sorted so .001, .002 ... reassemble in the right order.
            sorted_images = sorted(
                image_files, key=lambda f: f.filename or "")

            evidence_id = str(uuid.uuid4())
            base_name = sorted_images[0].filename or "unknown"
            name_no_ext, _ = os.path.splitext(base_name)
            final_filename = f"{name_no_ext}_combined.dd"

            safe_filename = f"{evidence_id}_{final_filename}"
            file_path = os.path.join(
                settings.cases_dir, case_id, "evidence", safe_filename
            )
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            file_size_bytes = 0
            sha256 = hashlib.sha256()

            # Stream chunks to avoid loading gigabytes into RAM
            async with aiofiles.open(file_path, "wb") as out_file:
                for f in sorted_images:
                    while True:
                        chunk = await f.read(1024 * 1024 * 4)  # 4MB chunks
                        if not chunk:
                            break
                        await out_file.write(chunk)
                        sha256.update(chunk)
                        file_size_bytes += len(chunk)

            combined = models.Evidence(
                id=evidence_id,
                case_id=case_id,
                filename=final_filename,
                original_filename=final_filename,
                file_type="dd",
                file_size_bytes=file_size_bytes,
                file_path=file_path,
                sha256_hash=sha256.hexdigest(),
                ingested_at=datetime.utcnow(),
                ingested_by=current_user.username,
                status="Uploaded",
                notes=(
                    f"Combined from {len(sorted_images)} split files"
                ),
            )
            db.add(combined)
            created.append(combined)

        # --- everything else -> one evidence item per file ---
        for f in plain_files:
            original_filename = f.filename or "unknown"
            ext = normalize_extension(original_filename)
            ev_id = str(uuid.uuid4())
            safe_name = f"{ev_id}_{original_filename}"
            path = os.path.join(
                settings.cases_dir, case_id, "evidence", safe_name
            )
            os.makedirs(os.path.dirname(path), exist_ok=True)

            size = 0
            digest = hashlib.sha256()
            async with aiofiles.open(path, "wb") as out_file:
                while True:
                    chunk = await f.read(4 * 1024 * 1024)
                    if not chunk:
                        break
                    await out_file.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)

            item = models.Evidence(
                id=ev_id,
                case_id=case_id,
                filename=safe_name,
                original_filename=original_filename,
                file_type=ext.lstrip("."),
                file_size_bytes=size,
                file_path=path,
                sha256_hash=digest.hexdigest(),
                ingested_at=datetime.utcnow(),
                ingested_by=current_user.username,
                status="Uploaded",
            )
            db.add(item)
            created.append(item)

        if not created:
            raise HTTPException(
                status_code=400, detail="No files provided")

        # Audit log
        db.add(models.AuditLog(
            id=str(uuid.uuid4()),
            case_id=case_id,
            action_type="EVIDENCE_UPLOADED",
            performed_by=current_user.username,
            details=json.dumps({
                "evidence_ids": [e.id for e in created],
                "filenames": [
                    e.original_filename for e in created],
                "files_received": len(files),
                "combined_image_segments": len(image_files),
                "total_size_bytes": sum(
                    e.file_size_bytes or 0 for e in created),
            })
        ))

        db.commit()
        for e in created:
            db.refresh(e)
        return created[0]

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to upload evidence",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/evidence/{evidence_id}/verify
# Chain-of-custody SHA-256 integrity check.
# Must be declared BEFORE /{evidence_id} routes.
# ---------------------------------------------------------------------------

@router.post("/{evidence_id}/verify")
def verify_evidence_integrity(
    case_id: str,
    evidence_id: str,
    current_user: models.User = Depends(require_investigator),
    db: Session = Depends(get_db),
):
    """
    Re-computes SHA-256 of stored file and compares to
    original hash recorded at upload time.
    Returns PASS or FAIL with full details.
    Logs result to audit trail for chain-of-custody.
    """
    import hashlib
    from datetime import datetime as _dt

    evidence = db.query(models.Evidence).filter(
        models.Evidence.id == evidence_id,
        models.Evidence.case_id == case_id,
    ).first()

    if not evidence:
        raise HTTPException(
            status_code=404,
            detail="Evidence not found")

    if not evidence.file_path or not os.path.exists(evidence.file_path):
        raise HTTPException(
            status_code=404,
            detail=(
                "Evidence file not found on disk. "
                "It may have been moved or deleted."
            ))

    if not evidence.sha256_hash:
        raise HTTPException(
            status_code=400,
            detail="No original hash stored. Cannot verify.")

    # Recompute SHA-256
    sha256 = hashlib.sha256()
    try:
        with open(evidence.file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        current_hash = sha256.hexdigest()
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Hash computation failed: {e}")

    passed = current_hash == evidence.sha256_hash
    result = "PASS" if passed else "FAIL"
    verified_at = str(_dt.utcnow())

    # Log to audit trail
    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type="INTEGRITY_VERIFIED",
        performed_by=current_user.username,
        details=json.dumps({
            "evidence_id": evidence_id,
            "filename": evidence.original_filename,
            "result": result,
            "original_hash": evidence.sha256_hash,
            "current_hash": current_hash,
            "verified_at": verified_at,
        })
    ))
    db.commit()

    return {
        "result": result,
        "passed": passed,
        "original_hash": evidence.sha256_hash,
        "current_hash": current_hash,
        "filename": evidence.original_filename,
        "verified_at": verified_at,
        "message": (
            "\u2705 Integrity verified \u2014 "
            "file matches original hash"
            if passed else
            "\U0001f6a8 INTEGRITY FAILURE \u2014 "
            "file has been modified since ingestion"
        ),
    }


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/artifacts/all
# Cross-evidence artifact browser with filtering.
# Must be declared BEFORE /{evidence_id} routes.
# ---------------------------------------------------------------------------

@router.get("/artifacts/all")
def get_all_case_artifacts(
    case_id: str,
    extension: str = None,
    extraction_type: str = None,
    is_flagged: bool = None,
    search: str = None,
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Returns paginated ForensicArtifact records for every
    evidence item in this case. Supports filtering by
    extension, extraction_type, is_flagged, and filename
    / path search.
    """
    case = db.query(models.Case).filter(
        models.Case.id == case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found")

    # Clamp to safe values
    page = max(1, page)
    page_size = max(1, min(page_size, 500))

    try:
        query = db.query(models.ForensicArtifact).filter(
            models.ForensicArtifact.case_id == case_id
        )

        if extension:
            query = query.filter(
                models.ForensicArtifact.file_extension == extension
            )
        if extraction_type:
            query = query.filter(
                models.ForensicArtifact.extraction_type == extraction_type
            )
        if is_flagged is not None:
            query = query.filter(
                models.ForensicArtifact.is_flagged == is_flagged
            )
        if search:
            query = query.filter(
                models.ForensicArtifact.internal_path.contains(search)
            )

        total = query.count()
        offset = (page - 1) * page_size
        artifacts = query.order_by(
            models.ForensicArtifact.modified_at.desc()
        ).offset(offset).limit(page_size).all()

        items = [
            {
                "id": a.id,
                "evidence_id": a.evidence_id,
                "internal_path": a.internal_path,
                "filename": a.filename,
                "file_extension": a.file_extension,
                "file_size_bytes": a.file_size_bytes,
                "sha256_hash": a.sha256_hash,
                "modified_at": a.modified_at,
                "accessed_at": a.accessed_at,
                "created_at_ts": a.created_at_ts,
                "born_at": a.born_at,
                "extraction_type": a.extraction_type,
                "is_flagged": a.is_flagged,
                "has_text": bool(a.extracted_text),
                "text_preview": (
                    a.extracted_text[:200]
                    if a.extracted_text
                    else None
                ),
                "is_viewable": a.is_viewable or False,
                "has_stored_file": bool(a.stored_file_path),
            }
            for a in artifacts
        ]

        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(
                1, (total + page_size - 1) // page_size),
            "has_next": page * page_size < total,
            "has_prev": page > 1,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/timeline
# ---------------------------------------------------------------------------

@router.get("/timeline")
def get_timeline(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Returns all artifacts with timestamps sorted
    chronologically by modified_at.
    Groups events by date for visualization.
    Flags days with >20 events as anomalies.
    """
    case = db.query(models.Case).filter(
        models.Case.id == case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found")

    try:
        artifacts = (
            db.query(models.ForensicArtifact)
            .filter(
                models.ForensicArtifact.case_id == case_id,
                models.ForensicArtifact.modified_at != "Unknown",
                models.ForensicArtifact.modified_at != None,
            )
            .order_by(models.ForensicArtifact.modified_at)
            .all()
        )

        from collections import defaultdict
        grouped = defaultdict(list)

        for a in artifacts:
            date_key = str(a.modified_at)[:10] if a.modified_at else "Unknown"
            grouped[date_key].append({
                "id": a.id,
                "filename": a.filename,
                "internal_path": a.internal_path,
                "file_extension": a.file_extension,
                "extraction_type": a.extraction_type,
                "file_size_bytes": a.file_size_bytes,
                "modified_at": a.modified_at,
                "accessed_at": a.accessed_at,
                "created_at_ts": a.created_at_ts,
                "born_at": a.born_at,
                "sha256_hash": a.sha256_hash,
                "is_flagged": a.is_flagged,
            })

        timeline = []
        for date in sorted(grouped.keys()):
            events = grouped[date]
            timeline.append({
                "date": date,
                "event_count": len(events),
                "events": events,
                "is_anomaly": len(events) > 20,
            })

        return {
            "total_events": len(artifacts),
            "date_range": {
                "first": timeline[0]["date"] if timeline else None,
                "last": timeline[-1]["date"] if timeline else None,
            },
            "timeline": timeline,
            "anomaly_count": sum(
                1 for t in timeline if t["is_anomaly"]
            ),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/anomalies
# ---------------------------------------------------------------------------

@router.get("/anomalies")
def get_anomalies(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """
    Returns all anomalous artifacts
    with their reasons and descriptions.
    """
    from backend.modules.anomaly_detector \
        import ANOMALY_DESCRIPTIONS

    case = db.query(models.Case).filter(
        models.Case.id == case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found")

    try:
        anomalies = db.query(
            models.ForensicArtifact
        ).filter(
            models.ForensicArtifact.case_id
                == case_id,
            models.ForensicArtifact.is_anomaly
                == True
        ).order_by(
            models.ForensicArtifact.modified_at
        ).all()

        total = db.query(
            models.ForensicArtifact
        ).filter(
            models.ForensicArtifact.case_id
                == case_id
        ).count()

        # Count by reason type
        from collections import defaultdict
        reason_counts = defaultdict(int)
        for a in anomalies:
            reasons = json.loads(
                a.anomaly_reasons or '[]')
            for r in reasons:
                reason_counts[r] += 1

        return {
            "total_artifacts": total,
            "anomaly_count": len(anomalies),
            "anomaly_rate": round(
                len(anomalies) / total * 100,
                1) if total > 0 else 0,
            "by_type": dict(reason_counts),
            "descriptions": 
                ANOMALY_DESCRIPTIONS,
            "anomalies": [{
                "id": a.id,
                "filename": a.filename,
                "internal_path": 
                    a.internal_path,
                "modified_at": a.modified_at,
                "born_at": a.born_at,
                "accessed_at": a.accessed_at,
                "reasons": json.loads(
                    a.anomaly_reasons 
                    or '[]'),
                "is_flagged": a.is_flagged,
                "sha256_hash": a.sha256_hash
            } for a in anomalies]
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e))


# ---------------------------------------------------------------------------
# PATCH /api/cases/{case_id}/evidence/artifacts/{artifact_id}/flag
# ---------------------------------------------------------------------------

@router.patch("/artifacts/{artifact_id}/flag")
def flag_artifact(
    case_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """Toggle the is_flagged field on a forensic artifact."""
    artifact = (
        db.query(models.ForensicArtifact)
        .filter(
            models.ForensicArtifact.id == artifact_id,
            models.ForensicArtifact.case_id == case_id,
        )
        .first()
    )
    if not artifact:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found")
    artifact.is_flagged = not artifact.is_flagged
    db.commit()
    return {"id": artifact_id, "is_flagged": artifact.is_flagged}


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/artifacts/{artifact_id}
# Full artifact detail including extracted_text.
# ---------------------------------------------------------------------------

@router.get("/artifacts/{artifact_id}")
def get_artifact(
    case_id: str,
    artifact_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Return a single artifact with its full extracted text."""
    artifact = (
        db.query(models.ForensicArtifact)
        .filter(
            models.ForensicArtifact.id == artifact_id,
            models.ForensicArtifact.case_id == case_id,
        )
        .first()
    )
    if not artifact:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found")
    return {
        "id": artifact.id,
        "evidence_id": artifact.evidence_id,
        "internal_path": artifact.internal_path,
        "filename": artifact.filename,
        "file_extension": artifact.file_extension,
        "file_size_bytes": artifact.file_size_bytes,
        "sha256_hash": artifact.sha256_hash,
        "modified_at": artifact.modified_at,
        "accessed_at": artifact.accessed_at,
        "created_at_ts": artifact.created_at_ts,
        "born_at": artifact.born_at,
        "extracted_text": artifact.extracted_text,
        "extraction_type": artifact.extraction_type,
        "is_flagged": artifact.is_flagged,
        "extracted_at": str(artifact.extracted_at),
        "stored_file_path": bool(artifact.stored_file_path),
        "stored_file_size": artifact.stored_file_size or 0,
        "is_viewable": artifact.is_viewable or False,
        "mime_type": get_mime_type(artifact.filename) if artifact.is_viewable else None,
    }


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/{evidence_id}/artifacts
# Per-evidence artifact list (pre-existing endpoint).
# ---------------------------------------------------------------------------

@router.get("/{evidence_id}/artifacts")
def list_artifacts(
    case_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Lists all forensic artifacts extracted from a
    disk image evidence item.
    Returns [] for document-type evidence.
    """
    try:
        db_evidence = (
            db.query(models.Evidence)
            .filter(
                models.Evidence.id == evidence_id,
                models.Evidence.case_id == case_id,
            )
            .first()
        )
        if not db_evidence:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Evidence not found",
                    detail=f"No evidence with id={evidence_id} in case {case_id}",
                ).model_dump(),
            )

        artifacts = (
            db.query(models.ForensicArtifact)
            .filter(
                models.ForensicArtifact.evidence_id == evidence_id
            )
            .all()
        )

        return [
            {
                "id": a.id,
                "internal_path": a.internal_path,
                "filename": a.filename,
                "file_extension": a.file_extension,
                "file_size_bytes": a.file_size_bytes,
                "sha256_hash": a.sha256_hash,
                "modified_at": a.modified_at,
                "accessed_at": a.accessed_at,
                "created_at_ts": a.created_at_ts,
                "born_at": a.born_at,
                "extraction_type": a.extraction_type,
                "is_flagged": a.is_flagged,
                "has_text": bool(a.extracted_text),
            }
            for a in artifacts
        ]
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve artifacts",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/{evidence_id}
# ---------------------------------------------------------------------------

@router.get("/{evidence_id}", response_model=schemas.EvidenceResponse)
def get_evidence(
    case_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Return a single evidence item."""
    try:
        db_evidence = (
            db.query(models.Evidence)
            .filter(
                models.Evidence.id == evidence_id,
                models.Evidence.case_id == case_id,
            )
            .first()
        )
        if not db_evidence:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Evidence not found",
                    detail=f"No evidence with id={evidence_id} in case {case_id}",
                ).model_dump(),
            )
        return db_evidence
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve evidence",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# DELETE /api/cases/{case_id}/evidence/{evidence_id}  — soft archive
# ---------------------------------------------------------------------------

@router.delete("/{evidence_id}", response_model=schemas.SuccessResponse)
def archive_evidence(
    case_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """
    Soft-archive evidence by setting status to 'Archived'.
    The file on disk is NOT deleted.

    The role gate was `require_admin`, which was both wrong and the reason a
    non-admin saw nothing happen: uploading evidence needs Investigator, and
    archiving the whole CASE needs Investigator, but archiving one item inside
    a case demanded Admin. The broader action was available to a lower role
    than the narrower one, so the gate could only have been a copy-paste.
    Reversible with POST .../restore.
    """
    try:
        db_evidence = (
            db.query(models.Evidence)
            .filter(
                models.Evidence.id == evidence_id,
                models.Evidence.case_id == case_id,
            )
            .first()
        )
        if not db_evidence:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Evidence not found",
                    detail=f"No evidence with id={evidence_id} in case {case_id}",
                ).model_dump(),
            )

        if db_evidence.status == "Archived":
            raise HTTPException(
                status_code=409,
                detail=schemas.ErrorResponse(
                    error="Already archived",
                    detail=(f"Evidence {evidence_id} is already archived. "
                            "Use restore to bring it back."),
                ).model_dump(),
            )

        # Refuse while an ingestion job is live. The worker holds the evidence
        # row and keeps writing chunks into the collection this call is about
        # to empty, so archiving mid-run would drop the item out of the case
        # and then write its vectors straight back into an index nobody is
        # shown any more. Refusing is the honest answer; the job will be
        # Queued or Failed in a moment and the archive will then work.
        live_job = (
            db.query(models.IngestionJob)
            .filter(
                models.IngestionJob.evidence_id == evidence_id,
                models.IngestionJob.status.in_(["Queued", "Running"]),
            )
            .first()
        )
        if live_job:
            raise HTTPException(
                status_code=409,
                detail=schemas.ErrorResponse(
                    error="Ingestion in progress",
                    detail=(f"Evidence {evidence_id} has a {live_job.status} "
                            "ingestion job. Stop the job first, then archive."),
                ).model_dump(),
            )

        # Qdrant cleanup — remove this evidence's vectors before archiving.
        #
        # This was wrapped in `except Exception: print(...)` and marked
        # non-fatal, which made the archive a lie in the one direction that
        # matters. The confirm dialog promises "AI queries will no longer
        # return its content". If this delete fails, the chunks are still in
        # the index, queries DO still return them, and the response says
        # "archived successfully" while the investigator is relying on the
        # opposite. An investigator who archives a document to keep it out of
        # an analysis, and then finds it in the answer, has been misled about
        # their own evidence.
        #
        # So a cleanup failure aborts the archive instead. Nothing is lost by
        # refusing: the status change below has not run, the file is untouched
        # on disk, and the item is still fully present and active. The
        # operator can retry, or stop whatever is holding the index.
        from backend.modules.vector_store import (
            get_client, get_collection_name, case_qdrant_path)
        from qdrant_client.models import (
            Filter as QFilter,
            FieldCondition, MatchValue)
        try:
            qdrant_path = case_qdrant_path(case_id)
            _client = get_client(qdrant_path)
            _collection = get_collection_name(case_id)
            _client.delete(
                collection_name=_collection,
                points_selector=QFilter(
                    must=[FieldCondition(
                        key="evidence_id",
                        match=MatchValue(value=evidence_id)
                    )]
                )
            )
            print(f"[CLEANUP] Removed Qdrant chunks for {evidence_id}")
        except Exception as _e:
            print(f"[CLEANUP] Qdrant cleanup FAILED for {evidence_id}: {_e}")
            raise HTTPException(
                status_code=500,
                detail=schemas.ErrorResponse(
                    error="Archive aborted — search index not cleaned",
                    detail=(
                        f"The vectors for {db_evidence.original_filename} could "
                        f"not be removed ({_e}), so its text would still be "
                        "returned by AI queries. The evidence has NOT been "
                        "archived and remains active and intact. Retry, or stop "
                        "any job using this case first."
                    ),
                ).model_dump(),
            )

        # Captured before it is zeroed below, so the audit trail records how
        # much was removed. The embedded client's delete() does not report how
        # many points its filter matched on this version, so this is the
        # pre-archive figure rather than a measured delete count — stated as
        # such rather than presented as something the delete confirmed.
        removed_chunks = db_evidence.chunk_count or 0

        db_evidence.status = "Archived"
        # Zeroed, and deliberately so.
        #
        # Making archive actually delete vectors is what created this problem:
        # from here on, chunk_count would count chunks that no longer exist.
        # Four consumers read it without checking status — the case export
        # (cases.py), the PDF report and its generator, and the queue's
        # evidence row — so a stale value means a report and an export that
        # over-count an archived case's index.
        #
        # The alternative was to keep the number as history and teach all four
        # readers that "Archived" means the figure is historical. A value that
        # is only correct in some states, read by code that does not know about
        # the others, is the §18 failure one layer down; the count of how many
        # chunks were removed is recorded in the audit entry below anyway.
        #
        # So the invariant is the simple one: chunk_count is the number of
        # vectors this evidence currently has in the search index. entity_count
        # is untouched because entities live in the database and archiving
        # never removed them — it is still true.
        db_evidence.chunk_count = 0
        db.commit()

        _create_audit(
            db=db,
            action_type="EVIDENCE_ARCHIVED",
            performed_by=current_user.username,
            details={
                "evidence_id": evidence_id,
                "filename": db_evidence.original_filename,
                # The pre-archive count, now zeroed on the row. See the note
                # above: the delete() result does not report how many points
                # its filter matched on this client version.
                "chunks_removed": removed_chunks,
            },
            case_id=case_id,
        )

        return schemas.SuccessResponse(
            message=f"Evidence {evidence_id} archived successfully."
        )
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to archive evidence",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/evidence/{evidence_id}/restore  — undo an archive
# ---------------------------------------------------------------------------

@router.post("/{evidence_id}/restore", response_model=schemas.SuccessResponse)
def restore_evidence(
    case_id: str,
    evidence_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """
    Bring an archived evidence item back into the active investigation.

    Archiving was one-way: it set a status, removed the item from the case
    view, and there was no route back. A mis-click was therefore permanent and
    invisible at the same time -- the worst combination for evidence, where
    the record of what was examined is itself the product. Restore is added
    because an operation that cannot be undone should not be one click away.

    The restored status is 'Uploaded', NOT the status it had before. This is
    deliberate and it is the only honest option:

      * archiving DELETED this evidence's vectors from Qdrant, so it is no
        longer indexed, and saying otherwise would be the §15/B14 failure --
        a row that looks searchable and returns nothing
      * 'Uploaded' is exactly the state of a file that is on disk and not yet
        ingested, and it is the state the normal Queue button already
        understands, so re-indexing is the ordinary path rather than a
        special case

    chunk_count is cleared for the same reason: it counted vectors that no
    longer exist. entity_count is KEPT, because entities live in the database
    and archiving never removed them -- clearing a true number to look tidy is
    the same defect in the opposite direction.
    """
    try:
        db_evidence = (
            db.query(models.Evidence)
            .filter(
                models.Evidence.id == evidence_id,
                models.Evidence.case_id == case_id,
            )
            .first()
        )
        if not db_evidence:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Evidence not found",
                    detail=f"No evidence with id={evidence_id} in case {case_id}",
                ).model_dump(),
            )
        if db_evidence.status != "Archived":
            raise HTTPException(
                status_code=409,
                detail=schemas.ErrorResponse(
                    error="Not archived",
                    detail=(f"Evidence {evidence_id} is already active "
                            f"(status={db_evidence.status})."),
                ).model_dump(),
            )

        live_job = (
            db.query(models.IngestionJob)
            .filter(
                models.IngestionJob.evidence_id == evidence_id,
                models.IngestionJob.status.in_(["Queued", "Running"]),
            )
            .first()
        )
        if live_job:
            raise HTTPException(
                status_code=409,
                detail=schemas.ErrorResponse(
                    error="Ingestion in progress",
                    detail=f"Evidence {evidence_id} has a {live_job.status} job.",
                ).model_dump(),
            )

        was = db_evidence.status
        db_evidence.status = "Uploaded"
        # Defensive, not corrective: archive_evidence already zeroed this, so
        # for any row archived by this code the value is already 0. It is
        # repeated because a row archived by an EARLIER version of the endpoint
        # still carries its old count, and a restored item that claims chunks
        # it does not have is the searchable-as-empty failure from §15/B14.
        db_evidence.chunk_count = 0
        db_evidence.ingestion_job_id = None  # the old job is not this item's
        db_evidence.error_message = None
        # entity_count intentionally untouched - see the docstring.
        db.commit()

        _create_audit(
            db=db,
            action_type="EVIDENCE_RESTORED",
            performed_by=current_user.username,
            details={
                "evidence_id": evidence_id,
                "filename": db_evidence.original_filename,
                "previous_status": was,
            },
            case_id=case_id,
        )

        return schemas.SuccessResponse(
            message=(
                f"Evidence {evidence_id} restored. Its search index was "
                "removed when it was archived, so it is now 'Uploaded' — "
                "queue it again to re-index it."
            )
        )
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to restore evidence",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/artifacts/{artifact_id}/view
# Serves stored file for inline browser viewing.
# ---------------------------------------------------------------------------

@router.get("/artifacts/{artifact_id}/view")
def view_artifact_file(
    case_id: str,
    artifact_id: str,
    token: str = None,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Serves the stored file content for
    viewing in the browser.
    Streams with correct MIME type.
    Accepts token as query param for
    img/audio/video src= usage.
    """
    # If no Bearer token was injected by oauth2_scheme,
    # fall back to ?token= query param
    if current_user is None and token:
        from jose import jwt, JWTError
        from backend.auth import SECRET_KEY, ALGORITHM
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                current_user = db.query(models.User).filter(
                    models.User.id == user_id
                ).first()
        except JWTError:
            raise HTTPException(status_code=401, detail="Invalid token")
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")

    artifact = db.query(
        models.ForensicArtifact
    ).filter(
        models.ForensicArtifact.id == artifact_id,
        models.ForensicArtifact.case_id == case_id
    ).first()

    if not artifact:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found")

    if not artifact.stored_file_path:
        raise HTTPException(
            status_code=404,
            detail=(
                "File content was not saved during ingestion. "
                "Re-ingest to save files."
            ))

    if not os.path.exists(artifact.stored_file_path):
        raise HTTPException(
            status_code=404,
            detail="File no longer exists on disk.")

    # Security check: ensure path is within the case evidence directory
    settings = get_settings()
    allowed_base = os.path.abspath(
        os.path.join(settings.cases_dir, case_id))
    real_path = os.path.abspath(artifact.stored_file_path)

    if not real_path.startswith(allowed_base):
        raise HTTPException(
            status_code=403,
            detail="Path traversal denied")

    mime = get_mime_type(artifact.filename)

    # Log audit event
    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type="FILE_VIEWED",
        performed_by=current_user.username,
        details=json.dumps({
            "artifact_id": artifact_id,
            "filename": artifact.filename,
            "internal_path": artifact.internal_path
        })
    ))
    db.commit()

    return FileResponse(
        path=artifact.stored_file_path,
        media_type=mime,
        filename=artifact.filename,
        headers={
            "Content-Disposition":
                f'inline; filename="{artifact.filename}"'
        }
    )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/artifacts/{artifact_id}/download
# Forces download of stored file.
# ---------------------------------------------------------------------------

@router.get("/artifacts/{artifact_id}/download")
def download_artifact_file(
    case_id: str,
    artifact_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Forces download of stored file."""
    artifact = db.query(
        models.ForensicArtifact
    ).filter(
        models.ForensicArtifact.id == artifact_id,
        models.ForensicArtifact.case_id == case_id
    ).first()

    if not artifact:
        raise HTTPException(
            status_code=404,
            detail="Artifact not found")

    if (not artifact.stored_file_path or
            not os.path.exists(artifact.stored_file_path)):
        raise HTTPException(
            status_code=404,
            detail="File not on disk")

    settings = get_settings()
    allowed_base = os.path.abspath(
        os.path.join(settings.cases_dir, case_id))
    real_path = os.path.abspath(artifact.stored_file_path)

    if not real_path.startswith(allowed_base):
        raise HTTPException(
            status_code=403,
            detail="Path traversal denied")

    return FileResponse(
        path=artifact.stored_file_path,
        media_type='application/octet-stream',
        filename=artifact.filename,
        headers={
            "Content-Disposition":
                f'attachment; filename="{artifact.filename}"'
        }
    )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/evidence/storage-stats
# Returns total disk usage for extracted files in this case.
# ---------------------------------------------------------------------------

@router.get("/storage-stats")
def get_storage_stats(
    case_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Returns total storage used by
    extracted files for this case.
    """
    settings = get_settings()
    extracted_dir = os.path.join(
        settings.cases_dir,
        case_id,
        "evidence"
    )
    stats = get_case_storage_stats(extracted_dir)

    # Count viewable artifacts
    viewable = db.query(
        models.ForensicArtifact
    ).filter(
        models.ForensicArtifact.case_id == case_id,
        models.ForensicArtifact.is_viewable == True,
        models.ForensicArtifact.stored_file_path != None
    ).count()

    return {
        **stats,
        "viewable_files": viewable,
        "case_id": case_id
    }


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/artifacts/compare
# Returns both artifacts' full data for side-by-side comparison,
# plus word-level diff statistics.
# ---------------------------------------------------------------------------

from pydantic import BaseModel as _BM


class CompareRequest(_BM):
    artifact_id_1: str
    artifact_id_2: str


@router.post("/artifacts/compare")
def compare_artifacts(
    case_id: str,
    body: CompareRequest,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Fetches both artifacts and returns their full data for the
    side-by-side comparison UI, including a word-level diff summary.
    """
    a1 = db.query(models.ForensicArtifact).filter(
        models.ForensicArtifact.id == body.artifact_id_1,
        models.ForensicArtifact.case_id == case_id,
    ).first()

    a2 = db.query(models.ForensicArtifact).filter(
        models.ForensicArtifact.id == body.artifact_id_2,
        models.ForensicArtifact.case_id == case_id,
    ).first()

    if not a1 or not a2:
        raise HTTPException(
            status_code=404,
            detail="One or both artifacts not found in this case",
        )

    def _to_dict(a: models.ForensicArtifact) -> dict:
        return {
            "id":               a.id,
            "filename":         a.filename,
            "internal_path":    a.internal_path,
            "file_extension":   a.file_extension,
            "file_size_bytes":  a.file_size_bytes,
            "sha256_hash":      a.sha256_hash,
            "modified_at":      str(a.modified_at)    if a.modified_at    else None,
            "accessed_at":      str(a.accessed_at)    if a.accessed_at    else None,
            "created_at_ts":    str(a.created_at_ts)  if a.created_at_ts  else None,
            "born_at":          str(a.born_at)         if a.born_at         else None,
            "extracted_text":   a.extracted_text,
            "extraction_type":  a.extraction_type,
            "shannon_entropy":  a.shannon_entropy,
            "is_anomaly":       a.is_anomaly,
            "is_flagged":       a.is_flagged,
            "has_stored_file":  bool(a.stored_file_path),
            "is_viewable":      a.is_viewable,
        }

    def _diff_stats(t1: str, t2: str) -> dict | None:
        if not t1 or not t2:
            return None
        words1 = set(t1.lower().split())
        words2 = set(t2.lower().split())
        common     = words1 & words2
        only_in_1  = words1 - words2
        only_in_2  = words2 - words1
        union_size = max(len(words1 | words2), 1)
        return {
            "common_words":    len(common),
            "unique_to_first": len(only_in_1),
            "unique_to_second":len(only_in_2),
            "similarity_pct":  round(len(common) / union_size * 100, 1),
        }

    return {
        "artifact_1":  _to_dict(a1),
        "artifact_2":  _to_dict(a2),
        "diff_stats":  _diff_stats(
            a1.extracted_text,
            a2.extracted_text,
        ),
    }

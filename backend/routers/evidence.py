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

router = APIRouter(
    prefix="/api/cases/{case_id}/evidence",
    tags=["Evidence"],
)

ALLOWED_EXTENSIONS = {
    # Documents
    '.pdf', '.txt',
    # Office
    '.docx', '.doc',
    '.xlsx', '.xls',
    '.pptx', '.ppt',
    # Forensic disk images
    '.e01', '.001', '.dd',
    '.raw', '.img',
    # Audio
    '.mp3', '.wav', '.m4a',
    '.flac', '.ogg', '.aac',
    # Video
    '.mp4', '.avi', '.mov',
    '.mkv', '.wmv',
    # Email
    '.eml', '.msg',
    # Images (OCR)
    '.jpg', '.jpeg', '.png',
    '.tiff', '.bmp'
}


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
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Return all evidence items for a case."""
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

        evidence_list = (
            db.query(models.Evidence)
            .filter(models.Evidence.case_id == case_id)
            .all()
        )
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
    ingested_by: str = Form(...),
    file: UploadFile = File(...),
    include_deleted: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """
    Upload a .pdf or .txt file as evidence for a case.
    Saves to disk, computes SHA-256, records in DB, writes audit log,
    then launches background ingestion thread.
    For forensic disk images, include_deleted=True will attempt
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
        _, ext = os.path.splitext(original_filename.lower())
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=schemas.ErrorResponse(
                    error="Invalid file type",
                    detail=(
                        f"Unsupported file type: {ext}. "
                        f"Supported: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
                    ),
                ).model_dump(),
            )

        # 3. Generate evidence ID
        evidence_id = str(uuid.uuid4())

        # 4. Save file to disk using aiofiles
        safe_filename = f"{evidence_id}_{original_filename}"
        file_path = os.path.join(
            settings.cases_dir, case_id, "evidence", safe_filename
        )
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        content = await file.read()
        async with aiofiles.open(file_path, "wb") as out_file:
            await out_file.write(content)

        file_size_bytes = len(content)

        # 5. Compute SHA-256 hash
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                sha256.update(chunk)
        hash_value = sha256.hexdigest()

        # Determine file_type from extension
        file_type = ext.lstrip(".")

        # 6. Create Evidence record in DB with status "Uploaded"
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
            ingested_by=ingested_by,
            status="Uploaded",
            chunk_count=0,
            entity_count=0,
        )
        db.add(db_evidence)
        db.commit()
        db.refresh(db_evidence)

        # 7. Create AuditLog entry
        _create_audit(
            db=db,
            action_type="FILE_UPLOADED",
            performed_by=ingested_by,
            details={
                "filename": original_filename,
                "file_size": file_size_bytes,
                "sha256_hash": hash_value,
                "evidence_id": evidence_id,
            },
            case_id=case_id,
        )

        # 8. Removed background ingestion thread (now handled by queue)

        # 9. Return EvidenceResponse immediately
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
    current_user: models.User = Depends(require_admin),
):
    """
    Soft-archive evidence by setting status to 'Archived'.
    The file on disk is NOT deleted.
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

        # Qdrant cleanup — remove this evidence's vectors before archiving
        try:
            from backend.modules.vector_store import (
                get_client, get_collection_name, case_qdrant_path)
            from backend.dependencies import get_settings as _get_settings
            from qdrant_client.models import (
                Filter as QFilter,
                FieldCondition, MatchValue)
            _settings = _get_settings()
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
            print(f"[CLEANUP] Qdrant cleanup error (non-fatal): {_e}")

        db_evidence.status = "Archived"
        db.commit()

        _create_audit(
            db=db,
            action_type="EVIDENCE_ARCHIVED",
            performed_by="system",
            details={
                "evidence_id": evidence_id,
                "filename": db_evidence.original_filename,
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

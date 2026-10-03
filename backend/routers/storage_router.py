"""
Storage management router — system-wide and per-case storage transparency.

Provides:
  * System overview: total/used/free across all volumes, cases directory usage
  * Per-case breakdown: evidence files, extracted files, Qdrant index, artifacts
  * Detailed file inventory: all ingested files with sizes, status, paths
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from sqlalchemy.orm import Session
from backend.database import get_db
from backend import models
from backend.dependencies import get_settings
from backend.auth import (
    get_current_user,
    require_viewer,
    require_analyst,
    require_admin
)
from backend.modules.file_store import get_case_storage_stats, resolve_qdrant_dir
from backend.modules.index_provenance import survey as provenance_survey
import os
import psutil
from datetime import datetime


router = APIRouter(
    prefix="/api/storage",
    tags=["Storage"],
)


def _human_bytes(n: int) -> str:
    """Format bytes as human-readable string."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
        n /= 1024


def _get_cases_dir() -> str:
    settings = get_settings()
    return settings.cases_dir


def _get_case_dir(case_id: str) -> str:
    return os.path.join(_get_cases_dir(), case_id)


def _get_evidence_dir(case_id: str) -> str:
    return os.path.join(_get_case_dir(case_id), "evidence")


def _get_qdrant_dir(case_id: str) -> str:
    """Get Qdrant dir for a case, accounting for relocation."""
    # Use the same resolution logic as vector_store.get_client
    base = resolve_qdrant_dir()
    return os.path.join(base, case_id, "qdrant")


def _walk_size(path: str) -> tuple[int, int]:
    """Return (total_bytes, file_count) for a directory tree."""
    total = 0
    count = 0
    if not os.path.isdir(path):
        return 0, 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                fp = os.path.join(root, f)
                total += os.path.getsize(fp)
                count += 1
            except OSError:
                pass
    return total, count


@router.get("/system-overview")
def get_system_storage_overview(
    current_user: models.User = Depends(get_current_user),
):
    """
    System-wide storage overview.

    Returns:
      - volumes: all mounted volumes with total/used/free
      - cases_root: total size of cases directory
      - cases_count: number of case directories
      - qdrant_root: total size of Qdrant storage (if relocated)
      - totals: aggregate across everything
    """
    settings = get_settings()
    cases_root = settings.cases_dir

    # Volume info (reuse hardware probe logic)
    volumes = []
    for part in psutil.disk_partitions(all=True):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            volumes.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "total_human": _human_bytes(usage.total),
                "used_human": _human_bytes(usage.used),
                "free_human": _human_bytes(usage.free),
                "pct_used": round(usage.used / usage.total * 100, 1) if usage.total else 0,
            })
        except (PermissionError, OSError):
            # Skip inaccessible mounts
            continue

    # Cases directory total
    cases_root_bytes, cases_root_files = _walk_size(cases_root)

    # Qdrant root (may be different from cases_root if relocated)
    qdrant_root = os.path.dirname(resolve_qdrant_dir()) if os.path.exists(resolve_qdrant_dir()) else None
    qdrant_root_bytes, qdrant_root_files = (0, 0)
    if qdrant_root and qdrant_root != cases_root and os.path.isdir(qdrant_root):
        qdrant_root_bytes, qdrant_root_files = _walk_size(qdrant_root)

    return {
        "volumes": volumes,
        "cases_root": {
            "path": cases_root,
            "total_bytes": cases_root_bytes,
            "total_human": _human_bytes(cases_root_bytes),
            "file_count": cases_root_files,
        },
        "qdrant_root": {
            "path": qdrant_root,
            "total_bytes": qdrant_root_bytes,
            "total_human": _human_bytes(qdrant_root_bytes),
            "file_count": qdrant_root_files,
            "relocated": qdrant_root is not None and qdrant_root != cases_root,
        } if qdrant_root else None,
        "summary": {
            "total_cases_bytes": cases_root_bytes + qdrant_root_bytes,
            "total_cases_human": _human_bytes(cases_root_bytes + qdrant_root_bytes),
            "total_cases_files": cases_root_files + qdrant_root_files,
        },
    }


@router.get("/case/{case_id}/breakdown")
def get_case_storage_breakdown(
    case_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Detailed per-case storage breakdown.

    Returns:
      - evidence_files: original uploaded files
      - extracted_files: files extracted from disk images/archives
      - qdrant_index: vector store size
      - artifacts: viewable extracted artifacts
      - total: aggregate
    """
    # Verify case exists and user has access
    case = db.query(models.Case).filter(models.Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    settings = get_settings()
    case_dir = _get_case_dir(case_id)
    evidence_dir = _get_evidence_dir(case_id)
    qdrant_dir = _get_qdrant_dir(case_id)

    # Evidence files (original uploads)
    evidence_files = []
    evidence_total = 0
    evidence_count = 0
    for ev in db.query(models.Evidence).filter(models.Evidence.case_id == case_id).all():
        if ev.file_path and os.path.exists(ev.file_path):
            sz = ev.file_size_bytes or os.path.getsize(ev.file_path)
        else:
            sz = ev.file_size_bytes or 0
        evidence_total += sz
        evidence_count += 1
        evidence_files.append({
            "id": ev.id,
            "filename": ev.filename,
            "original_filename": ev.original_filename,
            "status": ev.status,
            "file_type": ev.file_type,
            "size_bytes": sz,
            "size_human": _human_bytes(sz),
            "path": ev.file_path,
            "ingested_at": ev.ingested_at.isoformat() if ev.ingested_at else None,
        })

    # Extracted files (forensic artifacts from disk images)
    extracted_dir = os.path.join(evidence_dir, "extracted")
    extracted_total, extracted_count = _walk_size(extracted_dir)

    # Qdrant index
    qdrant_total, qdrant_count = _walk_size(qdrant_dir)

    # Artifacts (viewable extracted files)
    artifacts = []
    artifact_total = 0
    artifact_count = 0
    for art in db.query(models.ForensicArtifact).filter(
        models.ForensicArtifact.case_id == case_id,
        models.ForensicArtifact.stored_file_path != None
    ).all():
        if art.stored_file_path and os.path.exists(art.stored_file_path):
            sz = art.stored_file_size or os.path.getsize(art.stored_file_path)
        else:
            sz = art.stored_file_size or 0
        artifact_total += sz
        artifact_count += 1
        artifacts.append({
            "id": art.id,
            "internal_path": art.internal_path,
            "extraction_type": art.extraction_type,
            "size_bytes": sz,
            "size_human": _human_bytes(sz),
            "is_viewable": art.is_viewable,
            "is_deleted": art.is_deleted,
        })

    # Provenance info for Qdrant
    prov = provenance_survey(cases_root) if callable(provenance_survey) else {}

    return {
        "case_id": case_id,
        "case_name": case.name,
        "evidence_files": {
            "items": evidence_files,
            "total_bytes": evidence_total,
            "total_human": _human_bytes(evidence_total),
            "count": evidence_count,
        },
        "extracted_files": {
            "path": extracted_dir,
            "total_bytes": extracted_total,
            "total_human": _human_bytes(extracted_total),
            "count": extracted_count,
        },
        "qdrant_index": {
            "path": qdrant_dir,
            "total_bytes": qdrant_total,
            "total_human": _human_bytes(qdrant_total),
            "count": qdrant_count,
            "provenance": prov.get("cases", {}).get(case_id, {}),
        },
        "artifacts": {
            "items": artifacts,
            "total_bytes": artifact_total,
            "total_human": _human_bytes(artifact_total),
            "count": artifact_count,
        },
        "total": {
            "total_bytes": evidence_total + extracted_total + qdrant_total + artifact_total,
            "total_human": _human_bytes(evidence_total + extracted_total + qdrant_total + artifact_total),
        },
    }


@router.get("/case/{case_id}/files")
def list_case_files(
    case_id: str,
    include_archived: bool = Query(False),
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Complete file inventory for a case — every ingested file with full details.

    Returns flat list of all files: evidence, artifacts, extracted.
    """
    case = db.query(models.Case).filter(models.Case.id == case_id).first()
    if not case:
        raise HTTPException(404, "Case not found")

    files = []

    # Evidence files
    query = db.query(models.Evidence).filter(models.Evidence.case_id == case_id)
    if not include_archived:
        query = query.filter(models.Evidence.status != "Archived")
    for ev in query.all():
        sz = ev.file_size_bytes or 0
        if ev.file_path and os.path.exists(ev.file_path):
            sz = os.path.getsize(ev.file_path)
        files.append({
            "id": ev.id,
            "type": "evidence",
            "name": ev.original_filename or ev.filename,
            "status": ev.status,
            "file_type": ev.file_type,
            "size_bytes": sz,
            "size_human": _human_bytes(sz),
            "path": ev.file_path,
            "sha256": ev.sha256_hash,
            "ingested_at": ev.ingested_at.isoformat() if ev.ingested_at else None,
            "uploaded_by": ev.ingested_by,
        })

    # Forensic artifacts
    art_query = db.query(models.ForensicArtifact).filter(
        models.ForensicArtifact.case_id == case_id
    )
    for art in art_query.all():
        sz = art.stored_file_size or 0
        if art.stored_file_path and os.path.exists(art.stored_file_path):
            sz = os.path.getsize(art.stored_file_path)
        files.append({
            "id": art.id,
            "type": "artifact",
            "name": art.internal_path or f"artifact-{art.id[:8]}",
            "status": "extracted",
            "extraction_type": art.extraction_type,
            "size_bytes": sz,
            "size_human": _human_bytes(sz),
            "path": art.stored_file_path,
            "is_viewable": art.is_viewable,
            "is_deleted": art.is_deleted,
            "evidence_id": art.evidence_id,
        })

    # Sort by size descending
    files.sort(key=lambda x: x["size_bytes"], reverse=True)

    return {
        "case_id": case_id,
        "total_files": len(files),
        "total_bytes": sum(f["size_bytes"] for f in files),
        "total_human": _human_bytes(sum(f["size_bytes"] for f in files)),
        "files": files,
    }


@router.get("/case/{case_id}/evidence/{evidence_id}/details")
def get_evidence_storage_details(
    case_id: str,
    evidence_id: str,
    current_user: models.User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Storage details for a single evidence item and its artifacts."""
    ev = db.query(models.Evidence).filter(
        models.Evidence.id == evidence_id,
        models.Evidence.case_id == case_id
    ).first()
    if not ev:
        raise HTTPException(404, "Evidence not found")

    # Evidence file
    ev_sz = ev.file_size_bytes or 0
    if ev.file_path and os.path.exists(ev.file_path):
        ev_sz = os.path.getsize(ev.file_path)

    # Artifacts from this evidence
    artifacts = []
    art_total = 0
    for art in db.query(models.ForensicArtifact).filter(
        models.ForensicArtifact.evidence_id == evidence_id
    ).all():
        sz = art.stored_file_size or 0
        if art.stored_file_path and os.path.exists(art.stored_file_path):
            sz = os.path.getsize(art.stored_file_path)
        art_total += sz
        artifacts.append({
            "id": art.id,
            "internal_path": art.internal_path,
            "extraction_type": art.extraction_type,
            "size_bytes": sz,
            "size_human": _human_bytes(sz),
            "is_viewable": art.is_viewable,
            "is_deleted": art.is_deleted,
        })

    return {
        "evidence": {
            "id": ev.id,
            "filename": ev.filename,
            "original_filename": ev.original_filename,
            "status": ev.status,
            "file_type": ev.file_type,
            "size_bytes": ev_sz,
            "size_human": _human_bytes(ev_sz),
            "path": ev.file_path,
            "sha256": ev.sha256_hash,
            "ingested_at": ev.ingested_at.isoformat() if ev.ingested_at else None,
        },
        "artifacts": {
            "items": artifacts,
            "total_bytes": art_total,
            "total_human": _human_bytes(art_total),
            "count": len(artifacts),
        },
        "total_bytes": ev_sz + art_total,
        "total_human": _human_bytes(ev_sz + art_total),
    }
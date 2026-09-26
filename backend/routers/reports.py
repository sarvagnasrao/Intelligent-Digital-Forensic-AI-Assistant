from fastapi import (
    APIRouter, Depends, HTTPException,
    BackgroundTasks)
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from backend.database import get_db
from backend import models, schemas
from backend.dependencies import get_settings
from backend.modules.report_generator import (
    generate_report)
from backend.auth import (
    get_current_user,
    require_viewer,
    require_analyst,
    require_investigator,
    require_admin
)
import uuid, json, os, hashlib
from datetime import datetime

router = APIRouter(
    prefix="/api/cases/{case_id}/reports",
    tags=["Reports"]
)

settings = get_settings()

def _compute_sha256(path: str) -> str:
    sha256 = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(
            lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()

def _run_report_generation(
        report_id: str,
        case_id: str,
        report_type: str,
        generated_by: str,
        query_ids: list):
    """
    Background task that builds the PDF
    and updates the Report record.
    """
    from backend.database import SessionLocal
    db = SessionLocal()
    try:
        report = db.query(
            models.Report
        ).filter(
            models.Report.id == report_id
        ).first()
        if not report:
            return

        # Gather all data
        case = db.query(models.Case).filter(
            models.Case.id == case_id
        ).first()

        evidence = db.query(
            models.Evidence
        ).filter(
            models.Evidence.case_id == case_id
        ).all()

        entities = db.query(
            models.Entity
        ).filter(
            models.Entity.case_id == case_id
        ).order_by(
            models.Entity.frequency.desc()
        ).limit(100).all()

        if query_ids:
            queries = db.query(
                models.QueryLog
            ).filter(
                models.QueryLog.id.in_(
                    query_ids)
            ).all()
        else:
            queries = db.query(
                models.QueryLog
            ).filter(
                models.QueryLog.case_id 
                    == case_id
            ).order_by(
                models.QueryLog.asked_at
            ).all()

        artifacts = db.query(
            models.ForensicArtifact
        ).filter(
            models.ForensicArtifact.case_id 
                == case_id
        ).order_by(
            models.ForensicArtifact.modified_at
        ).limit(500).all()

        # Build timeline data structure
        from collections import defaultdict
        grouped = defaultdict(list)
        for a in artifacts:
            if (a.modified_at and
                a.modified_at != "Unknown"):
                date_key = str(
                    a.modified_at)[:10]
                grouped[date_key].append({
                    "filename": a.filename,
                    "internal_path": 
                        a.internal_path,
                    "extraction_type": 
                        a.extraction_type,
                    "file_size_bytes": 
                        a.file_size_bytes,
                    "modified_at": 
                        a.modified_at,
                    "is_flagged": a.is_flagged
                })

        timeline_data = None
        if grouped:
            timeline_list = []
            for date in sorted(
                grouped.keys()):
                events = grouped[date]
                timeline_list.append({
                    "date": date,
                    "event_count": 
                        len(events),
                    "events": events,
                    "is_anomaly": 
                        len(events) > 20
                })
            timeline_data = {
                "total_events": 
                    len(artifacts),
                "timeline": timeline_list,
                "date_range": {
                    "first": 
                        timeline_list[0][
                            "date"]
                        if timeline_list 
                        else None,
                    "last": 
                        timeline_list[-1][
                            "date"]
                        if timeline_list 
                        else None
                },
                "anomaly_count": sum(
                    1 for t in timeline_list
                    if t["is_anomaly"])
            }

        # Serialize to dicts
        case_dict = {
            "id": case.id,
            "case_name": case.case_name,
            "case_number": case.case_number,
            "status": case.status,
            "priority": case.priority,
            "created_by": case.created_by,
            "created_at": str(case.created_at)
        }
        evidence_list = [{
            "original_filename": 
                e.original_filename,
            "filename": e.filename,
            "status": e.status,
            "chunk_count": e.chunk_count,
            "entity_count": e.entity_count,
            "sha256_hash": e.sha256_hash
        } for e in evidence]

        entity_list = [{
            "name": e.name,
            "entity_type": e.entity_type,
            "frequency": e.frequency,
            "is_flagged": e.is_flagged,
            "notes": e.notes
        } for e in entities]

        query_list = [{
            "question_text": 
                q.question_text,
            "processed_response": 
                q.processed_response,
            "asked_by": q.asked_by,
            "asked_at": str(q.asked_at),
            "model_used": q.model_used,
            "response_time_ms": 
                q.response_time_ms,
            "cited_sentence_count": 
                q.cited_sentence_count,
            "is_flagged": q.is_flagged
        } for q in queries]

        artifact_list = [{
            "internal_path": 
                a.internal_path,
            "sha256_hash": a.sha256_hash,
            "is_flagged": a.is_flagged
        } for a in artifacts]

        # Generate PDF
        output_path = os.path.join(
            settings.cases_dir,
            case_id, "reports",
            f"{report_id}.pdf"
        )
        os.makedirs(
            os.path.dirname(output_path),
            exist_ok=True
        )

        page_count = generate_report(
            output_path=output_path,
            report_type=report_type,
            case_data=case_dict,
            generated_by=generated_by,
            evidence_list=evidence_list,
            entities=entity_list,
            queries=query_list,
            artifacts=artifact_list,
            timeline_data=timeline_data
        )

        # Update report record
        report.file_path = output_path
        report.sha256_hash = _compute_sha256(
            output_path)
        report.page_count = page_count or 1
        report.status = "Complete"
        report.query_ids_included = (
            json.dumps(query_ids))
        db.commit()

        # Audit log
        db.add(models.AuditLog(
            id=str(uuid.uuid4()),
            case_id=case_id,
            action_type="REPORT_GENERATED",
            performed_by=generated_by,
            details=json.dumps({
                "report_type": report_type,
                "pages": page_count,
                "report_id": report_id
            })
        ))
        db.commit()

        print(f"[REPORT] Generated: "
              f"{report_type} — "
              f"{page_count} pages")

    except Exception as e:
        print(f"[REPORT] FAILED: {e}")
        import traceback
        traceback.print_exc()
        try:
            report = db.query(
                models.Report
            ).filter(
                models.Report.id == report_id
            ).first()
            if report:
                report.status = "Failed"
                db.commit()
        except:
            pass
    finally:
        db.close()

@router.get("")
def list_reports(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Lists all reports for a case."""
    case = db.query(models.Case).filter(
        models.Case.id == case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found")

    reports = db.query(
        models.Report
    ).filter(
        models.Report.case_id == case_id
    ).order_by(
        models.Report.generated_at.desc()
    ).all()

    return [{
        "id": r.id,
        "report_type": r.report_type,
        "generated_by": r.generated_by,
        "generated_at": str(r.generated_at),
        "status": r.status,
        "page_count": r.page_count,
        "sha256_hash": r.sha256_hash,
        "file_exists": (
            os.path.exists(r.file_path)
            if r.file_path else False)
    } for r in reports]

@router.post("", status_code=201)
def create_report(
    case_id: str,
    body: schemas.ReportCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """
    Creates a report record and kicks off
    PDF generation as a background task.
    """
    case = db.query(models.Case).filter(
        models.Case.id == case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found")

    report_id = str(uuid.uuid4())
    report = models.Report(
        id=report_id,
        case_id=case_id,
        generated_by=body.generated_by,
        report_type=body.report_type,
        status="Generating",
        query_ids_included=json.dumps(
            body.query_ids_included)
    )
    db.add(report)
    db.commit()

    background_tasks.add_task(
        _run_report_generation,
        report_id=report_id,
        case_id=case_id,
        report_type=body.report_type,
        generated_by=body.generated_by,
        query_ids=body.query_ids_included
    )

    return {
        "id": report_id,
        "status": "Generating",
        "message": "Report generation started"
    }

@router.get("/{report_id}/download")
def download_report(
    case_id: str,
    report_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Streams the PDF for download."""
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.case_id == case_id
    ).first()
    if not report:
        raise HTTPException(
            status_code=404,
            detail="Report not found")
    if report.status != "Complete":
        raise HTTPException(
            status_code=400,
            detail=f"Report status: "
                   f"{report.status}")
    if (not report.file_path or
        not os.path.exists(report.file_path)):
        raise HTTPException(
            status_code=404,
            detail="PDF file not found")

    return FileResponse(
        path=report.file_path,
        media_type="application/pdf",
        filename=(
            f"IDF_AI_Report_"
            f"{report.report_type.replace(' ','_')}"
            f"_{report_id[:8]}.pdf"
        )
    )

@router.get("/{report_id}")
def get_report(
    case_id: str,
    report_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.case_id == case_id
    ).first()
    if not report:
        raise HTTPException(
            status_code=404,
            detail="Report not found")
    return {
        "id": report.id,
        "report_type": report.report_type,
        "generated_by": report.generated_by,
        "generated_at": str(
            report.generated_at),
        "status": report.status,
        "page_count": report.page_count,
        "sha256_hash": report.sha256_hash,
        "file_exists": (
            os.path.exists(report.file_path)
            if report.file_path else False),
        "query_ids_included": json.loads(
            report.query_ids_included or '[]')
    }

@router.delete("/{report_id}")
def delete_report(
    case_id: str,
    report_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_admin),
):
    report = db.query(models.Report).filter(
        models.Report.id == report_id,
        models.Report.case_id == case_id
    ).first()
    if not report:
        raise HTTPException(
            status_code=404,
            detail="Report not found")
    # Delete PDF from disk
    if (report.file_path and
        os.path.exists(report.file_path)):
        os.remove(report.file_path)
    db.delete(report)
    db.commit()
    return {"success": True,
            "message": "Report deleted"}

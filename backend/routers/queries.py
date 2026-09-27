from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from backend.database import get_db
from backend import models, schemas
from backend.modules.rag_engine import run_rag_query
from backend.modules.vector_store import case_qdrant_path
from backend.dependencies import get_settings
from backend.auth import (
    get_current_user,
    require_viewer,
    require_analyst,
    require_investigator,
    require_admin
)
import uuid
import json
import socket
from datetime import datetime

router = APIRouter(
    prefix="/api/cases/{case_id}/queries",
    tags=["Queries"],
)


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
# GET /api/cases/{case_id}/queries
# ---------------------------------------------------------------------------

@router.get("")
def list_queries(
    case_id: str,
    is_flagged: bool = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Return paginated queries for a case, ordered by
    asked_at descending (newest first).
    Optionally filter by is_flagged.
    """
    try:
        page = max(1, page)
        page_size = max(1, min(page_size, 200))

        query = db.query(models.QueryLog).filter(
            models.QueryLog.case_id == case_id,
            ~models.QueryLog.question_text.startswith("[PROFILE]"),
            ~models.QueryLog.question_text.startswith("[SUMMARY]"),
            ~models.QueryLog.question_text.startswith("[CONTRADICTION"),
            ~models.QueryLog.question_text.startswith("[PROFILE"),
        )
        if is_flagged is not None:
            query = query.filter(
                models.QueryLog.is_flagged == is_flagged)

        total = query.count()
        queries = query.order_by(
            models.QueryLog.asked_at.asc()
        ).offset(
            (page - 1) * page_size
        ).limit(page_size).all()

        return {
            "items": [{
                "id": q.id,
                "question_text": q.question_text,
                "processed_response": q.processed_response,
                "raw_llm_response": q.raw_llm_response,
                "asked_by": q.asked_by,
                "asked_at": str(q.asked_at),
                "is_flagged": q.is_flagged,
                "model_used": q.model_used,
                "cited_sentence_count": q.cited_sentence_count,
                "uncited_sentence_count": q.uncited_sentence_count,
                "response_time_ms": q.response_time_ms,
            } for q in queries],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(1, (total + page_size - 1) // page_size),
            "has_next": page * page_size < total,
            "has_prev": page > 1,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve queries",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/queries/ask
# ---------------------------------------------------------------------------

@router.post("/ask", status_code=201)
def ask_question(
    case_id: str,
    body: schemas.QueryCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """
    Runs the full RAG pipeline and saves the
    query + response to QueryLog.
    """
    settings = get_settings()
    qdrant_path = case_qdrant_path(case_id)

    # Verify case exists
    case = db.query(models.Case).filter(
        models.Case.id == case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found"
        )

    try:
        # Run RAG pipeline
        result = run_rag_query(
            query=body.question_text,
            case_id=case_id,
            qdrant_path=qdrant_path,
            cases_dir=settings.cases_dir,
            evidence_id=body.evidence_id,
            asked_by=body.asked_by,
            conversation_history=body.conversation_history
        )

        # Save to QueryLog
        query_id = str(uuid.uuid4())
        query_log = models.QueryLog(
            id=query_id,
            case_id=case_id,
            evidence_id=body.evidence_id,
            asked_by=body.asked_by,
            question_text=body.question_text,
            raw_llm_response=result[
                "raw_llm_response"],
            processed_response=result["answer"],
            chunks_used=json.dumps(
                result["chunks_used"]),
            graph_context=result["graph_context"],
            model_used=result["model_used"],
            cited_sentence_count=result[
                "cited_sentence_count"],
            uncited_sentence_count=result[
                "uncited_sentence_count"],
            response_time_ms=result[
                "response_time_ms"]
        )
        db.add(query_log)

        # Audit log
        audit = models.AuditLog(
            id=str(uuid.uuid4()),
            case_id=case_id,
            action_type="QUERY_MADE",
            performed_by=body.asked_by,
            details=json.dumps({
                "question": body.question_text,
                "model": result["model_used"],
                "response_time_ms": result[
                    "response_time_ms"]
            })
        )
        db.add(audit)
        db.commit()

        return {
            "query_id": query_id,
            "answer": result["answer"],
            "cited_sentence_count": result[
                "cited_sentence_count"],
            "uncited_sentence_count": result[
                "uncited_sentence_count"],
            "response_time_ms": result[
                "response_time_ms"],
            "model_used": result["model_used"],
            "ollama_available": result[
                "ollama_available"]
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/queries/{query_id}
# ---------------------------------------------------------------------------

@router.get("/{query_id}", response_model=schemas.QueryResponse)
def get_query(
    case_id: str,
    query_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Return a single query log entry."""
    try:
        db_query = (
            db.query(models.QueryLog)
            .filter(
                models.QueryLog.id == query_id,
                models.QueryLog.case_id == case_id,
            )
            .first()
        )
        if not db_query:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Query not found",
                    detail=f"No query with id={query_id} in case {case_id}",
                ).model_dump(),
            )
        return db_query
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve query",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# PATCH /api/cases/{case_id}/queries/{query_id}/flag
# ---------------------------------------------------------------------------

@router.patch("/{query_id}/flag", response_model=schemas.QueryResponse)
def flag_query(
    case_id: str,
    query_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """Toggle the is_flagged boolean for a query."""
    try:
        db_query = (
            db.query(models.QueryLog)
            .filter(
                models.QueryLog.id == query_id,
                models.QueryLog.case_id == case_id,
            )
            .first()
        )
        if not db_query:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Query not found",
                    detail=f"No query with id={query_id} in case {case_id}",
                ).model_dump(),
            )

        db_query.is_flagged = not db_query.is_flagged
        db.commit()
        db.refresh(db_query)

        _create_audit(
            db=db,
            action_type="QUERY_FLAGGED",
            performed_by=current_user.username,
            details={
                "query_id": query_id,
                "is_flagged": db_query.is_flagged,
            },
            case_id=case_id,
        )

        return db_query
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to flag query",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# DELETE /api/cases/{case_id}/queries/{query_id}
# ---------------------------------------------------------------------------

@router.delete("/{query_id}", response_model=schemas.SuccessResponse)
def delete_query(
    case_id: str,
    query_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """Hard-delete a query log entry."""
    try:
        db_query = (
            db.query(models.QueryLog)
            .filter(
                models.QueryLog.id == query_id,
                models.QueryLog.case_id == case_id,
            )
            .first()
        )
        if not db_query:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Query not found",
                    detail=f"No query with id={query_id} in case {case_id}",
                ).model_dump(),
            )

        db.delete(db_query)
        db.commit()

        _create_audit(
            db=db,
            action_type="QUERY_DELETED",
            performed_by=current_user.username,
            details={"query_id": query_id},
            case_id=case_id,
        )

        return schemas.SuccessResponse(message=f"Query {query_id} deleted successfully.")
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to delete query",
                detail=str(exc),
            ).model_dump(),
        )

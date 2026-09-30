from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Optional
from backend.database import get_db
from backend import models, schemas
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
    prefix="/api/cases/{case_id}/notes",
    tags=["Notes"],
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
# GET /api/cases/{case_id}/notes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[schemas.NoteResponse])
def list_notes(
    case_id: str,
    linked_to_type: Optional[str] = None,
    linked_to_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Return notes for a case ordered by created_at descending.
    Optionally filter by linked_to_type and/or linked_to_id.
    """
    try:
        query = db.query(models.Note).filter(models.Note.case_id == case_id)
        if linked_to_type is not None:
            query = query.filter(models.Note.linked_to_type == linked_to_type)
        if linked_to_id is not None:
            query = query.filter(models.Note.linked_to_id == linked_to_id)
        notes = query.order_by(models.Note.created_at.desc()).all()
        return notes
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve notes",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/notes
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.NoteResponse, status_code=201)
def create_note(
    case_id: str,
    body: schemas.NoteCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """Create a new note linked to a case."""
    try:
        # Verify case exists
        db_case = db.query(models.Case).filter(models.Case.id == case_id).first()
        if not db_case:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Case not found",
                    detail=f"No case with id={case_id}",
                ).model_dump(),
            )

        note_id = str(uuid.uuid4())
        now = datetime.utcnow()

        db_note = models.Note(
            id=note_id,
            case_id=case_id,
            linked_to_type=body.linked_to_type,
            linked_to_id=body.linked_to_id,
            # Was `body.author` - the client's own claim about who wrote the
            # note. A note is an assertion inside a case file, so a
            # self-declared author is a falsifiable assertion: any analyst
            # could plant a note in someone else's name. The authenticated
            # identity is the only value the server chose, and it is
            # already resolved by the route dependency.
            author=current_user.username,
            content=body.content,
            created_at=now,
            updated_at=now,
            is_flagged=False,
        )
        db.add(db_note)
        db.commit()
        db.refresh(db_note)

        _create_audit(
            db=db,
            action_type="NOTE_ADDED",
            # Same reasoning as `author` above: the audit log is the
            # forensic chain of record, and an entry whose actor is
            # self-declared cannot serve as one.
            performed_by=current_user.username,
            details={
                "note_id": note_id,
                "linked_to_type": body.linked_to_type,
                "linked_to_id": body.linked_to_id,
            },
            case_id=case_id,
        )

        return db_note
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to create note",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# PATCH /api/cases/{case_id}/notes/{note_id}
# ---------------------------------------------------------------------------

@router.patch("/{note_id}", response_model=schemas.NoteResponse)
def update_note(
    case_id: str,
    note_id: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """Update the content of a note. Only content and updated_at are changed."""
    try:
        db_note = (
            db.query(models.Note)
            .filter(
                models.Note.id == note_id,
                models.Note.case_id == case_id,
            )
            .first()
        )
        if not db_note:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Note not found",
                    detail=f"No note with id={note_id} in case {case_id}",
                ).model_dump(),
            )

        if "content" in body:
            db_note.content = body["content"]
        db_note.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_note)
        return db_note
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to update note",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# DELETE /api/cases/{case_id}/notes/{note_id}
# ---------------------------------------------------------------------------

@router.delete("/{note_id}", response_model=schemas.SuccessResponse)
def delete_note(
    case_id: str,
    note_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """Hard-delete a note."""
    try:
        db_note = (
            db.query(models.Note)
            .filter(
                models.Note.id == note_id,
                models.Note.case_id == case_id,
            )
            .first()
        )
        if not db_note:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Note not found",
                    detail=f"No note with id={note_id} in case {case_id}",
                ).model_dump(),
            )

        db.delete(db_note)
        db.commit()

        return schemas.SuccessResponse(message=f"Note {note_id} deleted successfully.")
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to delete note",
                detail=str(exc),
            ).model_dump(),
        )

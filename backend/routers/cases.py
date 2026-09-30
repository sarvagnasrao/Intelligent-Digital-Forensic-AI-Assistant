from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import zipfile, tempfile, io
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
import json
import os
from datetime import datetime

router = APIRouter(prefix="/api/cases", tags=["Cases"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse_case(db_case: models.Case, db: Session) -> schemas.CaseResponse:
    """
    Convert a SQLAlchemy Case ORM object into a CaseResponse,
    parsing the tags JSON string and computing counts.
    """
    try:
        tags = json.loads(db_case.tags) if db_case.tags else []
    except (json.JSONDecodeError, TypeError):
        tags = []

    evidence_count = (
        db.query(models.Evidence)
        .filter(models.Evidence.case_id == db_case.id)
        .count()
    )
    query_count = (
        db.query(models.QueryLog)
        .filter(models.QueryLog.case_id == db_case.id)
        .count()
    )

    return schemas.CaseResponse(
        id=db_case.id,
        case_name=db_case.case_name,
        case_number=db_case.case_number,
        status=db_case.status,
        priority=db_case.priority,
        description=db_case.description,
        created_by=db_case.created_by,
        created_at=db_case.created_at,
        updated_at=db_case.updated_at,
        tags=tags,
        evidence_count=evidence_count,
        query_count=query_count,
    )


def _create_audit(
    db: Session,
    action_type: str,
    performed_by: str,
    details: dict,
    case_id: str = None,
):
    """Create an AuditLog entry."""
    import socket
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
# GET /api/cases
# ---------------------------------------------------------------------------

@router.get("", response_model=list[schemas.CaseResponse])
def list_cases(
    status: str = None,
    priority: str = None,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Return cases ordered by created_at descending.
    Admins see all cases; all other roles only see cases
    they have been assigned to via CaseAccess.
    """
    try:
        query = db.query(models.Case)

        # Scope to assigned cases for non-Admin users
        if current_user.role != "Admin":
            accessible_ids = [
                a.case_id for a in
                db.query(models.CaseAccess).filter(
                    models.CaseAccess.user_id == current_user.id
                ).all()
            ]
            query = query.filter(models.Case.id.in_(accessible_ids))

        if status:
            query = query.filter(models.Case.status == status)
        if priority:
            query = query.filter(models.Case.priority == priority)

        cases = query.order_by(models.Case.created_at.desc()).all()
        return [_parse_case(c, db) for c in cases]
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve cases",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# POST /api/cases
# ---------------------------------------------------------------------------

@router.post("", response_model=schemas.CaseResponse, status_code=201)
def create_case(
    body: schemas.CaseCreate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """Create a new investigation case."""
    try:
        settings = get_settings()
        case_id = str(uuid.uuid4())

        case_number = body.case_number if body.case_number else None

        db_case = models.Case(
            id=case_id,
            case_name=body.case_name,
            case_number=case_number,
            status="Open",
            priority=body.priority,
            description=body.description,
            # Was `body.created_by` - a field the client supplied, written
            # straight into the case record. Any authenticated user could
            # create a case attributed to anyone, including the Admin, and
            # the lie would persist in the case header forever.
            #
            # The authenticated identity is already resolved by the route's
            # dependency; it is the only value that can be trusted here,
            # because it is the only one the server chose. The client field
            # is still accepted (see schemas.CaseCreate) so existing callers
            # do not break, but it no longer decides anything.
            created_by=current_user.username,
            tags=json.dumps(body.tags),
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(db_case)
        db.commit()
        db.refresh(db_case)

        # Create folder structure on disk
        evidence_dir = os.path.join(settings.cases_dir, case_id, "evidence")
        reports_dir = os.path.join(settings.cases_dir, case_id, "reports")
        os.makedirs(evidence_dir, exist_ok=True)
        os.makedirs(reports_dir, exist_ok=True)

        # Audit log
        _create_audit(
            db=db,
            action_type="CASE_CREATED",
            # Same reasoning as `created_by` above. The audit log is the
            # forensic chain of record: a value the caller supplied is a
            # value the caller can choose, and an audit entry is worthless
            # the moment its actor is self-declared.
            performed_by=current_user.username,
            details={"case_name": body.case_name, "case_id": case_id},
            case_id=case_id,
        )

        # Auto-grant 'manage' access to the creator so they can see their own case
        db.add(models.CaseAccess(
            id=str(uuid.uuid4()),
            case_id=case_id,
            user_id=current_user.id,
            granted_by="system",
            role_on_case="Investigator",
        ))
        db.commit()

        return _parse_case(db_case, db)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        import traceback; traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to create case",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}
# ---------------------------------------------------------------------------

@router.get("/{case_id}", response_model=schemas.CaseResponse)
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Return a single case by ID."""
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
        return _parse_case(db_case, db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve case",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# PATCH /api/cases/{case_id}
# ---------------------------------------------------------------------------

@router.patch("/{case_id}", response_model=schemas.CaseResponse)
def update_case(
    case_id: str,
    body: schemas.CaseUpdate,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """Update mutable fields of a case."""
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

        updated_fields = {}
        if body.case_name is not None:
            db_case.case_name = body.case_name
            updated_fields["case_name"] = body.case_name
        if body.status is not None:
            db_case.status = body.status
            updated_fields["status"] = body.status
        if body.priority is not None:
            db_case.priority = body.priority
            updated_fields["priority"] = body.priority
        if body.description is not None:
            db_case.description = body.description
            updated_fields["description"] = body.description
        if body.tags is not None:
            db_case.tags = json.dumps(body.tags)
            updated_fields["tags"] = body.tags

        db_case.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_case)

        _create_audit(
            db=db,
            action_type="CASE_UPDATED",
            performed_by=current_user.username,
            details={"case_id": case_id, "updated_fields": updated_fields},
            case_id=case_id,
        )

        return _parse_case(db_case, db)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to update case",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# DELETE /api/cases/{case_id}  — soft delete (archive)
# ---------------------------------------------------------------------------

@router.delete("/{case_id}", response_model=schemas.SuccessResponse)
def archive_case(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_investigator),
):
    """
    Soft-delete a case by setting status to 'Archived'.
    Cases are never hard-deleted.
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

        db_case.status = "Archived"
        db_case.updated_at = datetime.utcnow()
        db.commit()

        _create_audit(
            db=db,
            action_type="CASE_CLOSED",
            performed_by=current_user.username,
            details={"case_id": case_id, "case_name": db_case.case_name},
            case_id=case_id,
        )

        return schemas.SuccessResponse(message=f"Case {case_id} archived successfully.")
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to archive case",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# AI Case Summary
# ---------------------------------------------------------------------------

@router.post("/{case_id}/summary")
def generate_case_summary(
    case_id: str,
    current_user=Depends(require_analyst),
    db: Session = Depends(get_db),
):
    """
    Generates an AI executive summary of the entire case.
    Gathers all evidence, entities, queries, and notes,
    then synthesises them into a professional report via Ollama.
    """
    from backend.modules.ollama_client import (
        generate_response, ollama_diagnostic)
    from backend.modules.vector_store import search_chunks
    import time

    settings = get_settings()

    # Verify case exists
    case = db.query(models.Case).filter(models.Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    # Gather indexed evidence
    evidence = (
        db.query(models.Evidence)
        .filter(
            models.Evidence.case_id == case_id,
            models.Evidence.status == "Indexed",
        )
        .all()
    )

    # Top entities by frequency
    entities = (
        db.query(models.Entity)
        .filter(models.Entity.case_id == case_id)
        .order_by(models.Entity.frequency.desc())
        .limit(30)
        .all()
    )

    flagged_entities = [e for e in entities if e.is_flagged]

    # Anomaly count
    anomalies = (
        db.query(models.ForensicArtifact)
        .filter(
            models.ForensicArtifact.case_id == case_id,
            models.ForensicArtifact.is_anomaly == True,
        )
        .count()
    )

    # Recent investigator queries
    queries = (
        db.query(models.QueryLog)
        .filter(
            models.QueryLog.case_id == case_id,
            models.QueryLog.question_text != "[SUMMARY] Case Summary",
        )
        .order_by(models.QueryLog.asked_at.desc())
        .limit(10)
        .all()
    )

    # Notes
    notes = db.query(models.Note).filter(models.Note.case_id == case_id).all()

    # Build text summaries
    entity_summary = "\n".join([
        f"- {e.name} ({e.entity_type}, {e.frequency} mentions"
        f"{', FLAGGED' if e.is_flagged else ''})"
        for e in entities[:20]
    ]) or "No entities extracted yet."

    query_summary = "\n".join([
        f"Q: {q.question_text}\nA: {(q.processed_response or '')[:300]}..."
        for q in queries[:5]
    ]) or "No queries made yet."

    notes_summary = "\n".join([
        f"- [{n.author}]: {n.content}"
        for n in notes
    ]) or "No notes added."

    # Retrieve key evidence chunks from vector store
    qdrant_path = case_qdrant_path(case_id)
    key_chunks = []
    if os.path.exists(qdrant_path):
        for term in ["suspect", "evidence", "timeline", "location", "communication"]:
            try:
                chunks = search_chunks(
                    query=term,
                    case_id=case_id,
                    qdrant_path=qdrant_path,
                    top_k=2,
                )
                key_chunks.extend(chunks)
            except Exception:
                pass

    # Deduplicate chunks
    seen = set()
    unique_chunks = []
    for c in key_chunks:
        key = c["text"][:50]
        if key not in seen:
            seen.add(key)
            unique_chunks.append(c)
    unique_chunks = unique_chunks[:8]

    evidence_context = "\n\n".join([
        f"[Evidence {i + 1} from {c['source']}]\n{c['text']}"
        for i, c in enumerate(unique_chunks)
    ]) or "No evidence indexed yet."

    SUMMARY_PROMPT = f"""You are a senior forensic analyst.
Write a professional executive case summary report based on the information below.
Structure it clearly with these sections:

1. CASE OVERVIEW
2. KEY SUBJECTS (persons of interest)
3. DIGITAL EVIDENCE SUMMARY
4. TIMELINE OF EVENTS (if determinable)
5. KEY FINDINGS
6. SUSPICIOUS INDICATORS
7. EVIDENCE GAPS & RECOMMENDATIONS
8. CONCLUSION

Be factual, professional, and concise. Cite evidence where possible.

CASE: {case.case_name}
STATUS: {case.status}
PRIORITY: {case.priority}
DESCRIPTION: {case.description or 'Not provided'}
INVESTIGATOR: {case.created_by}

EVIDENCE FILES ({len(evidence)} indexed):
{chr(10).join([f'- {e.original_filename} ({e.chunk_count} chunks)' for e in evidence]) or '- None indexed'}

KEY ENTITIES EXTRACTED:
{entity_summary}

FLAGGED ENTITIES:
{chr(10).join([f'- {e.name} ({e.entity_type})' for e in flagged_entities]) or 'None flagged'}

ANOMALIES DETECTED: {anomalies}

INVESTIGATOR QUERIES:
{query_summary}

INVESTIGATOR NOTES:
{notes_summary}

KEY EVIDENCE EXCERPTS:
{evidence_context}

Write the executive summary now:"""

    # Generate or fallback
    # Gated on a model existing, not merely on the daemon answering.
    # /api/tags returns 200 with an empty model list on a machine that never
    # pulled a model, so the old check passed and the "summary" persisted was
    # the model's own error text filed as a case summary.
    diag = ollama_diagnostic()
    if not (diag["running"] and diag["model_ready"]):
        summary_text = (
            f"## {case.case_name} — Executive Summary\n\n"
            f"**Status:** {case.status}  \n"
            f"**Priority:** {case.priority}  \n"
            f"**Evidence Files:** {len(evidence)}  \n"
            f"**Entities Extracted:** {len(entities)}  \n"
            f"**Anomalies Detected:** {anomalies}  \n\n"
            f"*{diag['reason'] or 'Ollama is not ready to answer.'} "
            f"Start Ollama and regenerate for a full AI summary.*"
        )
    else:
        summary_text = generate_response(
            prompt=SUMMARY_PROMPT,
            system_prompt=(
                "You are a senior forensic analyst writing official case reports. "
                "Be professional, factual, and structured. Use markdown formatting."
            ),
        )

    # Persist as a flagged QueryLog entry so it survives between sessions
    summary_log = models.QueryLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        asked_by=current_user.username,
        question_text="[SUMMARY] Case Summary",
        processed_response=summary_text,
        raw_llm_response=summary_text,
        model_used="llama3.2:3b",
        cited_sentence_count=0,
        uncited_sentence_count=0,
        response_time_ms=0,
        is_flagged=True,
    )
    db.add(summary_log)

    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type="SUMMARY_GENERATED",
        performed_by=current_user.username,
        details=json.dumps({
            "case_name": case.case_name,
            "evidence_count": len(evidence),
            "entity_count": len(entities),
        }),
    ))
    db.commit()

    return {
        "summary": summary_text,
        "summary_id": summary_log.id,
        "case_name": case.case_name,
        "generated_by": current_user.username,
        "generated_at": str(summary_log.asked_at),
        "stats": {
            "evidence_files": len(evidence),
            "entities": len(entities),
            "flagged_entities": len(flagged_entities),
            "anomalies": anomalies,
            "queries": len(queries),
            "notes": len(notes),
        },
    }


@router.get("/{case_id}/summary/latest")
def get_latest_summary(
    case_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Gets the most recently generated AI summary for this case."""
    summary = (
        db.query(models.QueryLog)
        .filter(
            models.QueryLog.case_id == case_id,
            models.QueryLog.question_text == "[SUMMARY] Case Summary",
        )
        .order_by(models.QueryLog.asked_at.desc())
        .first()
    )

    if not summary:
        return {"has_summary": False}

    return {
        "has_summary": True,
        "summary": summary.processed_response,
        "summary_id": summary.id,
        "generated_at": str(summary.asked_at),
        "generated_by": summary.asked_by,
    }

# ---------------------------------------------------------------------------
# CONTRADICTIONS
# ---------------------------------------------------------------------------

@router.post("/{case_id}/contradictions")
def detect_contradictions(
    case_id: str,
    current_user=Depends(require_analyst),
    db: Session = Depends(get_db)
):
    """
    Uses AI to identify contradictions
    and inconsistencies across all evidence
    in the case.
    """
    from backend.modules.ollama_client import (
        generate_response,
        ollama_diagnostic
    )
    from backend.modules.vector_store import search_chunks
    from backend.dependencies import get_settings
    import json

    settings = get_settings()

    # Get all query answers
    queries = db.query(models.QueryLog).filter(
        models.QueryLog.case_id == case_id,
        models.QueryLog.is_flagged == False,
        ~models.QueryLog.question_text.startswith("[SUMMARY]"),
        ~models.QueryLog.question_text.startswith("[PROFILE]"),
    ).order_by(
        models.QueryLog.asked_at.desc()
    ).limit(20).all()

    # Get anomalous artifacts
    anomalies = db.query(models.ForensicArtifact).filter(
        models.ForensicArtifact.case_id == case_id,
        models.ForensicArtifact.is_anomaly == True
    ).limit(15).all()

    # Get key evidence chunks
    qdrant_path = case_qdrant_path(case_id)

    key_chunks = []
    for term in [
        "date created modified",
        "timeline sequence",
        "location",
        "identity alias",
        "communication sent received"
    ]:
        try:
            chunks = search_chunks(
                query=term,
                case_id=case_id,
                qdrant_path=qdrant_path,
                top_k=3
            )
            key_chunks.extend(chunks)
        except:
            pass

    # Deduplicate chunks
    seen = set()
    unique_chunks = []
    for c in key_chunks:
        key = c['text'][:40]
        if key not in seen:
            seen.add(key)
            unique_chunks.append(c)
    unique_chunks = unique_chunks[:12]

    # Build evidence context
    evidence_text = ""
    for i, c in enumerate(unique_chunks, 1):
        evidence_text += (
            f"\n[Statement {i} from {c['source']}]\n"
            f"{c['text'][:400]}\n"
        )

    # Build query context
    query_text = ""
    for q in queries[:10]:
        if q.processed_response:
            query_text += (
                f"\nQ: {q.question_text}\n"
                f"A: {q.processed_response[:300]}\n"
            )

    # Anomaly context
    anomaly_text = "\n".join([
        f"- {a.filename}: {a.anomaly_reasons}"
        for a in anomalies[:10]
    ])

    CONTRADICTION_PROMPT = f"""
You are a forensic analyst reviewing
case evidence for internal contradictions
and inconsistencies.

Below is evidence from the case.
Your task:
1. Identify SPECIFIC contradictions
   (e.g., conflicting dates, conflicting
   locations, conflicting identities)
2. Identify SUSPICIOUS gaps or missing
   context
3. Identify statements that cannot both
   be true simultaneously
4. Note any timeline impossibilities

FORMAT your response as:

## Contradictions Found

### Contradiction 1: [Brief title]
- **Statement A:** [exact quote/paraphrase]
  Source: [filename]
- **Statement B:** [exact quote/paraphrase]
  Source: [filename]
- **Why this matters:** [forensic implication]

[Repeat for each contradiction]

## Suspicious Gaps
[List any important missing evidence or gaps]

## Timeline Inconsistencies
[Any temporal contradictions]

## Verdict
[Summary: High/Medium/Low contradiction level
and what it suggests about the evidence]

If no contradictions are found, say:
"No significant contradictions detected.
Evidence appears internally consistent."

---

EVIDENCE STATEMENTS:
{evidence_text}

INVESTIGATOR QUERY ANSWERS:
{query_text}

TIMESTAMP ANOMALIES:
{anomaly_text or 'None detected'}

Analyse for contradictions now:
"""

    diag = ollama_diagnostic()
    if not (diag["running"] and diag["model_ready"]):
        result_text = (
            "## Contradiction Analysis\n\n"
            f"{diag['reason'] or 'Ollama is not ready to answer.'} "
            "Start Ollama and retry.\n\n"
            f"**Evidence statements "
            f"ready for analysis:** "
            f"{len(unique_chunks)}\n"
            f"**Query answers:** "
            f"{len(queries)}\n"
            f"**Anomalies:** "
            f"{len(anomalies)}"
        )
    else:
        result_text = generate_response(
            prompt=CONTRADICTION_PROMPT,
            system_prompt=(
                "You are a forensic analyst "
                "specialising in detecting "
                "inconsistencies in digital "
                "evidence. Be specific, "
                "cite sources, and be "
                "concise. Use markdown."
            )
        )

    # Count contradictions found
    contradiction_count = result_text.count("### Contradiction")

    # Save as flagged query log
    log = models.QueryLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        asked_by=current_user.username,
        question_text="[CONTRADICTION_ANALYSIS] Contradiction Detection",
        processed_response=result_text,
        raw_llm_response=result_text,
        model_used="llama3.2:3b",
        cited_sentence_count=0,
        uncited_sentence_count=0,
        response_time_ms=0,
        is_flagged=contradiction_count > 0
    )
    db.add(log)

    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type="CONTRADICTION_ANALYSIS",
        performed_by=current_user.username,
        details=json.dumps({
            "contradictions_found": contradiction_count,
            "evidence_statements": len(unique_chunks),
        })
    ))
    db.commit()

    return {
        "analysis": result_text,
        "contradictions_found": contradiction_count,
        "evidence_statements_analysed": len(unique_chunks),
        "queries_analysed": len(queries),
        "anomalies_included": len(anomalies),
        "has_contradictions": contradiction_count > 0,
        "analysis_id": log.id,
        "generated_at": str(log.asked_at),
    }

@router.get("/{case_id}/contradictions/latest")
def get_latest_contradiction_analysis(
    case_id: str,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db)
):
    log = db.query(models.QueryLog).filter(
        models.QueryLog.case_id == case_id,
        models.QueryLog.question_text.startswith("[CONTRADICTION_ANALYSIS]")
    ).order_by(
        models.QueryLog.asked_at.desc()
    ).first()
    if not log:
        return {"has_analysis": False}
    return {
        "has_analysis": True,
        "analysis": log.processed_response,
        "generated_at": str(log.asked_at),
        "generated_by": log.asked_by,
        "has_contradictions": log.is_flagged
    }


# ---------------------------------------------------------------------------
# POST /api/cases/import
# Declared before /{case_id}/export so "import" isn't captured as case_id.
# ---------------------------------------------------------------------------

@router.post("/import", status_code=201)
async def import_case(
    file: UploadFile = File(...),
    current_user: models.User = Depends(require_investigator),
    db: Session = Depends(get_db),
):
    """
    Imports a case from a ZIP package created by the export endpoint.
    Creates a new case with a fresh ID. Entities, notes, watchlist
    keywords, and the entity graph are all restored.
    """
    if not (file.filename or "").endswith(".zip"):
        raise HTTPException(status_code=400, detail="Must be a .zip file")

    content = await file.read()
    settings = get_settings()

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            names = zf.namelist()

            if "case_meta.json" not in names:
                raise HTTPException(
                    status_code=400,
                    detail="Not a valid IDF AI case export — missing case_meta.json",
                )

            # ── Case meta ────────────────────────────────────────────────────
            meta = json.loads(zf.read("case_meta.json"))
            new_case_id = str(uuid.uuid4())

            orig_desc  = meta.get("description") or ""
            import_note = (
                f"\n\nImported from: \"{meta.get('case_name')}\" "
                f"— Original ID: {meta['id'][:8]}"
            )
            new_case = models.Case(
                id=new_case_id,
                case_name=meta["case_name"] + " (Imported)",
                case_number=meta.get("case_number"),
                status=meta.get("status", "Open"),
                priority=meta.get("priority", "Medium"),
                description=orig_desc + import_note,
                created_by=current_user.username,
                tags=meta.get("tags"),
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
            )
            db.add(new_case)

            # Grant importer manage access
            db.add(models.CaseAccess(
                id=str(uuid.uuid4()),
                case_id=new_case_id,
                user_id=current_user.id,
                granted_by="import",
                role_on_case="Investigator",
            ))

            # Create case directory on disk
            case_dir = os.path.join(settings.cases_dir, new_case_id)
            os.makedirs(os.path.join(case_dir, "evidence"), exist_ok=True)
            os.makedirs(os.path.join(case_dir, "reports"),  exist_ok=True)

            # ── Entities ─────────────────────────────────────────────────────
            if "entities.json" in names:
                for e in json.loads(zf.read("entities.json")):
                    db.add(models.Entity(
                        id=str(uuid.uuid4()),
                        case_id=new_case_id,
                        name=e["name"],
                        entity_type=e["entity_type"],
                        frequency=e.get("frequency", 1),
                        aliases=e.get("aliases", "[]"),
                        is_flagged=e.get("is_flagged", False),
                    ))

            # ── Notes ────────────────────────────────────────────────────────
            if "notes.json" in names:
                for n in json.loads(zf.read("notes.json")):
                    db.add(models.Note(
                        id=str(uuid.uuid4()),
                        case_id=new_case_id,
                        content=n["content"],
                        author=(n.get("author", "") + " (imported)").strip(),
                    ))

            # ── Watchlist ────────────────────────────────────────────────────
            if "watchlist.json" in names:
                for w in json.loads(zf.read("watchlist.json")):
                    db.add(models.WatchlistKeyword(
                        id=str(uuid.uuid4()),
                        case_id=new_case_id,
                        keyword=w["keyword"],
                        category=w.get("category"),
                        added_by=current_user.username,
                        hit_count=0,
                        is_active=True,
                    ))

            # ── Entity graph ─────────────────────────────────────────────────
            if "graph_store.json" in names:
                graph_dest = os.path.join(case_dir, "graph_store.json")
                with open(graph_dest, "wb") as gf:
                    gf.write(zf.read("graph_store.json"))

            db.commit()

            # ── Audit log ────────────────────────────────────────────────────
            db.add(models.AuditLog(
                id=str(uuid.uuid4()),
                case_id=new_case_id,
                action_type="CASE_IMPORTED",
                performed_by=current_user.username,
                performed_at=datetime.utcnow(),
                details=json.dumps({
                    "original_case_name": meta.get("case_name"),
                    "original_id":        meta["id"][:8],
                    "import_version":     meta.get("export_version", "unknown"),
                }),
            ))
            db.commit()

            return {
                "new_case_id": new_case_id,
                "case_name":   new_case.case_name,
                "message":     "Case imported successfully",
            }

    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"Import failed: {exc}")


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/export
# ---------------------------------------------------------------------------

@router.get("/{case_id}/export")
def export_case(
    case_id: str,
    include_files: bool = False,
    current_user: models.User = Depends(require_investigator),
    db: Session = Depends(get_db),
):
    """
    Exports an entire case as a ZIP package.
    Includes metadata, evidence records, entities, queries, notes,
    audit log, artifacts (text, capped at 50 k chars), watchlist,
    credentials, and the entity graph JSON.

    Pass ?include_files=true to also bundle extracted binary files
    (images, PDFs, etc. each ≤ 50 MB).
    """
    case = db.query(models.Case).filter(models.Case.id == case_id).first()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")

    settings    = get_settings()
    tmp         = tempfile.mkdtemp()
    date_str    = datetime.utcnow().strftime("%Y%m%d")
    zip_name    = f"idfai_case_{case_id[:8]}_{date_str}.zip"
    zip_path    = os.path.join(tmp, zip_name)

    # Fetch everything before opening the ZIP
    evidence_rows  = db.query(models.Evidence).filter(models.Evidence.case_id == case_id).all()
    entity_rows    = db.query(models.Entity).filter(models.Entity.case_id == case_id).all()
    query_rows     = (
        db.query(models.QueryLog)
        .filter(models.QueryLog.case_id == case_id)
        .order_by(models.QueryLog.asked_at)
        .all()
    )
    note_rows      = db.query(models.Note).filter(models.Note.case_id == case_id).all()
    audit_rows     = (
        db.query(models.AuditLog)
        .filter(models.AuditLog.case_id == case_id)
        .order_by(models.AuditLog.performed_at)
        .all()
    )
    artifact_rows  = (
        db.query(models.ForensicArtifact)
        .filter(models.ForensicArtifact.case_id == case_id)
        .all()
    )
    wl_rows        = (
        db.query(models.WatchlistKeyword)
        .filter(
            models.WatchlistKeyword.case_id == case_id,
            models.WatchlistKeyword.is_active == True,
        )
        .all()
    )
    try:
        cred_rows = (
            db.query(models.CredentialFinding)
            .filter(models.CredentialFinding.case_id == case_id)
            .all()
        )
    except Exception:
        cred_rows = []

    # ── Serialize ─────────────────────────────────────────────────────────────
    case_meta = {
        "id":             case.id,
        "case_name":      case.case_name,
        "case_number":    case.case_number,
        "status":         case.status,
        "priority":       case.priority,
        "description":    case.description,
        "created_by":     case.created_by,
        "created_at":     str(case.created_at),
        "tags":           case.tags,
        "export_version": "1.0",
        "export_date":    str(datetime.utcnow()),
        "exported_by":    current_user.username,
    }
    evidence_data = [
        {
            "id":                e.id,
            "original_filename": e.original_filename,
            "filename":          e.filename,
            "status":            e.status,
            "sha256_hash":       e.sha256_hash,
            "file_size_bytes":   e.file_size_bytes,
            "chunk_count":       e.chunk_count,
            "entity_count":      e.entity_count,
            "ingested_by":       e.ingested_by,
            "ingested_at":       str(e.ingested_at),
        }
        for e in evidence_rows
    ]
    entities_data = [
        {
            "id":          e.id,
            "name":        e.name,
            "entity_type": e.entity_type,
            "frequency":   e.frequency,
            "aliases":     e.aliases,
            "is_flagged":  e.is_flagged,
        }
        for e in entity_rows
    ]
    queries_data = [
        {
            "id":                 q.id,
            "question_text":      q.question_text,
            "processed_response": q.processed_response,
            "asked_by":           q.asked_by,
            "asked_at":           str(q.asked_at),
            "is_flagged":         q.is_flagged,
            "model_used":         q.model_used,
        }
        for q in query_rows
    ]
    notes_data = [
        {
            "id":         n.id,
            "content":    n.content,
            "author":     n.author,
            "created_at": str(n.created_at),
        }
        for n in note_rows
    ]
    audit_data = [
        {
            "action_type":  a.action_type,
            "performed_by": a.performed_by,
            "performed_at": str(a.performed_at),
            "details":      a.details,
        }
        for a in audit_rows
    ]
    artifacts_data = [
        {
            "id":              a.id,
            "filename":        a.filename,
            "internal_path":   a.internal_path,
            "extraction_type": a.extraction_type,
            "file_size_bytes": a.file_size_bytes,
            "sha256_hash":     a.sha256_hash,
            "modified_at":     str(a.modified_at) if a.modified_at else None,
            "shannon_entropy": a.shannon_entropy,
            "is_anomaly":      a.is_anomaly,
            "is_flagged":      a.is_flagged,
            "extracted_text":  (a.extracted_text or "")[:50_000],
        }
        for a in artifact_rows
    ]
    wl_data = [
        {"keyword": w.keyword, "category": w.category, "hit_count": w.hit_count}
        for w in wl_rows
    ]
    creds_data = [
        {
            "credential_type": c.credential_type,
            "severity":        getattr(c, "severity", None),
            "source_file":     getattr(c, "source_file", None),
            "is_confirmed":    c.is_confirmed,
        }
        for c in cred_rows
    ]

    # ── Build ZIP ─────────────────────────────────────────────────────────────
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("case_meta.json",  json.dumps(case_meta,     indent=2))
        zf.writestr("evidence.json",   json.dumps(evidence_data,  indent=2))
        zf.writestr("entities.json",   json.dumps(entities_data,  indent=2))
        zf.writestr("queries.json",    json.dumps(queries_data,   indent=2))
        zf.writestr("notes.json",      json.dumps(notes_data,     indent=2))
        zf.writestr("audit_log.json",  json.dumps(audit_data,     indent=2))
        zf.writestr("artifacts.json",  json.dumps(artifacts_data, indent=2))
        zf.writestr("watchlist.json",  json.dumps(wl_data,        indent=2))
        if creds_data:
            zf.writestr("credentials.json", json.dumps(creds_data, indent=2))

        # Entity relationship graph
        graph_path = os.path.join(settings.cases_dir, case_id, "graph_store.json")
        if os.path.exists(graph_path):
            zf.write(graph_path, "graph_store.json")

        # Optionally bundle extracted binary files (≤ 50 MB each)
        if include_files:
            evidence_dir = os.path.join(settings.cases_dir, case_id, "evidence")
            if os.path.exists(evidence_dir):
                for root, _dirs, files in os.walk(evidence_dir):
                    for fname in files:
                        fp = os.path.join(root, fname)
                        if os.path.getsize(fp) <= 50 * 1024 * 1024:
                            arcname = "extracted_files/" + os.path.relpath(fp, evidence_dir)
                            zf.write(fp, arcname)

        # Human-readable README
        readme = (
            f"# IDF AI Case Export\n\n"
            f"**Case:** {case.case_name}\n"
            f"**Case #:** {case.case_number or '—'}\n"
            f"**Status:** {case.status}\n"
            f"**Exported:** {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"**By:** {current_user.username}\n\n"
            f"## Contents\n\n"
            f"| File | Description |\n"
            f"|------|-------------|\n"
            f"| case_meta.json | Case metadata and identifiers |\n"
            f"| evidence.json | Uploaded evidence file records |\n"
            f"| entities.json | Extracted named entities |\n"
            f"| queries.json | AI investigation queries & answers |\n"
            f"| notes.json | Investigator notes |\n"
            f"| audit_log.json | Chain of custody log |\n"
            f"| artifacts.json | Extracted file artifacts with text |\n"
            f"| watchlist.json | Keyword watchlist |\n"
            f"| credentials.json | Detected credentials (if any) |\n"
            f"| graph_store.json | Entity relationship graph |\n\n"
            f"## Statistics\n\n"
            f"- Evidence files: {len(evidence_data)}\n"
            f"- Entities: {len(entities_data)}\n"
            f"- Queries: {len(queries_data)}\n"
            f"- Artifacts: {len(artifacts_data)}\n\n"
            f"## Import\n\n"
            f"Upload this ZIP via **Cases → Import Case** on any IDF AI Assistant instance.\n"
        )
        zf.writestr("README.md", readme)

    # ── Audit log ─────────────────────────────────────────────────────────────
    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type="CASE_EXPORTED",
        performed_by=current_user.username,
        performed_at=datetime.utcnow(),
        details=json.dumps({
            "case_name":      case.case_name,
            "include_files":  include_files,
            "evidence_count": len(evidence_data),
            "artifact_count": len(artifacts_data),
            "zip_name":       zip_name,
        }),
    ))
    db.commit()

    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=zip_name,
        headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
    )

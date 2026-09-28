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
    prefix="/api/cases/{case_id}/entities",
    tags=["Entities"],
)


# ---------------------------------------------------------------------------
# Helper: parse aliases JSON string → list[str]
# ---------------------------------------------------------------------------

def _parse_entity(db_entity: models.Entity) -> schemas.EntityResponse:
    try:
        aliases = json.loads(db_entity.aliases) if db_entity.aliases else []
    except (json.JSONDecodeError, TypeError):
        aliases = []

    return schemas.EntityResponse(
        id=db_entity.id,
        case_id=db_entity.case_id,
        name=db_entity.name,
        entity_type=db_entity.entity_type,
        frequency=db_entity.frequency,
        aliases=aliases,
        is_flagged=db_entity.is_flagged,
        notes=db_entity.notes,
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
# GET /api/cases/{case_id}/entities
# ---------------------------------------------------------------------------

@router.get("")
def list_entities(
    case_id: str,
    entity_type: Optional[str] = None,
    is_flagged: Optional[bool] = None,
    page: int = 1,
    page_size: int = 100,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Return paginated entities for a case, ordered by
    frequency descending. Optionally filter by
    entity_type and/or is_flagged.
    """
    try:
        page = max(1, page)
        page_size = max(1, min(page_size, 500))

        query = db.query(models.Entity).filter(
            models.Entity.case_id == case_id)
        if entity_type is not None:
            query = query.filter(
                models.Entity.entity_type == entity_type)
        if is_flagged is not None:
            query = query.filter(
                models.Entity.is_flagged == is_flagged)

        total = query.count()
        offset = (page - 1) * page_size
        entities = query.order_by(
            models.Entity.frequency.desc()
        ).offset(offset).limit(page_size).all()

        return {
            "items": [_parse_entity(e) for e in entities],
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": max(
                1, (total + page_size - 1) // page_size),
            "has_next": page * page_size < total,
            "has_prev": page > 1,
        }
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve entities",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/entities/graph
# ---------------------------------------------------------------------------

@router.get("/graph")
def get_graph(
    case_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """
    Returns the full NetworkX graph data
    for visualization.
    """
    from backend.modules.graph_builder import (
        get_graph_data, get_entity_summary)
    from backend.dependencies import get_settings
    settings = get_settings()

    case = db.query(models.Case).filter(
        models.Case.id == case_id
    ).first()
    if not case:
        raise HTTPException(
            status_code=404,
            detail="Case not found"
        )

    try:
        graph_data = get_graph_data(
            case_id, settings.cases_dir)
        summary = get_entity_summary(
            case_id, settings.cases_dir)

        return {
            "graph": graph_data,
            "summary": summary,
            "total_nodes": len(
                graph_data["nodes"]),
            "total_edges": len(
                graph_data["edges"])
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve graph data",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/entities/{entity_id}
# ---------------------------------------------------------------------------

@router.get("/{entity_id}", response_model=schemas.EntityResponse)
def get_entity(
    case_id: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_viewer),
):
    """Return a single entity."""
    try:
        db_entity = (
            db.query(models.Entity)
            .filter(
                models.Entity.id == entity_id,
                models.Entity.case_id == case_id,
            )
            .first()
        )
        if not db_entity:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Entity not found",
                    detail=f"No entity with id={entity_id} in case {case_id}",
                ).model_dump(),
            )
        return _parse_entity(db_entity)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to retrieve entity",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# GET /api/cases/{case_id}/entities/{entity_id}/profile
# ---------------------------------------------------------------------------

@router.get("/{entity_id}/profile")
def get_entity_profile(
    case_id: str,
    entity_id: str,
    current_user = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Retrieves the most recently saved profile for an entity.
    Returns has_profile: False if no profile exists.
    """
    entity = db.query(
        models.Entity
    ).filter(
        models.Entity.id == entity_id,
        models.Entity.case_id == case_id
    ).first()
    if not entity:
        raise HTTPException(
            status_code=404,
            detail="Entity not found")

    # Profiles are saved as QueryLog entries with question_text
    # starting with [PROFILE] {entity_name}
    profile_log = db.query(
        models.QueryLog
    ).filter(
        models.QueryLog.case_id == case_id,
        models.QueryLog.question_text.startswith(
            f"[PROFILE] {entity.name}")
    ).order_by(
        models.QueryLog.asked_at.desc()
    ).first()

    if not profile_log:
        return {
            "has_profile": False,
            "entity_id": entity_id,
            "entity_name": entity.name,
            "entity_type": entity.entity_type
        }

    return {
        "has_profile": True,
        "entity_id": entity_id,
        "entity_name": entity.name,
        "entity_type": entity.entity_type,
        "frequency": entity.frequency,
        "aliases": json.loads(entity.aliases or '[]'),
        "profile": profile_log.processed_response,
        "graph_context": profile_log.graph_context,
        "related_artifact_count": 0,
        "cited_sentence_count": profile_log.cited_sentence_count,
        "generated_at": str(profile_log.asked_at),
        "generated_by": profile_log.asked_by
    }


# ---------------------------------------------------------------------------
# POST /api/cases/{case_id}/entities/{entity_id}/profile
# ---------------------------------------------------------------------------

@router.post("/{entity_id}/profile")
def generate_entity_profile(
    case_id: str,
    entity_id: str,
    body: dict = {},
    current_user: models.User = Depends(require_analyst),
    db: Session = Depends(get_db)
):
    """
    Generates a comprehensive AI profile for an entity (person, org, IP, etc.)
    by aggregating all evidence about them via a dedicated profile prompt.
    Does NOT reuse run_rag_query — uses a forensic-specific system prompt
    that small models like llama3.2:3b will not refuse.
    """
    from backend.modules.ollama_client import (
        generate_response, ollama_diagnostic)
    from backend.modules.vector_store import search_chunks, case_qdrant_path
    from backend.modules.graph_builder import (
        load_graph, get_graph_context)
    from backend.dependencies import get_settings
    import time

    settings = get_settings()

    PROFILE_SYSTEM_PROMPT = """You are a forensic analyst. You have been given \
evidence excerpts about a specific entity. \
Your task is to write a structured forensic profile based ONLY on these excerpts.

INSTRUCTIONS:
1. Write a profile with these sections:
   - Overview (who/what this entity is)
   - Known Associates (people mentioned alongside them)
   - Locations Connected
   - Organizations Connected
   - IP Addresses / Technical Indicators
   - Timeline of Activity (dates mentioned)
   - Key Findings
2. Only include sections where evidence exists. Skip empty sections.
3. After each factual claim, add: [Source: filename]
4. If evidence is thin, say so honestly in the Overview section.
5. You are summarizing the evidence provided to you. This is your job. \
Do NOT refuse to analyze.
6. Write in professional forensic report style."""

    # Get the entity
    entity = db.query(
        models.Entity
    ).filter(
        models.Entity.id == entity_id,
        models.Entity.case_id == case_id
    ).first()
    if not entity:
        raise HTTPException(
            status_code=404,
            detail="Entity not found"
        )

    entity_name = entity.name

    # Get graph relationships
    graph_context = get_graph_context(
        entity_name, case_id,
        settings.cases_dir
    )

    # Get all artifacts mentioning this entity name
    related_artifacts = db.query(
        models.ForensicArtifact
    ).filter(
        models.ForensicArtifact.case_id == case_id,
        models.ForensicArtifact.extracted_text.contains(entity_name)
    ).limit(20).all()

    artifact_context = ""
    if related_artifacts:
        lines = [f"\nArtifacts mentioning {entity_name}:"]
        for a in related_artifacts:
            lines.append(
                f"- File: {a.internal_path} "
                f"(Modified: {a.modified_at})"
            )
        artifact_context = '\n'.join(lines)

    # Step 1: Retrieve relevant chunks from vector store
    qdrant_path = case_qdrant_path(case_id)
    start_time = time.time()

    chunks = search_chunks(
        query=entity_name,
        case_id=case_id,
        qdrant_path=qdrant_path,
        top_k=10
    )

    if not chunks:
        # Try broader search
        chunks = search_chunks(
            query=f"mentions of {entity_name}",
            case_id=case_id,
            qdrant_path=qdrant_path,
            top_k=7
        )

    # Step 2: Build evidence context
    if chunks:
        evidence_lines = [
            f"Evidence about '{entity_name}':",
            f"Entity type: {entity.entity_type}",
            f"Mentioned {entity.frequency} time(s)",
            ""
        ]
        for i, chunk in enumerate(chunks, 1):
            evidence_lines.append(f"[Evidence {i}]")
            evidence_lines.append(
                f"Source: {chunk['source']} "
                f"(Relevance: {chunk['score']})"
            )
            evidence_lines.append(chunk['text'])
            evidence_lines.append("")
        evidence_context = '\n'.join(evidence_lines)
    else:
        evidence_context = (
            f"Entity: {entity_name}\n"
            f"Type: {entity.entity_type}\n"
            f"Frequency: {entity.frequency}\n"
            f"Note: No indexed text chunks found for this entity. "
            f"Profile will be based on graph relationships only."
        )

    # Step 3: Build the full prompt
    graph_context_str = graph_context or ""
    full_prompt = (
        f"{evidence_context}\n\n"
        f"{graph_context_str}\n\n"
        f"{artifact_context}\n\n"
        f"TASK: Write a structured forensic profile for "
        f"'{entity_name}' ({entity.entity_type}) based on the "
        f"evidence above. Use the section format described in "
        f"your instructions. Cite sources inline."
    )

    # Step 4: Generate with Ollama
    #
    # Gated on a model existing, not merely on the daemon answering:
    # /api/tags answers 200 with an empty model list on a machine that never
    # pulled one, so the old check passed and the "profile" persisted was the
    # model's own error text.
    diag = ollama_diagnostic()
    if not (diag["running"] and diag["model_ready"]):
        profile_text = (
            f"## Offline Profile — Ollama Not Running\n\n"
            f"**Entity:** {entity_name}\n"
            f"**Type:** {entity.entity_type}\n"
            f"**Frequency:** {entity.frequency} mention(s)\n\n"
            f"**Graph Relationships:**\n"
            f"{graph_context or 'None found'}\n\n"
            f"*{diag['reason'] or 'Ollama is not ready to answer.'} "
            f"Start Ollama to generate a full AI profile.*"
        )
        cited_count = 0
        uncited_count = 0
    else:
        raw_response = generate_response(
            prompt=full_prompt,
            system_prompt=PROFILE_SYSTEM_PROMPT
        )

        # Detect and handle model refusals with a simpler fallback
        refusal_phrases = [
            "I can't provide",
            "I cannot provide",
            "I'm not able to",
            "strictly prohibited",
            "requires using my training",
            "as an AI"
        ]
        profile_text = raw_response
        for phrase in refusal_phrases:
            if phrase.lower() in profile_text.lower():
                fallback_prompt = (
                    f"Summarize what is known about '{entity_name}' "
                    f"from this evidence:\n\n{evidence_context}\n\n"
                    f"Write bullet points for each fact found. "
                    f"Add [Source: filename] after each point."
                )
                profile_text = generate_response(
                    prompt=fallback_prompt,
                    system_prompt=(
                        "Summarize the evidence provided. "
                        "Do not refuse. Cite sources."
                    )
                )
                break

        cited_count = profile_text.count('[Source:')
        uncited_count = max(
            0, profile_text.count('. ') - cited_count)

    elapsed_ms = int((time.time() - start_time) * 1000)

    # Get aliases from entity record
    aliases = json.loads(entity.aliases or '[]')

    # Save as a QueryLog entry for persistence and audit trail
    profile_query_log = models.QueryLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        asked_by=current_user.username,
        question_text=f"[PROFILE] {entity_name}",
        processed_response=profile_text,
        raw_llm_response=profile_text,
        graph_context=graph_context,
        model_used="llama3.2:3b",
        cited_sentence_count=cited_count,
        uncited_sentence_count=uncited_count,
        response_time_ms=elapsed_ms,
        is_flagged=True
    )
    db.add(profile_query_log)

    # Log to audit
    db.add(models.AuditLog(
        id=str(uuid.uuid4()),
        case_id=case_id,
        action_type="PROFILE_GENERATED",
        performed_by=current_user.username,
        details=json.dumps({
            "entity_name": entity_name,
            "entity_type": entity.entity_type,
            "entity_id": entity_id,
            "chunks_used": len(chunks),
            "ollama_available": diag["running"]
        })
    ))
    db.commit()

    return {
        "entity_id": entity_id,
        "entity_name": entity_name,
        "entity_type": entity.entity_type,
        "frequency": entity.frequency,
        "aliases": aliases,
        "profile": profile_text,
        "graph_context": graph_context,
        "related_artifact_count": len(related_artifacts),
        "cited_sentence_count": cited_count,
        "uncited_sentence_count": uncited_count,
        "response_time_ms": elapsed_ms,
        "ollama_available": diag["running"],
        "chunks_used": len(chunks),
        "generated_at": str(profile_query_log.asked_at),
        "generated_by": current_user.username,
        "is_flagged_for_review": True
    }


# ---------------------------------------------------------------------------
# PATCH /api/cases/{case_id}/entities/{entity_id}
# ---------------------------------------------------------------------------


@router.patch("/{entity_id}", response_model=schemas.EntityResponse)
def update_entity(
    case_id: str,
    entity_id: str,
    body: dict,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """
    Update notes and/or is_flagged on an entity.
    Both fields are optional. Accepts {notes: str, is_flagged: bool}.
    """
    try:
        db_entity = (
            db.query(models.Entity)
            .filter(
                models.Entity.id == entity_id,
                models.Entity.case_id == case_id,
            )
            .first()
        )
        if not db_entity:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Entity not found",
                    detail=f"No entity with id={entity_id} in case {case_id}",
                ).model_dump(),
            )

        if "notes" in body:
            db_entity.notes = body["notes"]
        if "is_flagged" in body:
            db_entity.is_flagged = body["is_flagged"]

        db.commit()
        db.refresh(db_entity)
        return _parse_entity(db_entity)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to update entity",
                detail=str(exc),
            ).model_dump(),
        )


# ---------------------------------------------------------------------------
# PATCH /api/cases/{case_id}/entities/{entity_id}/flag
# ---------------------------------------------------------------------------

@router.patch("/{entity_id}/flag", response_model=schemas.EntityResponse)
def flag_entity(
    case_id: str,
    entity_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(require_analyst),
):
    """Toggle the is_flagged boolean for an entity."""
    try:
        db_entity = (
            db.query(models.Entity)
            .filter(
                models.Entity.id == entity_id,
                models.Entity.case_id == case_id,
            )
            .first()
        )
        if not db_entity:
            raise HTTPException(
                status_code=404,
                detail=schemas.ErrorResponse(
                    error="Entity not found",
                    detail=f"No entity with id={entity_id} in case {case_id}",
                ).model_dump(),
            )

        db_entity.is_flagged = not db_entity.is_flagged
        db.commit()
        db.refresh(db_entity)

        _create_audit(
            db=db,
            action_type="ENTITY_FLAGGED",
            performed_by=current_user.username,
            details={
                "entity_id": entity_id,
                "entity_name": db_entity.name,
                "is_flagged": db_entity.is_flagged,
            },
            case_id=case_id,
        )

        return _parse_entity(db_entity)
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail=schemas.ErrorResponse(
                error="Failed to flag entity",
                detail=str(exc),
            ).model_dump(),
        )

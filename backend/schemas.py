from datetime import datetime
from typing import Optional
import json

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Case Schemas
# ---------------------------------------------------------------------------

class CaseCreate(BaseModel):
    case_name: str
    case_number: Optional[str] = None
    priority: str = "Medium"
    description: Optional[str] = None
    # Accepted for backward compatibility and IGNORED - see the note on
    # QueryCreate.asked_by. The case's creator is the authenticated user.
    created_by: Optional[str] = None
    tags: list[str] = []


class CaseUpdate(BaseModel):
    case_name: Optional[str] = None
    status: Optional[str] = None
    priority: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None


class CaseResponse(BaseModel):
    id: str
    case_name: str
    case_number: Optional[str]
    status: str
    priority: str
    description: Optional[str]
    created_by: str
    created_at: datetime
    updated_at: datetime
    tags: list[str]
    evidence_count: int = 0
    query_count: int = 0

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Evidence Schemas
# ---------------------------------------------------------------------------

class EvidenceResponse(BaseModel):
    id: str
    case_id: str
    filename: str
    original_filename: str
    file_type: str
    file_size_bytes: int
    sha256_hash: Optional[str]
    ingested_at: datetime
    ingested_by: str
    status: str
    chunk_count: int
    entity_count: int
    notes: Optional[str]
    error_message: Optional[str]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# QueryLog Schemas
# ---------------------------------------------------------------------------

# How many conversation exchanges a client may submit. The RAG engine only
# renders the last few and caps each field, so this is a denial-of-service
# guard on the request body, not a behaviour change (finding C6).
MAX_CONVERSATION_HISTORY = 50


class QueryCreate(BaseModel):
    question_text: str
    # Accepted for backward compatibility and IGNORED. The server records
    # the authenticated user, so nothing sent here can change who a query
    # is attributed to. It was previously REQUIRED, which meant every
    # client had to assert an identity that was then written verbatim into
    # both the query record and the audit log - a caller-chosen author on
    # a forensic record. A field that is ignored should not be mandatory.
    asked_by: Optional[str] = None
    evidence_id: Optional[str] = None
    # Bounded on purpose (finding C6). This list is client-supplied, is
    # rendered into the model's prompt as PROTECTED text ahead of the
    # evidence, and was previously unbounded -- so a caller could crowd the
    # evidence out of the context window with history alone. Non-dict entries
    # are dropped rather than crashing the prompt builder, and the list is
    # truncated to the most recent MAX_CONVERSATION_HISTORY exchanges.
    conversation_history: list = Field(default_factory=list)

    @field_validator("conversation_history", mode="before")
    @classmethod
    def _bounded_history(cls, value):
        if not isinstance(value, list):
            return []
        entries = [e for e in value if isinstance(e, dict)]
        return entries[-MAX_CONVERSATION_HISTORY:]


class QueryResponse(BaseModel):
    id: str
    case_id: str
    evidence_id: Optional[str]
    asked_by: str
    asked_at: datetime
    question_text: str
    processed_response: Optional[str]
    model_used: str
    # MISNOMER, kept for stored-record compatibility. This counts distinct
    # evidence FILES the answer drew on, not sentences, and nothing in the
    # pipeline emits a per-sentence source marker to count. It previously
    # rendered in the UI as "N of N sentences cited" -- which is always 100%
    # -- with a tooltip claiming it showed whether the model asserted more
    # than the evidence supports. That is a measurement-shaped field carrying
    # no measurement, so the UI now says "N sources".
    cited_sentence_count: int
    # ALWAYS 0. Not a measurement. Per-sentence citation marking was removed,
    # and the field was left behind still named like a count. Do not render it
    # and do not compute a ratio with it.
    uncited_sentence_count: int
    response_time_ms: int
    is_flagged: bool
    # The stored JSON array of excerpt references the answer was built from,
    # returned so a claim can be traced to the passages behind it (finding C3).
    # The column is a JSON TEXT field; it is parsed here. A missing, null,
    # empty or malformed value is None -- "not returnable" -- NEVER [], which
    # would assert the answer was built from no excerpts at all.
    chunks_used: Optional[list] = None

    @field_validator("chunks_used", mode="before")
    @classmethod
    def _parse_chunks_used(cls, value):
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                return None
            return parsed if isinstance(parsed, list) else None
        return None

    model_config = ConfigDict(
        from_attributes=True,
        protected_namespaces=(),  # suppress model_ namespace warning for model_used
    )


# ---------------------------------------------------------------------------
# Entity Schemas
# ---------------------------------------------------------------------------

class EntityResponse(BaseModel):
    id: str
    case_id: str
    name: str
    entity_type: str
    frequency: int
    aliases: list[str]
    is_flagged: bool
    notes: Optional[str]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Note Schemas
# ---------------------------------------------------------------------------

class NoteCreate(BaseModel):
    linked_to_type: Optional[str] = None
    linked_to_id: Optional[str] = None
    # Accepted for backward compatibility and IGNORED - see the note on
    # QueryCreate.asked_by. A note's author is the authenticated user.
    author: Optional[str] = None
    content: str


class NoteResponse(BaseModel):
    id: str
    case_id: str
    linked_to_type: Optional[str]
    linked_to_id: Optional[str]
    author: str
    created_at: datetime
    updated_at: datetime
    content: str
    is_flagged: bool

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# AuditLog Schemas
# ---------------------------------------------------------------------------

class AuditLogResponse(BaseModel):
    id: str
    case_id: Optional[str]
    action_type: str
    performed_by: str
    performed_at: datetime
    details: dict
    machine_id: Optional[str]

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Report Schemas
# ---------------------------------------------------------------------------

class ReportCreate(BaseModel):
    report_type: str
    # Accepted for backward compatibility and IGNORED — see the note on
    # QueryCreate.asked_by. The report's author is the authenticated user.
    generated_by: Optional[str] = None
    query_ids_included: list[str] = []


class ReportResponse(BaseModel):
    id: str
    case_id: str
    generated_at: datetime
    generated_by: str
    report_type: str
    file_path: Optional[str]
    sha256_hash: Optional[str]
    page_count: int
    status: str

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Generic Response Schemas
# ---------------------------------------------------------------------------

class SuccessResponse(BaseModel):
    success: bool = True
    message: str


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    detail: Optional[str] = None


# ---------------------------------------------------------------------------
# User Preference Schemas
# ---------------------------------------------------------------------------

class UserPreferenceUpdate(BaseModel):
    theme: Optional[str] = None
    timezone: Optional[str] = None
    api_keys: Optional[dict] = None
    show_system_resources: Optional[bool] = None

class UserPreferenceResponse(BaseModel):
    theme: str
    timezone: str
    api_keys: dict
    show_system_resources: bool = True

    model_config = ConfigDict(from_attributes=True)

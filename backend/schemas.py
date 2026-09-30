from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


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
    conversation_history: list = []


class QueryResponse(BaseModel):
    id: str
    case_id: str
    evidence_id: Optional[str]
    asked_by: str
    asked_at: datetime
    question_text: str
    processed_response: Optional[str]
    model_used: str
    cited_sentence_count: int
    uncited_sentence_count: int
    response_time_ms: int
    is_flagged: bool

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

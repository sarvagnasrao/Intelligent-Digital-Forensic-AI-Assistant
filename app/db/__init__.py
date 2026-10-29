"""Database models package - imports all models for Alembic."""
from __future__ import annotations

from app.db.base import Base

# Models are imported lazily to avoid circular imports
# Call load_all_models() to register all models with Base.metadata

def load_all_models() -> None:
    """Import all models to register with Base.metadata."""
    # Import order matters - auth first (User, Case), then others
    from app.auth.models import Case, User, UserRole  # noqa: F401
    from app.evidence.models import CustodyEvent, Evidence, EvidenceHash, EvidenceStatus, EvidenceType, HashAlgorithm  # noqa: F401
    from app.examination.models import ExaminationJob, ExaminationOperation, ExaminationResult, JobStatus  # noqa: F401
    from app.artifacts.models import (  # noqa: F401
        Artifact,
        ArtifactChunk,
        ArtifactType,
        Entity,
        EntityType,
        IndexStatus,
        TimelineEvent,
    )
    from app.analysis.models import (  # noqa: F401
        AnalysisJob,
        AnalysisJobStatus,
        EntityRelationship,
        RelationshipKind,
        RelationshipStatus,
    )
    from app.findings.models import Finding, FindingArtifactLink, FindingOrigin, FindingStatus  # noqa: F401
    from app.reports.models import Report, ReportFormat, ReportStatus  # noqa: F401
    from app.audit.models import AuditEvent  # noqa: F401
    from app.ai.models import AIChatMessage  # noqa: F401

__all__ = [
    "Base",
    "User",
    "UserRole",
    "Case",
    "Evidence",
    "EvidenceType",
    "EvidenceStatus",
    "EvidenceHash",
    "HashAlgorithm",
    "CustodyEvent",
    "ExaminationJob",
    "ExaminationOperation",
    "ExaminationResult",
    "JobStatus",
    "Artifact",
    "ArtifactChunk",
    "ArtifactType",
    "IndexStatus",
    "Entity",
    "EntityType",
    "TimelineEvent",
    "AnalysisJob",
    "AnalysisJobStatus",
    "EntityRelationship",
    "RelationshipKind",
    "RelationshipStatus",
    "Finding",
    "FindingStatus",
    "FindingOrigin",
    "FindingArtifactLink",
    "Report",
    "ReportStatus",
    "ReportFormat",
    "AuditEvent",
    "AIChatMessage",
    "load_all_models",
]

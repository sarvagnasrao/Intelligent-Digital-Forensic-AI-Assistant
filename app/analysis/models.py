"""Models for background entity extraction and relationship analysis.

The analysis runs after examination, one job per examination job, so a job is
never queued twice for the same artifacts. Relationships are case-level and are
rebuilt from the entities each time, which keeps them consistent when an
evidence item is removed or re-examined.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.auth.models import Case
    from app.evidence.models import Evidence
    from app.examination.models import ExaminationJob


class AnalysisJobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class RelationshipKind(str, enum.Enum):
    # Two entities that appear in the same artifact(s).
    SHARED_ENTITY = "shared_entity"
    # Two artifacts that mention at least one of the same identifiers.
    RELATED_ARTIFACTS = "related_artifacts"
    # The same bytes found under two different paths or evidence items.
    DUPLICATE_CONTENT = "duplicate_content"


class RelationshipStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class AnalysisJob(Base):
    """One background analysis run for one evidence item."""

    __tablename__ = "analysis_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    evidence_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # One analysis per examination: re-examining creates a new examination job,
    # which is exactly when the artifact set changed and analysis is due again.
    examination_job_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("examination_jobs.id", ondelete="CASCADE"),
        nullable=True,
        unique=True,
    )

    status: Mapped[AnalysisJobStatus] = mapped_column(
        Enum(AnalysisJobStatus), default=AnalysisJobStatus.PENDING, nullable=False, index=True
    )
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    artifact_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entity_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    relationship_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    llm_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    case: Mapped["Case"] = relationship("Case")
    evidence: Mapped["Evidence"] = relationship("Evidence")
    examination_job: Mapped["ExaminationJob"] = relationship("ExaminationJob")

    __table_args__ = (
        Index("ix_analysis_case_status", "case_id", "status"),
        Index("ix_analysis_evidence", "evidence_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<AnalysisJob(id={self.id}, job_id={self.job_id}, "
            f"status={self.status.value})>"
        )


class EntityRelationship(Base):
    """A link between two entity values, with the evidence that supports it.

    Nothing is asserted without support: ``artifact_ids_json`` lists every
    artifact where both values occur, and the UI shows that list next to the
    confirm/reject buttons.
    """

    __tablename__ = "entity_relationships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    kind: Mapped[RelationshipKind] = mapped_column(
        Enum(RelationshipKind), default=RelationshipKind.SHARED_ENTITY, nullable=False
    )
    left_type: Mapped[str] = mapped_column(String(32), nullable=False)
    left_value: Mapped[str] = mapped_column(String(512), nullable=False)
    right_type: Mapped[str] = mapped_column(String(32), nullable=False)
    right_value: Mapped[str] = mapped_column(String(512), nullable=False)

    score: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    shared_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    artifact_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[RelationshipStatus] = mapped_column(
        Enum(RelationshipStatus), default=RelationshipStatus.PENDING, nullable=False, index=True
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    built_by_job_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "case_id", "kind",
            "left_type", "left_value", "right_type", "right_value",
            name="uq_relationship_case_pair",
        ),
        Index("ix_relationship_case_score", "case_id", "score"),
        Index("ix_relationship_case_status", "case_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<EntityRelationship({self.left_value!r} <-> {self.right_value!r}, "
            f"shared={self.shared_count})>"
        )

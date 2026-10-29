"""Database models for findings and verification."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.auth.models import Case, User
    from app.artifacts.models import Artifact


class FindingStatus(str, enum.Enum):
    DRAFT = "draft"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


class FindingOrigin(str, enum.Enum):
    INVESTIGATOR = "investigator"
    AI_SUGGESTED = "ai_suggested"


class Finding(Base):
    """Investigator finding with verification workflow."""
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    conclusion: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[FindingStatus] = mapped_column(Enum(FindingStatus), default=FindingStatus.DRAFT, nullable=False, index=True)
    origin: Mapped[FindingOrigin] = mapped_column(Enum(FindingOrigin), default=FindingOrigin.INVESTIGATOR, nullable=False)

    # AI-specific fields
    ai_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_citations_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of artifact IDs
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ai_confidence: Mapped[float | None] = mapped_column(nullable=True)

    # Verification
    verified_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="findings")
    created_by: Mapped["User"] = relationship("User", foreign_keys=[created_by_id])
    verified_by: Mapped["User | None"] = relationship("User", foreign_keys=[verified_by_id])
    artifact_links: Mapped[list["FindingArtifactLink"]] = relationship("FindingArtifactLink", back_populates="finding", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("case_id", "finding_id", name="uq_finding_case_finding_id"),
        Index("ix_finding_case_status", "case_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Finding(id={self.id}, finding_id={self.finding_id}, status={self.status.value})>"


class FindingArtifactLink(Base):
    """Link between finding and supporting artifacts."""
    __tablename__ = "finding_artifact_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    finding_id: Mapped[int] = mapped_column(Integer, ForeignKey("findings.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id: Mapped[int] = mapped_column(Integer, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True)

    relevance: Mapped[str] = mapped_column(String(32), default="supports", nullable=False)  # supports, contradicts, contextual
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    cited_in_ai: Mapped[bool] = mapped_column(default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    finding: Mapped["Finding"] = relationship("Finding", back_populates="artifact_links")
    artifact: Mapped["Artifact"] = relationship("Artifact", back_populates="finding_links")

    __table_args__ = (
        UniqueConstraint("finding_id", "artifact_id", name="uq_finding_artifact_link"),
    )

    def __repr__(self) -> str:
        return f"<FindingArtifactLink(finding_id={self.finding_id}, artifact_id={self.artifact_id})>"

"""Database models for audit trail and chain of custody."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.auth.models import Case, User


class AuditEvent(Base):
    """Append-only audit log for all significant actions."""
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    case_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("cases.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # login, logout, case_create, evidence_register, examine, search, ai_query, finding_create, report_generate, export
    action: Mapped[str] = mapped_column(String(128), nullable=False)  # Specific action description
    result: Mapped[str] = mapped_column(String(16), nullable=False)  # success, failure, partial

    # Target entity
    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)  # case, evidence, artifact, finding, report
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Request/response metadata
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(256), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Details
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON with additional context
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

    # Relationships
    case: Mapped["Case | None"] = relationship("Case", back_populates="audit_events")
    user: Mapped["User | None"] = relationship("User", back_populates="audit_events")

    __table_args__ = (
        Index("ix_audit_case_time", "case_id", "timestamp"),
        Index("ix_audit_user_time", "user_id", "timestamp"),
        Index("ix_audit_type_time", "event_type", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<AuditEvent(id={self.id}, type={self.event_type}, action={self.action}, result={self.result})>"

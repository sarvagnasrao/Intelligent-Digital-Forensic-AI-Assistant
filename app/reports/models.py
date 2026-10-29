"""Database models for reports."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.auth.models import Case, User


class ReportStatus(str, enum.Enum):
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


class ReportFormat(str, enum.Enum):
    PDF = "pdf"
    HTML = "html"
    JSON = "json"


class Report(Base):
    """Generated report for a case."""
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    report_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)

    title: Mapped[str] = mapped_column(String(256), nullable=False)
    format: Mapped[ReportFormat] = mapped_column(Enum(ReportFormat), default=ReportFormat.PDF, nullable=False)
    status: Mapped[ReportStatus] = mapped_column(Enum(ReportStatus), default=ReportStatus.GENERATING, nullable=False, index=True)

    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content summary
    included_sections_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of sections
    finding_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of finding IDs included
    artifact_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON array of artifact IDs included

    generated_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="reports")
    generated_by: Mapped["User"] = relationship("User")

    __table_args__ = (
        UniqueConstraint("case_id", "report_id", name="uq_report_case_report_id"),
        Index("ix_report_case_status", "case_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Report(id={self.id}, report_id={self.report_id}, format={self.format.value}, status={self.status.value})>"

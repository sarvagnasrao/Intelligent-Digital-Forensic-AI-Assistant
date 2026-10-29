"""Database models for examination jobs and results."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.auth.models import Case, User
    from app.evidence.models import Evidence


class ExaminationOperation(str, enum.Enum):
    PARTITION_ANALYSIS = "partition_analysis"
    FILESYSTEM_DETECTION = "filesystem_detection"
    FILE_TRAVERSAL = "file_traversal"
    FILE_EXTRACTION = "file_extraction"
    DELETED_RECOVERY = "deleted_recovery"
    METADATA_EXTRACTION = "metadata_extraction"
    FULL_EXAMINATION = "full_examination"


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    # A job that was running when the application exited. It is not failed:
    # nothing is known about how far the worker got, and the investigator can
    # simply start it again.
    INTERRUPTED = "interrupted"


class ExaminationJob(Base):
    """Examination job tracking."""
    __tablename__ = "examination_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id: Mapped[int] = mapped_column(Integer, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True)

    operation: Mapped[ExaminationOperation] = mapped_column(Enum(ExaminationOperation), nullable=False)
    parameters_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON config

    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False, index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    progress_message: Mapped[str | None] = mapped_column(String(512), nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    worker_pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="examinations")
    evidence: Mapped["Evidence"] = relationship("Evidence", back_populates="examinations")
    created_by: Mapped["User"] = relationship("User")
    results: Mapped[list["ExaminationResult"]] = relationship("ExaminationResult", back_populates="job", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_exam_job_case_status", "case_id", "status"),
        Index("ix_exam_job_evidence_status", "evidence_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<ExaminationJob(id={self.id}, job_id={self.job_id}, op={self.operation.value}, status={self.status.value})>"


class ExaminationResult(Base):
    """Results from an examination job."""
    __tablename__ = "examination_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("examination_jobs.id", ondelete="CASCADE"), nullable=False, index=True)

    result_type: Mapped[str] = mapped_column(String(64), nullable=False)  # partition, filesystem, file_list, extracted_files, metadata
    content_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON serialized result
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    job: Mapped["ExaminationJob"] = relationship("ExaminationJob", back_populates="results")

    __table_args__ = (
        Index("ix_exam_result_job_type", "job_id", "result_type"),
    )

    def __repr__(self) -> str:
        return f"<ExaminationResult(id={self.id}, job_id={self.job_id}, type={self.result_type})>"

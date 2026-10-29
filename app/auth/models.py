"""Database models for authentication and users."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.cases.models import Case


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    INVESTIGATOR = "investigator"
    READ_ONLY = "read_only"


class User(Base):
    """User account with role-based access control."""
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(256), nullable=False)
    full_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.INVESTIGATOR, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    assigned_cases: Mapped[list["Case"]] = relationship("Case", back_populates="assignee", foreign_keys="Case.assignee_id")
    created_cases: Mapped[list["Case"]] = relationship("Case", back_populates="creator", foreign_keys="Case.created_by_id")
    audit_events: Mapped[list["AuditEvent"]] = relationship("AuditEvent", back_populates="user")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, username={self.username}, role={self.role.value})>"


class Case(Base):
    """Forensic case."""
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)  # Human-readable ID
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    objective: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="open", nullable=False, index=True)  # open, active, on_hold, closed
    priority: Mapped[str] = mapped_column(String(16), default="medium", nullable=False)  # low, medium, high, critical

    created_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    assignee_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cloud_ai_consent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cloud_ai_consent_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )

    # Relationships
    creator: Mapped["User"] = relationship("User", back_populates="created_cases", foreign_keys=[created_by_id])
    assignee: Mapped["User | None"] = relationship("User", back_populates="assigned_cases", foreign_keys=[assignee_id])
    evidence: Mapped[list["Evidence"]] = relationship("Evidence", back_populates="case", cascade="all, delete-orphan")
    examinations: Mapped[list["ExaminationJob"]] = relationship("ExaminationJob", back_populates="case", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship("Artifact", back_populates="case", cascade="all, delete-orphan")
    findings: Mapped[list["Finding"]] = relationship("Finding", back_populates="case", cascade="all, delete-orphan")
    reports: Mapped[list["Report"]] = relationship("Report", back_populates="case", cascade="all, delete-orphan")
    audit_events: Mapped[list["AuditEvent"]] = relationship("AuditEvent", back_populates="case", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("case_id", name="uq_cases_case_id"),
    )

    def __repr__(self) -> str:
        return f"<Case(id={self.id}, case_id={self.case_id}, title={self.title})>"

"""Database models for evidence and integrity."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.auth.models import Case, User


class EvidenceType(str, enum.Enum):
    ORIGINAL = "original"
    IMAGE = "image"
    DERIVED = "derived"
    EXTRACTED = "extracted"
    REPORT = "report"


class HashAlgorithm(str, enum.Enum):
    SHA256 = "sha256"
    MD5 = "md5"
    SHA1 = "sha1"


class EvidenceStatus(str, enum.Enum):
    REGISTERED = "registered"
    INTEGRITY_VERIFIED = "integrity_verified"
    INTEGRITY_FAILED = "integrity_failed"
    EXAMINED = "examined"
    EXAMINATION_FAILED = "examination_failed"
    INDEXED = "indexed"
    ARCHIVED = "archived"


class Evidence(Base):
    """Evidence item registered to a case."""
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # Human-readable ID per case
    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_type: Mapped[EvidenceType] = mapped_column(Enum(EvidenceType), default=EvidenceType.ORIGINAL, nullable=False)

    source_path: Mapped[str] = mapped_column(String(1024), nullable=False)  # Original acquisition path
    stored_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # Copied/stored path
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extension: Mapped[str | None] = mapped_column(String(16), nullable=True)

    status: Mapped[EvidenceStatus] = mapped_column(Enum(EvidenceStatus), default=EvidenceStatus.REGISTERED, nullable=False, index=True)

    registered_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Removal is a tombstone, deliberately separate from ``status``: an item can
    # be archived or failed and still be removed from the case, and the record
    # (with its hashes and custody events) is kept so the case history stays
    # truthful. Permanent deletion is a separate, guarded operation.
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    removed_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    removal_reason: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="evidence")
    registered_by: Mapped["User"] = relationship("User", foreign_keys=[registered_by_id])
    removed_by: Mapped["User | None"] = relationship("User", foreign_keys=[removed_by_id])
    hashes: Mapped[list["EvidenceHash"]] = relationship("EvidenceHash", back_populates="evidence", cascade="all, delete-orphan")
    custody_events: Mapped[list["CustodyEvent"]] = relationship("CustodyEvent", back_populates="evidence", cascade="all, delete-orphan")
    examinations: Mapped[list["ExaminationJob"]] = relationship("ExaminationJob", back_populates="evidence")

    __table_args__ = (
        UniqueConstraint("case_id", "evidence_id", name="uq_evidence_case_evidence_id"),
        Index("ix_evidence_case_status", "case_id", "status"),
    )

    def __repr__(self) -> str:
        return f"<Evidence(id={self.id}, evidence_id={self.evidence_id}, name={self.name})>"

    @property
    def is_removed(self) -> bool:
        """True when the item has been taken out of the case without deletion."""
        return self.removed_at is not None


class EvidenceHash(Base):
    """Cryptographic hash records for evidence integrity."""
    __tablename__ = "evidence_hashes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[int] = mapped_column(Integer, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True)

    algorithm: Mapped[HashAlgorithm] = mapped_column(Enum(HashAlgorithm), nullable=False)
    hash_value: Mapped[str] = mapped_column(String(128), nullable=False)  # Hex encoded
    is_reference: Mapped[bool] = mapped_column(default=False, nullable=False)  # True = original reference hash
    calculated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    calculated_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)

    # Verification fields
    verified_against_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("evidence_hashes.id"), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    match_result: Mapped[bool | None] = mapped_column(nullable=True)  # True = match, False = mismatch

    # Relationships
    evidence: Mapped["Evidence"] = relationship("Evidence", back_populates="hashes")
    calculated_by: Mapped["User"] = relationship("User", foreign_keys=[calculated_by_id])
    verified_against: Mapped["EvidenceHash | None"] = relationship("EvidenceHash", remote_side=[id])
    verified_by: Mapped["User | None"] = relationship("User", foreign_keys=[verified_by_id])

    __table_args__ = (
        UniqueConstraint("evidence_id", "algorithm", "is_reference", name="uq_evidence_hash_algo_ref"),
        Index("ix_evidence_hash_evidence_algo", "evidence_id", "algorithm"),
    )

    def __repr__(self) -> str:
        return f"<EvidenceHash(evidence_id={self.evidence_id}, algo={self.algorithm.value}, ref={self.is_reference})>"


class CustodyEvent(Base):
    """Chain of custody event log."""
    __tablename__ = "custody_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    evidence_id: Mapped[int] = mapped_column(Integer, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True)

    event_type: Mapped[str] = mapped_column(String(64), nullable=False)  # registered, verified, examined, extracted, copied, transferred, viewed
    description: Mapped[str] = mapped_column(Text, nullable=False)
    performed_by_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    performed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Context
    source_location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    destination_location: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tool_used: Mapped[str | None] = mapped_column(String(128), nullable=True)  # e.g., "pytsk3", "hashcalc", "manual"
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Additional JSON data

    # Relationships
    evidence: Mapped["Evidence"] = relationship("Evidence", back_populates="custody_events")
    performed_by: Mapped["User"] = relationship("User")

    __table_args__ = (
        Index("ix_custody_evidence_time", "evidence_id", "performed_at"),
    )

    def __repr__(self) -> str:
        return f"<CustodyEvent(id={self.id}, evidence_id={self.evidence_id}, type={self.event_type})>"

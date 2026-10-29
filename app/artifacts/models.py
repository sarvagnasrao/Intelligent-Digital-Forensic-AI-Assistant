"""Database models for artifacts and search indexing."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.auth.models import Case, User
    from app.evidence.models import Evidence


class ArtifactType(str, enum.Enum):
    FILE = "file"
    SMS = "sms"
    CALL_LOG = "call_log"
    CONTACT = "contact"
    EMAIL = "email"
    BROWSER_HISTORY = "browser_history"
    BROWSER_DOWNLOAD = "browser_download"
    CHAT_MESSAGE = "chat_message"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    DOCUMENT = "document"
    ARCHIVE = "archive"
    DATABASE = "database"
    REGISTRY = "registry"
    LOG_ENTRY = "log_entry"
    METADATA = "metadata"
    EXIF = "exif"
    OTHER = "other"


class IndexStatus(str, enum.Enum):
    NOT_INDEXED = "not_indexed"
    INDEXING = "indexing"
    INDEXED = "indexed"
    INDEX_FAILED = "index_failed"


class Artifact(Base):
    """Extracted artifact from evidence examination."""
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    evidence_id: Mapped[int] = mapped_column(Integer, ForeignKey("evidence.id", ondelete="CASCADE"), nullable=False, index=True)
    examination_job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("examination_jobs.id"), nullable=True, index=True)

    artifact_type: Mapped[ArtifactType] = mapped_column(Enum(ArtifactType), default=ArtifactType.OTHER, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source location within evidence
    source_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)  # Path within filesystem/image
    source_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Byte offset
    source_size: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Content
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)  # Extracted text content
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA256 of content
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    extension: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Timestamps from artifact
    created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    modified_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accessed_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Metadata
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # Additional type-specific metadata

    # Indexing
    index_status: Mapped[IndexStatus] = mapped_column(Enum(IndexStatus), default=IndexStatus.NOT_INDEXED, nullable=False, index=True)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # Qdrant point ID

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    # Relationships
    case: Mapped["Case"] = relationship("Case", back_populates="artifacts")
    evidence: Mapped["Evidence"] = relationship("Evidence")
    entities: Mapped[list["Entity"]] = relationship("Entity", back_populates="artifact", cascade="all, delete-orphan")
    chunks: Mapped[list["ArtifactChunk"]] = relationship("ArtifactChunk", back_populates="artifact", cascade="all, delete-orphan")
    timeline_events: Mapped[list["TimelineEvent"]] = relationship("TimelineEvent", back_populates="artifact", cascade="all, delete-orphan")
    finding_links: Mapped[list["FindingArtifactLink"]] = relationship("FindingArtifactLink", back_populates="artifact", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("case_id", "artifact_id", name="uq_artifact_case_artifact_id"),
        Index("ix_artifact_case_type", "case_id", "artifact_type"),
        Index("ix_artifact_case_index", "case_id", "index_status"),
    )

    def __repr__(self) -> str:
        return f"<Artifact(id={self.id}, artifact_id={self.artifact_id}, type={self.artifact_type.value})>"


# FTS5 Virtual Table for keyword search (created via raw SQL in migration)
# This is NOT a SQLAlchemy model - the virtual table is created by Alembic migration
# Use raw SQL to query: SELECT * FROM artifacts_fts WHERE content_text MATCH 'query'


class ArtifactChunk(Base):
    """One passage of an artifact, embedded as its own vector.

    Whole-file embeddings were truncated at 8,000 characters, so a long PDF or
    log could only ever return "this file", never the passage that matched.
    Chunks keep their own text and span, which is what makes a semantic result
    show a real excerpt and a position inside the file.
    """

    __tablename__ = "artifact_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    artifact_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    vector_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    artifact: Mapped["Artifact"] = relationship("Artifact", back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("artifact_id", "chunk_index", name="uq_chunk_artifact_index"),
        Index("ix_chunk_case", "case_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ArtifactChunk(artifact_id={self.artifact_id}, "
            f"index={self.chunk_index})>"
        )


class EntityType(str, enum.Enum):
    EMAIL = "email"
    IP_ADDRESS = "ip_address"
    USERNAME = "username"
    FILE_PATH = "file_path"
    URL = "url"
    PHONE = "phone"
    CRYPTO_ADDRESS = "crypto_address"
    TIMESTAMP = "timestamp"
    PERSON = "person"
    ORGANIZATION = "organization"
    LOCATION = "location"
    # Added with the analysis pipeline: hardware identifiers and digests are
    # extracted exactly, so they are useful without any model involvement.
    MAC_ADDRESS = "mac_address"
    HASH = "hash"
    DEVICE_ID = "device_id"
    OTHER = "other"


class Entity(Base):
    """Named entity extracted from artifacts."""
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id: Mapped[int] = mapped_column(Integer, ForeignKey("artifacts.id", ondelete="CASCADE"), nullable=False, index=True)

    entity_type: Mapped[EntityType] = mapped_column(Enum(EntityType), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    normalized_value: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)

    # Source span in artifact
    start_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    context_snippet: Mapped[str | None] = mapped_column(Text, nullable=True)

    confidence: Mapped[float] = mapped_column(default=1.0, nullable=False)
    extractor: Mapped[str] = mapped_column(String(64), nullable=False)  # spacy, regex, manual

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    artifact: Mapped["Artifact"] = relationship("Artifact", back_populates="entities")
    timeline_events: Mapped[list["TimelineEvent"]] = relationship("TimelineEvent", back_populates="entity", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("case_id", "entity_id", name="uq_entity_case_entity_id"),
        Index("ix_entity_case_type_value", "case_id", "entity_type", "value"),
    )

    def __repr__(self) -> str:
        return f"<Entity(id={self.id}, type={self.entity_type.value}, value={self.value})>"


class TimelineEvent(Base):
    """Timeline event from artifact or entity."""
    __tablename__ = "timeline_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    case_id: Mapped[int] = mapped_column(Integer, ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    artifact_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("artifacts.id", ondelete="SET NULL"), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("entities.id", ondelete="SET NULL"), nullable=True, index=True)

    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    timestamp_utc: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    certainty: Mapped[str] = mapped_column(String(16), default="high", nullable=False)  # high, medium, low

    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # file_created, message_sent, call_made, etc.
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(String(64), nullable=False)  # artifact, entity, manual
    metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    artifact: Mapped["Artifact | None"] = relationship("Artifact", back_populates="timeline_events")
    entity: Mapped["Entity | None"] = relationship("Entity", back_populates="timeline_events")

    __table_args__ = (
        UniqueConstraint("case_id", "event_id", name="uq_timeline_case_event_id"),
        Index("ix_timeline_case_time", "case_id", "timestamp"),
    )

    def __repr__(self) -> str:
        return f"<TimelineEvent(id={self.id}, time={self.timestamp}, type={self.event_type})>"

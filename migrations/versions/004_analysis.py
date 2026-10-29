"""Add background analysis: chunks, analysis jobs and relationships.

Revision ID: 004
Revises: 003

Three tables arrive together because they are one feature:

* ``artifact_chunks`` holds one passage per embedded vector, so a semantic hit
  can quote the sentence that matched instead of naming the whole file;
* ``analysis_jobs`` is the queue — one row per completed examination;
* ``entity_relationships`` is the case-level graph built from the entities,
  with the confirm/reject decision and the supporting artifact ids.

``entities.entity_type`` gained the ``mac_address``, ``hash`` and ``device_id``
values. Those need no DDL here: the column is a plain ``VARCHAR(32)`` (the enum
is enforced in Python), so existing databases accept the new values as soon as
the application knows about them.

Databases created by ``create_all`` get all three tables directly and are
stamped at head, which is why ``init_db`` does not run this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "artifact_chunks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("artifact_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("vector_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["artifact_id"], ["artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("artifact_id", "chunk_index", name="uq_chunk_artifact_index"),
    )
    op.create_index("ix_artifact_chunks_artifact_id", "artifact_chunks", ["artifact_id"])
    op.create_index("ix_artifact_chunks_case_id", "artifact_chunks", ["case_id"])
    op.create_index("ix_chunk_case", "artifact_chunks", ["case_id"])

    op.create_table(
        "analysis_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Integer(), nullable=False),
        sa.Column("examination_job_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("progress_percent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress_message", sa.String(length=512), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("entity_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("relationship_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parameters_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["examination_job_id"], ["examination_jobs.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id"),
        # One analysis per examination, so a completed scan is never queued twice.
        sa.UniqueConstraint("examination_job_id"),
    )
    op.create_index("ix_analysis_jobs_job_id", "analysis_jobs", ["job_id"])
    op.create_index("ix_analysis_jobs_case_id", "analysis_jobs", ["case_id"])
    op.create_index("ix_analysis_jobs_evidence_id", "analysis_jobs", ["evidence_id"])
    op.create_index("ix_analysis_jobs_status", "analysis_jobs", ["status"])
    op.create_index("ix_analysis_case_status", "analysis_jobs", ["case_id", "status"])
    op.create_index("ix_analysis_evidence", "analysis_jobs", ["evidence_id"])

    op.create_table(
        "entity_relationships",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("left_type", sa.String(length=32), nullable=False),
        sa.Column("left_value", sa.String(length=512), nullable=False),
        sa.Column("right_type", sa.String(length=32), nullable=False),
        sa.Column("right_value", sa.String(length=512), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("shared_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifact_ids_json", sa.Text(), nullable=True),
        sa.Column("evidence_ids_json", sa.Text(), nullable=True),
        sa.Column("details_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reviewed_by_id", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("built_by_job_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id",
            "kind",
            "left_type",
            "left_value",
            "right_type",
            "right_value",
            name="uq_relationship_case_pair",
        ),
    )
    op.create_index("ix_entity_relationships_case_id", "entity_relationships", ["case_id"])
    op.create_index("ix_entity_relationships_status", "entity_relationships", ["status"])
    op.create_index("ix_relationship_case_score", "entity_relationships", ["case_id", "score"])
    op.create_index("ix_relationship_case_status", "entity_relationships", ["case_id", "status"])


def downgrade() -> None:
    op.drop_table("entity_relationships")
    op.drop_table("analysis_jobs")
    op.drop_table("artifact_chunks")

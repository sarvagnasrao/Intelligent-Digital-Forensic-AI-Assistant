"""Add model indexes absent from the historical migration-built schema.

Revision ID: 006
Revises: 005

The application-created schema already has these indexes through SQLAlchemy
metadata. Migrations 001-005 predate that metadata and omitted several useful
lookups; this revision brings upgrade-created databases into parity without
changing data or replacing existing composite indexes.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEXES = (
    ("ix_artifacts_artifact_id", "artifacts", ("artifact_id",)),
    ("ix_artifacts_artifact_type", "artifacts", ("artifact_type",)),
    ("ix_artifacts_evidence_id", "artifacts", ("evidence_id",)),
    ("ix_artifacts_examination_job_id", "artifacts", ("examination_job_id",)),
    ("ix_artifacts_index_status", "artifacts", ("index_status",)),
    ("ix_audit_events_timestamp", "audit_events", ("timestamp",)),
    ("ix_entities_artifact_id", "entities", ("artifact_id",)),
    ("ix_entities_entity_id", "entities", ("entity_id",)),
    ("ix_entities_entity_type", "entities", ("entity_type",)),
    ("ix_entities_normalized_value", "entities", ("normalized_value",)),
    ("ix_entities_value", "entities", ("value",)),
    ("ix_evidence_case_status", "evidence", ("case_id", "status")),
    ("ix_evidence_evidence_id", "evidence", ("evidence_id",)),
    ("ix_examination_jobs_status", "examination_jobs", ("status",)),
    ("ix_finding_artifact_links_artifact_id", "finding_artifact_links", ("artifact_id",)),
    ("ix_finding_artifact_links_finding_id", "finding_artifact_links", ("finding_id",)),
    ("ix_findings_finding_id", "findings", ("finding_id",)),
    ("ix_findings_status", "findings", ("status",)),
    ("ix_reports_report_id", "reports", ("report_id",)),
    ("ix_reports_status", "reports", ("status",)),
    ("ix_timeline_events_artifact_id", "timeline_events", ("artifact_id",)),
    ("ix_timeline_events_entity_id", "timeline_events", ("entity_id",)),
    ("ix_timeline_events_event_id", "timeline_events", ("event_id",)),
    ("ix_timeline_events_event_type", "timeline_events", ("event_type",)),
    ("ix_timeline_events_timestamp", "timeline_events", ("timestamp",)),
)


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        op.create_index(name, table, list(columns), if_not_exists=True)


def downgrade() -> None:
    for name, table, _columns in reversed(_INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)

"""Keep forensic case data intact when the investigator archives a case.

Revision ID: 008
Revises: 007

The columns are nullable to preserve existing cases. `archived_by_id` stores
the administrator id without an SQLite FK, matching the existing startup
reconciliation path for optional columns; the audit event also captures actor
and case metadata transactionally.
"""

import sqlalchemy as sa
from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("archived_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("archive_reason", sa.String(512), nullable=True))
    op.create_index("ix_cases_archived_at", "cases", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_cases_archived_at", table_name="cases")
    with op.batch_alter_table("cases") as batch:
        batch.drop_column("archive_reason")
        batch.drop_column("archived_by_id")
        batch.drop_column("archived_at")

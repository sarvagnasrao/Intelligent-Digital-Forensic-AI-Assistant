"""Add the evidence removal tombstone.

Revision ID: 003
Revises: 002

An evidence record can now be removed from a case without being deleted: the
record, its hashes and its custody events stay in the database, and the three
columns below say who removed it and why. Permanent deletion remains a separate
guarded operation.

The application also reconciles these columns on startup (``init_db``), because
databases created by ``create_all`` are stamped at head and would otherwise
never receive them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.add_column(sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("removed_by_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("removal_reason", sa.String(length=512), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("evidence") as batch:
        batch.drop_column("removal_reason")
        batch.drop_column("removed_by_id")
        batch.drop_column("removed_at")

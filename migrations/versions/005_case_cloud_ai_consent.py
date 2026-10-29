"""Record explicit per-case consent for cloud AI evidence processing.

Revision ID: 005
Revises: 004
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.add_column(
            sa.Column("cloud_ai_consent_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("cloud_ai_consent_by_id", sa.Integer(), nullable=True)
        )
        batch.create_foreign_key(
            "fk_cases_cloud_ai_consent_by_id_users",
            "users",
            ["cloud_ai_consent_by_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("cases") as batch:
        batch.drop_constraint(
            "fk_cases_cloud_ai_consent_by_id_users", type_="foreignkey"
        )
        batch.drop_column("cloud_ai_consent_by_id")
        batch.drop_column("cloud_ai_consent_at")

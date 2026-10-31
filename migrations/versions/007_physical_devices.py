"""Add explicit investigator-entered physical devices.

Revision ID: 007
Revises: 006
"""

import sqlalchemy as sa
from alembic import op

revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "physical_devices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "case_id", sa.Integer(), sa.ForeignKey("cases.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("label", sa.String(256), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("serial_number", sa.String(256)),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )
    op.create_index("ix_physical_devices_case_id", "physical_devices", ["case_id"])
    op.create_table(
        "device_evidence_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "device_id",
            sa.Integer(),
            sa.ForeignKey("physical_devices.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "evidence_id",
            sa.Integer(),
            sa.ForeignKey("evidence.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("created_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.UniqueConstraint("device_id", "evidence_id", name="uq_device_evidence"),
    )
    op.create_index("ix_device_evidence_links_device_id", "device_evidence_links", ["device_id"])
    op.create_index(
        "ix_device_evidence_links_evidence_id", "device_evidence_links", ["evidence_id"]
    )


def downgrade():
    op.drop_table("device_evidence_links")
    op.drop_table("physical_devices")

"""Persist case-scoped AI assistant conversations.

Revision ID: 002
Revises: 001
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("mode", sa.String(length=24), nullable=False, server_default="analysis"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations_json", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ai_chat_messages_case_id", "ai_chat_messages", ["case_id"])
    op.create_index("ix_ai_chat_case_message", "ai_chat_messages", ["case_id", "id"])


def downgrade() -> None:
    op.drop_index("ix_ai_chat_case_message", table_name="ai_chat_messages")
    op.drop_index("ix_ai_chat_messages_case_id", table_name="ai_chat_messages")
    op.drop_table("ai_chat_messages")

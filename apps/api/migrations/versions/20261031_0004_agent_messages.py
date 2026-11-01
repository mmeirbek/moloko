"""Sprint 4: agent_messages (agent↔agent messages within a run).

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31 21:26:03.216908+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_messages",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("sender_agent_id", sa.Uuid(), nullable=False),
        sa.Column("receiver_agent_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("message_type", sa.String(length=32), nullable=False),
        sa.Column(
            "content",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.String(length=300), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["receiver_agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_messages_receiver_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sender_agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_messages_sender_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_messages_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_messages")),
    )
    op.create_index(
        "ix_agent_messages_receiver",
        "agent_messages",
        ["receiver_agent_id", "created_at"],
        unique=False,
    )
    op.create_index(op.f("ix_agent_messages_run_id"), "agent_messages", ["run_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_agent_messages_run_id"), table_name="agent_messages")
    op.drop_index("ix_agent_messages_receiver", table_name="agent_messages")
    op.drop_table("agent_messages")

"""Owner request: agents talk to each other directly (agent_ask / agent_tell).

* ``agents.contacts`` — who a persistent agent may contact ({} = everyone);
* ``tasks.requested_by_agent_id`` — the agent that asked for a "consult" task;
* ``agent_messages.read_at`` — when the receiver took a message in (inbox), plus an index
  on the sender for the agent page's correspondence tab.

Revision ID: 0015_agent_contacts
Revises: 0014a
Create Date: 2026-11-02 20:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_agent_contacts"
down_revision: str | Sequence[str] | None = "0014a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents",
        sa.Column(
            "contacts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column("tasks", sa.Column("requested_by_agent_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        op.f("fk_tasks_requested_by_agent_id_agents"),
        "tasks",
        "agents",
        ["requested_by_agent_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_tasks_requested_by_agent_id"), "tasks", ["requested_by_agent_id"], unique=False
    )
    op.add_column("agent_messages", sa.Column("read_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_agent_messages_sender",
        "agent_messages",
        ["sender_agent_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_agent_messages_sender", table_name="agent_messages")
    op.drop_column("agent_messages", "read_at")
    op.drop_index(op.f("ix_tasks_requested_by_agent_id"), table_name="tasks")
    op.drop_constraint(op.f("fk_tasks_requested_by_agent_id_agents"), "tasks", type_="foreignkey")
    op.drop_column("tasks", "requested_by_agent_id")
    op.drop_column("agents", "contacts")

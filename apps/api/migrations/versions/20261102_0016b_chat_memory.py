"""Owner request: chats never forget.

* ``conversations.summary*`` — a rolling summary of the messages that no longer fit into
  the model's context (made in the background after an answer, given to the model as data);
* ``messages.recalled_sources`` — which earlier chats / tasks / memories recall gave the
  model for an answer (shown under the answer).

Revision ID: 0016b_chat_memory
Revises: 0016a_work_memory
Create Date: 2026-11-02 22:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016b_chat_memory"
down_revision: str | Sequence[str] | None = "0016a_work_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("summary_upto_message_id", sa.Uuid(), nullable=True))
    op.add_column(
        "conversations",
        sa.Column("summary_upto_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_messages", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "conversations",
        sa.Column("summary_updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "messages",
        sa.Column("recalled_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("messages", "recalled_sources")
    op.drop_column("conversations", "summary_updated_at")
    op.drop_column("conversations", "summary_messages")
    op.drop_column("conversations", "summary_upto_at")
    op.drop_column("conversations", "summary_upto_message_id")
    op.drop_column("conversations", "summary")

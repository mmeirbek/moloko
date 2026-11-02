"""Owner request: agents remember and can search all work — search_chunks for work sources.

New source types (finished tasks, agent↔agent messages, chat messages) need a few more
columns on ``search_chunks``: the receiver of an agent message (``peer_agent_id``), the
run (``run_id``), when the work happened (``source_at``) and display fields (``meta``).

Revision ID: 0016a_work_memory
Revises: 0015_agent_contacts
Create Date: 2026-11-02 22:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016a_work_memory"
down_revision: str | Sequence[str] | None = "0015_agent_contacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("search_chunks", sa.Column("peer_agent_id", sa.Uuid(), nullable=True))
    op.add_column("search_chunks", sa.Column("run_id", sa.Uuid(), nullable=True))
    op.add_column(
        "search_chunks", sa.Column("source_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "search_chunks",
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("search_chunks", "meta")
    op.drop_column("search_chunks", "source_at")
    op.drop_column("search_chunks", "run_id")
    op.drop_column("search_chunks", "peer_agent_id")

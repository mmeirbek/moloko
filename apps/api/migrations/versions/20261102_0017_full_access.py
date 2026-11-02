"""Owner's decision: «Полный доступ» for chosen persistent agents.

* ``agents.full_access_since`` — since when the agent may use every enabled, available tool
  without approvals (NULL = off). Turned on only with the owner's password through
  ``PUT /agents/{id}/full-access``; audited as ``agent.full_access_granted`` / ``_revoked``.

Revision ID: 0017_full_access
Revises: 0016b_chat_memory
Create Date: 2026-11-02 23:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_full_access"
down_revision: str | Sequence[str] | None = "0016b_chat_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agents", sa.Column("full_access_since", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("agents", "full_access_since")

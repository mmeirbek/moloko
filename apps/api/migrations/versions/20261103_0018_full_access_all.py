"""Owner's decision: «Полный доступ всем агентам».

* ``users.full_access_all_since`` — since when every persistent agent of the office (and
  every one added later, also by the Orchestrator) gets full access; NULL = off. Turned on
  only with the owner's password through ``PUT /agents/full-access``; audited as
  ``agent.full_access_all_granted`` / ``_revoked``.

Revision ID: 0018_full_access_all
Revises: 0017_full_access
Create Date: 2026-11-03 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018_full_access_all"
down_revision: str | Sequence[str] | None = "0017_full_access"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("full_access_all_since", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "full_access_all_since")

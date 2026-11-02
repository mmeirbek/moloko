"""Owner request: the owner's own sign-in lifetime (users.session_ttl_hours).

NULL = use the configured default (SESSION_TTL_HOURS), so existing accounts keep
today's behaviour.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-02 04:34:16+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("session_ttl_hours", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "session_ttl_hours")

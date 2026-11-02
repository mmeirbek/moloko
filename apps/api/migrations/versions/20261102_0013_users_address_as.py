"""Owner request: how moloko addresses the owner (users.address_as).

NULL = no particular form of address (today's behaviour). The length limit is a
setting (ADDRESS_AS_MAX_CHARS), so the column is plain text.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-02 12:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("address_as", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "address_as")

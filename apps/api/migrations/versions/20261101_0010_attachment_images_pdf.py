"""Owner request: pictures and PDFs in chat (attachments.kind, data, pages).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-01 16:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "attachments", sa.Column("kind", sa.String(length=8), server_default="text", nullable=False)
    )
    op.add_column("attachments", sa.Column("data", sa.LargeBinary(), nullable=True))
    op.add_column("attachments", sa.Column("pages", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "pages")
    op.drop_column("attachments", "data")
    op.drop_column("attachments", "kind")

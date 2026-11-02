"""Owner request: attachments of any type, size and number (files on disk).

New uploads are streamed to FILE_STORAGE_ROOT; the row keeps the metadata and the text
for prompts and search. Older rows keep their bytes in ``data`` and still work.

* ``size`` becomes BIGINT (files over 2 GB).
* ``storage_path``: the original, relative to FILE_STORAGE_ROOT (NULL = old row).
* ``model_path``: the picture the model is shown (the original or a downscaled copy;
  NULL for a new picture = not shown, see ``note``).
* ``text_chars``: length of the whole text in characters (``text`` may hold less).
* ``note``: what the model should know about the file (e.g. only some PDF pages read).

Revision ID: 0014a
Revises: 0014d
Create Date: 2026-11-02 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014a"
down_revision: str | Sequence[str] | None = "0014d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "attachments", "size", type_=sa.BigInteger(), existing_type=sa.Integer(), nullable=False
    )
    op.add_column("attachments", sa.Column("storage_path", sa.String(length=255), nullable=True))
    op.add_column("attachments", sa.Column("model_path", sa.String(length=255), nullable=True))
    op.add_column("attachments", sa.Column("text_chars", sa.BigInteger(), nullable=True))
    op.add_column("attachments", sa.Column("note", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("attachments", "note")
    op.drop_column("attachments", "text_chars")
    op.drop_column("attachments", "model_path")
    op.drop_column("attachments", "storage_path")
    op.alter_column(
        "attachments", "size", type_=sa.Integer(), existing_type=sa.BigInteger(), nullable=False
    )

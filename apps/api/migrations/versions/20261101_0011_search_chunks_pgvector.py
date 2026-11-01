"""Owner request: semantic search (pgvector) over memories, workspace files and chat files.

Also re-indexes every table once: the database image moved from Alpine (musl) to Debian
(glibc), whose text sort order can differ, so indexes built before must be rebuilt.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-01 17:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.models.search import Vector

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN SELECT tablename FROM pg_tables WHERE schemaname = 'public' LOOP
                EXECUTE format('REINDEX TABLE %I', r.tablename);
            END LOOP;
        END $$;
        """
    )
    op.create_table(
        "search_chunks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_type", sa.String(length=16), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("memory_type", sa.String(length=24), nullable=True),
        sa.Column("project", sa.String(length=100), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("embedding", Vector(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_search_chunks_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_search_chunks")),
    )
    op.create_index(
        "ix_search_chunks_source",
        "search_chunks",
        ["user_id", "source_type", "source_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_search_chunks_source", table_name="search_chunks")
    op.drop_table("search_chunks")

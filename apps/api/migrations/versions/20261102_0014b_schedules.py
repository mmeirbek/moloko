"""Owner request: scheduled tasks (schedules).

A rule in the owner's time zone (once / every N hours / daily / weekly / monthly), the
target (the Orchestrator or a persistent agent) and the computed next run; the worker
starts due schedules every minute.

Revision ID: 0014b
Revises: 0013
Create Date: 2026-11-02 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014b"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "schedules",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("target", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("at_time", sa.String(length=5), nullable=True),
        sa.Column(
            "weekdays",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("day_of_month", sa.SmallInteger(), nullable=True),
        sa.Column("interval_hours", sa.SmallInteger(), nullable=True),
        sa.Column("run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("busy_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_task_id", sa.Uuid(), nullable=True),
        sa.Column("last_outcome", sa.String(length=16), nullable=True),
        sa.Column("last_reason", sa.String(length=64), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["agent_id"],
            ["agents.id"],
            name=op.f("fk_schedules_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["last_task_id"],
            ["tasks.id"],
            name=op.f("fk_schedules_last_task_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_schedules_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
    )
    op.create_index(op.f("ix_schedules_agent_id"), "schedules", ["agent_id"], unique=False)
    op.create_index("ix_schedules_due", "schedules", ["enabled", "next_run_at"], unique=False)
    op.create_index(
        "ix_schedules_user_created", "schedules", ["user_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_schedules_user_created", table_name="schedules")
    op.drop_index("ix_schedules_due", table_name="schedules")
    op.drop_index(op.f("ix_schedules_agent_id"), table_name="schedules")
    op.drop_table("schedules")

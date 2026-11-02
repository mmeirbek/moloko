"""Owner request: own agent templates ("Save as template") and a monthly budget per agent.

* ``agent_templates`` — the owner's own templates (an agent's reusable configuration),
  names unique per owner.
* ``agents.monthly_budget_usd`` — NULL = no limit of its own.
* ``usage_records.budget_agent_id`` — whose budget a model call counts against (the agent,
  or for a subagent the nearest persistent agent / Orchestrator above it). Backfilled.

Revision ID: 0014c
Revises: 0013
Create Date: 2026-11-02 18:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014c"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_templates",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("specialization", sa.String(length=64), nullable=True),
        sa.Column("model_config_id", sa.Uuid(), nullable=True),
        sa.Column("system_prompt", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "autonomy_level", sa.String(length=16), server_default="supervised", nullable=False
        ),
        sa.Column(
            "allowed_tools",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "permissions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "limits",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "memory_settings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("monthly_budget_usd", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("source_agent_id", sa.Uuid(), nullable=True),
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
            ["model_config_id"],
            ["model_configs.id"],
            name=op.f("fk_agent_templates_model_config_id_model_configs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["source_agent_id"],
            ["agents.id"],
            name=op.f("fk_agent_templates_source_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_agent_templates_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_templates")),
        sa.UniqueConstraint("user_id", "name", name=op.f("uq_agent_templates_user_id")),
    )

    op.add_column(
        "agents", sa.Column("monthly_budget_usd", sa.Numeric(precision=12, scale=2), nullable=True)
    )

    op.add_column("usage_records", sa.Column("budget_agent_id", sa.Uuid(), nullable=True))
    op.create_index(
        "ix_usage_records_budget_agent_created",
        "usage_records",
        ["budget_agent_id", "created_at"],
        unique=False,
    )
    # History so far: every agent call counts against the agent itself …
    op.execute("UPDATE usage_records SET budget_agent_id = agent_id WHERE agent_id IS NOT NULL")
    # … except subagents' calls: they count against the nearest non-subagent above them.
    op.execute(
        """
        WITH RECURSIVE chain AS (
            SELECT a.id AS start_id, a.id AS cur_id, a.parent_agent_id, a.agent_type, 0 AS depth
            FROM agents a WHERE a.agent_type = 'subagent'
            UNION ALL
            SELECT c.start_id, p.id, p.parent_agent_id, p.agent_type, c.depth + 1
            FROM chain c JOIN agents p ON p.id = c.parent_agent_id
            WHERE c.agent_type = 'subagent' AND c.depth < 10
        ),
        owners AS (
            SELECT DISTINCT ON (start_id) start_id, cur_id AS owner_id
            FROM chain WHERE agent_type <> 'subagent'
            ORDER BY start_id, depth
        )
        UPDATE usage_records u SET budget_agent_id = o.owner_id
        FROM owners o WHERE u.agent_id = o.start_id
        """
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_budget_agent_created", table_name="usage_records")
    op.drop_column("usage_records", "budget_agent_id")
    op.drop_column("agents", "monthly_budget_usd")
    op.drop_table("agent_templates")

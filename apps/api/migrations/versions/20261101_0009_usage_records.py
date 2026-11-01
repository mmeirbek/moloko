"""Owner request: usage ledger for costs and the monthly budget (backfilled from chat
messages and agent runs recorded so far).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-01 15:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_records",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("agent_name", sa.String(length=100), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("model_config_id", sa.Uuid(), nullable=True),
        sa.Column("provider_kind", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=False),
        sa.Column("input_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("output_tokens", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=14, scale=6), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["model_config_id"],
            ["model_configs.id"],
            name=op.f("fk_usage_records_model_config_id_model_configs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_usage_records_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
    )
    op.create_index(
        "ix_usage_records_user_created", "usage_records", ["user_id", "created_at"], unique=False
    )
    # history so far: chat answers …
    op.execute(
        """
        INSERT INTO usage_records (id, user_id, source, conversation_id, model_config_id,
            provider_kind, model, input_tokens, output_tokens, cost_usd, created_at)
        SELECT gen_random_uuid(), m.user_id, 'chat', m.conversation_id, m.model_config_id,
            m.provider_kind, COALESCE(m.model, 'unknown'), COALESCE(m.input_tokens, 0),
            COALESCE(m.output_tokens, 0), m.cost_usd, COALESCE(m.completed_at, m.created_at)
        FROM messages m
        WHERE m.role = 'assistant' AND (m.input_tokens IS NOT NULL OR m.output_tokens IS NOT NULL)
        """
    )
    # … and agent runs (one row per run, with the agent's model at that time)
    op.execute(
        """
        INSERT INTO usage_records (id, user_id, source, agent_id, agent_name, task_id, run_id,
            model_config_id, provider_kind, model, input_tokens, output_tokens, cost_usd,
            created_at)
        SELECT gen_random_uuid(), r.user_id,
            CASE WHEN a.agent_type = 'orchestrator' THEN 'orchestrator' ELSE 'agent' END,
            r.agent_id, a.name, r.task_id, r.id, a.model_config_id, p.kind,
            COALESCE(mc.model, 'unknown'),
            COALESCE((r.usage->>'input_tokens')::int, 0),
            COALESCE((r.usage->>'output_tokens')::int, 0),
            (r.usage->>'cost_usd')::numeric, COALESCE(r.finished_at, r.started_at, r.created_at)
        FROM agent_runs r
        JOIN agents a ON a.id = r.agent_id
        LEFT JOIN model_configs mc ON mc.id = a.model_config_id
        LEFT JOIN model_providers p ON p.id = mc.provider_id
        WHERE COALESCE((r.usage->>'input_tokens')::int, 0) > 0
           OR COALESCE((r.usage->>'output_tokens')::int, 0) > 0
        """
    )


def downgrade() -> None:
    op.drop_index("ix_usage_records_user_created", table_name="usage_records")
    op.drop_table("usage_records")

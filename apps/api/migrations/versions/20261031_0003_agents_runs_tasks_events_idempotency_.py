"""Sprint 3: agents, agent_runs, tasks, agent_events (append-only), idempotency_keys, system_settings.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31 20:37:17.020941+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "agent_events",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.Column("type", sa.String(length=48), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_events")),
        sa.UniqueConstraint("seq", name=op.f("uq_agent_events_seq")),
    )
    op.create_index("ix_agent_events_run_seq", "agent_events", ["run_id", "seq"], unique=False)
    op.create_index("ix_agent_events_task_seq", "agent_events", ["task_id", "seq"], unique=False)
    op.create_index("ix_agent_events_user_seq", "agent_events", ["user_id", "seq"], unique=False)
    op.create_table(
        "idempotency_keys",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scope", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_idempotency_keys_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_idempotency_keys")),
        sa.UniqueConstraint("user_id", "scope", "key", name=op.f("uq_idempotency_keys_user_id")),
    )
    op.create_table(
        "system_settings",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column(
            "value",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
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
            ["user_id"],
            ["users.id"],
            name=op.f("fk_system_settings_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_system_settings")),
        sa.UniqueConstraint("user_id", "key", name=op.f("uq_system_settings_user_id")),
    )
    op.create_table(
        "agents",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("agent_type", sa.String(length=16), nullable=False),
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
        sa.Column("status", sa.String(length=16), server_default="idle", nullable=False),
        sa.Column("paused_from", sa.String(length=16), nullable=True),
        sa.Column("current_task_id", sa.Uuid(), nullable=True),
        sa.Column("parent_agent_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("depth", sa.Integer(), server_default="0", nullable=False),
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
        sa.Column("runtime", sa.String(length=32), server_default="native", nullable=False),
        sa.Column("config_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_agents_model_config_id_model_configs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_agent_id"],
            ["agents.id"],
            name=op.f("fk_agents_parent_agent_id_agents"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agents_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
    )
    op.create_index(op.f("ix_agents_run_id"), "agents", ["run_id"], unique=False)
    op.create_index("ix_agents_user_type", "agents", ["user_id", "agent_type"], unique=False)
    op.create_table(
        "agent_runs",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("parent_run_id", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("phase", sa.String(length=20), nullable=True),
        sa.Column("plan", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "state",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("steps", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "usage",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("error_id", sa.String(length=64), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
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
            name=op.f("fk_agent_runs_agent_id_agents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_run_id"],
            ["agent_runs.id"],
            name=op.f("fk_agent_runs_parent_run_id_agent_runs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_agent_runs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_runs")),
    )
    op.create_index(op.f("ix_agent_runs_agent_id"), "agent_runs", ["agent_id"], unique=False)
    op.create_index(op.f("ix_agent_runs_task_id"), "agent_runs", ["task_id"], unique=False)
    op.create_table(
        "tasks",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("task_type", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("agent_id", sa.Uuid(), nullable=True),
        sa.Column("run_id", sa.Uuid(), nullable=True),
        sa.Column("parent_task_id", sa.Uuid(), nullable=True),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("retry_of_id", sa.Uuid(), nullable=True),
        sa.Column(
            "depends_on",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("progress", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("status_reason", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("error_id", sa.String(length=64), nullable=True),
        sa.Column("created_by", sa.String(length=16), server_default="user", nullable=False),
        sa.Column(
            "extra",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
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
            ["agent_id"], ["agents.id"], name=op.f("fk_tasks_agent_id_agents"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["parent_task_id"],
            ["tasks.id"],
            name=op.f("fk_tasks_parent_task_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["retry_of_id"],
            ["tasks.id"],
            name=op.f("fk_tasks_retry_of_id_tasks"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_tasks_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_agent_id"), "tasks", ["agent_id"], unique=False)
    op.create_index(op.f("ix_tasks_parent_task_id"), "tasks", ["parent_task_id"], unique=False)
    op.create_index("ix_tasks_user_created", "tasks", ["user_id", "created_at"], unique=False)
    op.create_index("ix_tasks_user_status", "tasks", ["user_id", "status"], unique=False)

    # agent_events is append-only (spec 10.1): reject UPDATE and DELETE in the database.
    op.execute(
        """
        CREATE FUNCTION agent_events_block_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'agent_events is append-only (% blocked)', TG_OP;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER agent_events_append_only
        BEFORE UPDATE OR DELETE ON agent_events
        FOR EACH ROW EXECUTE FUNCTION agent_events_block_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER agent_events_append_only ON agent_events")
    op.execute("DROP FUNCTION agent_events_block_mutation()")
    op.drop_index("ix_tasks_user_status", table_name="tasks")
    op.drop_index("ix_tasks_user_created", table_name="tasks")
    op.drop_index(op.f("ix_tasks_parent_task_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_agent_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(op.f("ix_agent_runs_task_id"), table_name="agent_runs")
    op.drop_index(op.f("ix_agent_runs_agent_id"), table_name="agent_runs")
    op.drop_table("agent_runs")
    op.drop_index("ix_agents_user_type", table_name="agents")
    op.drop_index(op.f("ix_agents_run_id"), table_name="agents")
    op.drop_table("agents")
    op.drop_table("system_settings")
    op.drop_table("idempotency_keys")
    op.drop_index("ix_agent_events_user_seq", table_name="agent_events")
    op.drop_index("ix_agent_events_task_seq", table_name="agent_events")
    op.drop_index("ix_agent_events_run_seq", table_name="agent_events")
    op.drop_table("agent_events")

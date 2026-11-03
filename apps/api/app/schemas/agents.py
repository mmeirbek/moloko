from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StrictBool

from app.agents.looks import Animal
from app.agents.state import AgentType, AutonomyLevel
from app.schemas.tasks import RunOut, TaskOut


class AgentContacts(BaseModel):
    """Who a persistent agent may talk to directly (agent_ask / agent_tell). Both sides
    must allow it. Subagents only talk to their siblings; the Orchestrator is no contact."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "list", "none"] = Field(
        default="all", description="all = every own agent, list = only agent_ids, none = nobody"
    )
    agent_ids: list[uuid.UUID] = Field(
        default_factory=list, max_length=100, description="Used when mode = list."
    )


class AgentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str
    agent_type: str
    specialization: str | None
    model_config_id: uuid.UUID | None
    system_prompt: str
    autonomy_level: str
    allowed_tools: list[str]
    permissions: dict[str, Any]
    status: str
    paused_from: str | None
    current_task_id: uuid.UUID | None
    parent_agent_id: uuid.UUID | None
    run_id: uuid.UUID | None
    depth: int
    limits: dict[str, Any]
    memory_settings: dict[str, Any]
    runtime: str
    workspace_id: uuid.UUID | None
    config_version: int
    archived_at: datetime | None
    monthly_budget_usd: Decimal | None
    contacts: AgentContacts
    full_access: bool = Field(
        description="«Полный доступ»: every enabled tool, no approvals (the owner's decision; "
        "changed only through PUT /agents/{id}/full-access)."
    )
    full_access_since: datetime | None = Field(description="When full access was turned on.")
    animal: str | None = Field(
        default=None, description="Its animal (face and office character); null = the Orchestrator."
    )
    created_at: datetime
    updated_at: datetime


# Per-agent monthly budget in USD (None = no limit of its own; the global budget still applies).
MonthlyBudget = Annotated[
    Decimal | None,
    Field(
        gt=0,
        le=1_000_000,
        decimal_places=2,
        description="Monthly limit in USD for this agent's model calls, subagents included; "
        "null = no limit of its own.",
    ),
    AfterValidator(lambda v: v.quantize(Decimal("0.01")) if v is not None else None),
]

ToolOverride = Literal["approve", "deny"]


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_steps: int | None = Field(default=None, ge=1, le=1000)
    run_timeout_seconds: int | None = Field(default=None, ge=10, le=86_400)


class MemorySettings(BaseModel):
    """How much saved memory an agent sees (spec 17). Defaults apply to ``{}``."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    include_shared: bool = True  # shared ``user`` memories about the owner
    # Shared notes of these projects are included too.
    projects: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(
        default_factory=list, max_length=20
    )
    # At most MEMORY_CONTEXT_MAX_CHARS (checked by the service); None = the global limit.
    max_context_chars: int | None = Field(default=None, ge=200, le=200_000)


class AgentCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)
    agent_type: AgentType = AgentType.AUTONOMOUS
    specialization: str | None = Field(default=None, max_length=64)
    model_config_id: uuid.UUID | None = None
    system_prompt: str = Field(default="", max_length=20_000)
    autonomy_level: AutonomyLevel = AutonomyLevel.SUPERVISED
    allowed_tools: list[str] = Field(default_factory=list, max_length=100)
    limits: AgentLimits = Field(default_factory=AgentLimits)
    memory_settings: MemorySettings = Field(default_factory=MemorySettings)
    # Per-tool overrides; they can only be stricter than the autonomy level (spec 14.2).
    tool_overrides: dict[str, ToolOverride] = Field(default_factory=dict, max_length=100)
    workspace_id: uuid.UUID | None = None  # a project workspace; None = one per task
    monthly_budget_usd: MonthlyBudget = None
    contacts: AgentContacts = Field(default_factory=AgentContacts)
    animal: Animal | None = Field(default=None, description="Its animal; null = chosen at random.")


class AgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=2000)
    specialization: str | None = Field(default=None, max_length=64)
    model_config_id: uuid.UUID | None = None
    system_prompt: str | None = Field(default=None, max_length=20_000)
    autonomy_level: AutonomyLevel | None = None
    allowed_tools: list[str] | None = Field(default=None, max_length=100)
    limits: AgentLimits | None = None
    memory_settings: MemorySettings | None = None
    tool_overrides: dict[str, ToolOverride] | None = Field(default=None, max_length=100)
    workspace_id: uuid.UUID | None = None
    monthly_budget_usd: MonthlyBudget = None  # sent as null = remove the limit
    contacts: AgentContacts | None = None  # omitted / null = unchanged
    animal: Animal | None = None  # omitted / null = unchanged


class AgentFullAccessUpdate(BaseModel):
    """Body of ``PUT /agents/{id}/full-access`` and ``PUT /agents/full-access`` (all agents).
    Turning it on needs the owner's password (wrong ones count toward the login lockout);
    turning it off does not."""

    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    password: str | None = Field(
        default=None, min_length=1, max_length=1024, description="Required when enabled."
    )


class FullAccessForAllOut(BaseModel):
    """«Полный доступ всем агентам»: whether every persistent agent of the office (and every
    one added later, also by the Orchestrator) works without approvals."""

    enabled: bool
    since: datetime | None = Field(description="When it was turned on; null = off.")


class AgentTemplateOut(BaseModel):
    key: str = Field(
        description="What POST /agents/from-template takes: a built-in key, or an own "
        "template's id."
    )
    source: Literal["builtin", "own"]
    id: uuid.UUID | None = Field(description="Own templates only (DELETE /agents/templates/{id}).")
    name: str
    description: str
    specialization: str
    allowed_tools: list[str]
    autonomy_level: str
    model_config_id: uuid.UUID | None
    monthly_budget_usd: Decimal | None
    created_at: datetime | None


class AgentFromTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template: str = Field(
        min_length=1,
        max_length=64,
        description="A key from GET /agents/templates (built-in key or own template id).",
    )
    name: str | None = Field(default=None, min_length=1, max_length=100)
    locale: str = Field(default="ru", max_length=8)


class SaveAsTemplate(BaseModel):
    """Optional body of ``POST /agents/{id}/save-template``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="The template's name; by default the agent's name.",
    )


class AgentBudgetOut(BaseModel):
    """This month's spending against the budget that applies to an agent."""

    agent_id: uuid.UUID
    budget_agent_id: uuid.UUID = Field(
        description="Whose budget counts: the agent itself, or for a subagent the "
        "persistent agent / Orchestrator above it."
    )
    budget_agent_name: str
    month: str
    spent_usd: Decimal
    monthly_budget_usd: Decimal | None
    warn_percent: int
    percent: float | None
    exceeded: bool


class AgentRestore(BaseModel):
    """Optional body of ``POST /agents/{id}/restore``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Come back under this name (when another agent took the old one).",
    )


class AgentMessageItem(BaseModel):
    """One message in an agent's correspondence (agent page → «Переписка»)."""

    id: uuid.UUID
    created_at: datetime
    direction: Literal["in", "out"] = Field(description="Relative to the agent asked about.")
    sender_agent_id: uuid.UUID
    sender_name: str | None
    receiver_agent_id: uuid.UUID
    receiver_name: str | None
    message_type: str = Field(
        description="request = agent_ask question, task_result = its answer, error = no "
        "answer (failed / cancelled / timed out), note = agent_tell, context = Orchestrator "
        "plan input"
    )
    status: str = Field(description="delivered | refused")
    error: str | None = Field(description="Why it was refused (a reason code).")
    summary: str
    text: str | None = Field(description="The full text; null when refused.")
    files: list[str]
    task_id: uuid.UUID | None
    consult_task_id: uuid.UUID | None = Field(description="The receiver's task of a question.")
    asker_task_id: uuid.UUID | None = Field(description="The asking agent's task.")
    read_at: datetime | None


class AgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: uuid.UUID | None = None  # run an existing (created) task …
    title: str | None = Field(default=None, min_length=1, max_length=200)  # … or a new one
    description: str = Field(default="", max_length=50_000)


class StartedRun(BaseModel):
    task: TaskOut
    run: RunOut | None = Field(
        description="The run; null while the task waits in line for its busy agent "
        "(it starts by itself when the agent is free)."
    )

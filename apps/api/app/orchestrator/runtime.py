"""Orchestrator runtime (spec 14.3).

    planning ── direct answer ──────────────────────────────────────► completed
        │
        └─ delegate: new agents (if the plan needs them) + one part per agent,
           wait (task ``waiting``; the Orchestrator is free for other tasks) ─┐ scheduler
    aggregating ◄── all parts finished (re-queued when the Orchestrator is free) ◄┘
        └─ synthesis (checked critically when plan.review) → completed
           (or failed if no part succeeded)

Every part goes to one of the owner's persistent agents (no temporary subagents). Limits
(parts, new agents, active parts, steps, time) are enforced in code.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import lock_agent, lock_run, lock_task, release_agent, set_task_status
from app.agents.state import AgentStatus, TaskStatus, TaskType
from app.events import bus
from app.models.agent import Agent, AgentRun
from app.models.chat import Conversation, Message
from app.models.task import Task
from app.orchestrator.messaging import format_inputs, inbox
from app.orchestrator.parts import create_subtasks, owner_agents, owner_models
from app.orchestrator.plan import Plan, PlanError, parse_plan
from app.orchestrator.prompts import planning_system, synthesis_system
from app.orchestrator.scheduler import WAITING_FOR_SUBTASKS
from app.providers.base import ChatMessage, ChatRequest, ChatResult
from app.providers.gateway import ModelTarget
from app.runtimes.base import RunContext
from app.runtimes.native import (
    LimitExceeded,
    NativeRuntime,
    RunSetup,
    owner_note,
    task_prompt,
)
from app.schemas.chat import MessageOut
from app.tools.policy import ALWAYS_ALLOWED


async def _agent_names(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
    return {i: n for i, n in rows.all()}


async def inputs_for(db: AsyncSession, agent: Agent, run_id: uuid.UUID) -> str:
    """The results sent to the Orchestrator within this run (its parts' results)."""
    messages = await inbox(db, agent, run_id=run_id)
    names = await _agent_names(db, {m.sender_agent_id for m in messages})
    return format_inputs(messages, names)


def with_owner_context(system: str, setup: RunSetup) -> str:
    """The Orchestrator's protocol prompt, then the owner's form of address (an
    instruction), then saved memory (data, always last)."""
    return "\n\n".join(p for p in (system, setup.address, setup.memory) if p)


class OrchestratorRuntime(NativeRuntime):
    name = "orchestrator"

    async def run(self, ctx: RunContext, segment_started: float) -> None:
        setup = await self.setup(ctx)
        async with asyncio.timeout(setup.remaining):
            if setup.run.phase in (None, "planning"):
                await self._plan(ctx, setup, segment_started)
            else:
                await self._aggregate(ctx, setup, segment_started)

    # --- model calls ----------------------------------------------------------------------

    async def _call(
        self,
        ctx: RunContext,
        setup: RunSetup,
        system: str,
        transcript: list[ChatMessage],
        segment_started: float,
    ) -> ChatResult:
        await ctx.control.check()
        if setup.steps >= setup.max_steps:
            raise LimitExceeded(
                "max_steps_exceeded", f"The orchestrator used all {setup.max_steps} steps."
            )
        await self._ensure_working(ctx)
        await self._budget_gate(ctx)
        request = ChatRequest(
            model=setup.target.model,
            messages=tuple(transcript),
            system=system,
            max_tokens=ctx.settings.agent_max_output_tokens,
        )
        result: ChatResult = await ctx.control.guard(ctx.gateway.complete(setup.target, request))
        setup.steps += 1
        transcript.append(ChatMessage(role="assistant", content=result.text))
        await self._checkpoint(
            ctx,
            setup.target,
            transcript,
            setup.steps,
            result,
            setup.elapsed + time.monotonic() - segment_started,
        )
        return result

    # --- planning --------------------------------------------------------------------------

    async def _plan(self, ctx: RunContext, setup: RunSetup, segment_started: float) -> None:
        settings = ctx.settings
        agent, task = setup.agent, setup.task
        async with ctx.sessionmaker() as db:
            roster = await owner_agents(db, agent.user_id)
            models = await owner_models(db, agent.user_id, settings.orchestrator_max_models_listed)
        # A new agent may only get tools the Orchestrator itself may use; every agent has
        # the read-only history tools anyway (not part of the plan).
        tools = tuple(t.name for t in setup.tools if t.name not in ALWAYS_ALLOWED)
        system = planning_system(
            max_subtasks=settings.max_subtasks_per_plan,
            max_active=settings.max_active_parts_per_run,
            max_new_agents=settings.orchestrator_max_new_agents,
            tools=tools,
            agents=tuple((a.name, a.specialization or "", a.description) for a in roster),
            models=tuple(line for line, _ in models.values()),
        )
        system = with_owner_context(system, setup)
        async with ctx.sessionmaker() as db:
            inputs = await inputs_for(db, agent, ctx.run_id)
        prompt = task_prompt(task) + (f"\n\n{inputs}" if inputs else "")
        if notes := await self._owner_notes(ctx):
            prompt += f"\n\n{notes}"
        transcript = [ChatMessage(role="user", content=prompt)]
        attempts = 0
        while True:
            result = await self._call(ctx, setup, system, transcript, segment_started)
            try:
                plan, warnings = parse_plan(
                    result.text,
                    max_subtasks=settings.max_subtasks_per_plan,
                    agents=[a.name for a in roster],
                    max_new_agents=settings.orchestrator_max_new_agents,
                    tools=list(tools),
                    models={name: model_id for name, (_, model_id) in models.items()},
                )
                break
            except PlanError as exc:
                attempts += 1
                if attempts > settings.max_retries_per_step:
                    raise LimitExceeded(
                        "invalid_plan", f"The orchestrator could not produce a valid plan: {exc}"
                    ) from None
                transcript.append(
                    ChatMessage(
                        role="user",
                        content=f"Your reply was not a valid plan ({exc}). "
                        "Reply with ONE valid JSON object.",
                    )
                )

        await self._store_plan(ctx, plan, warnings)
        if plan.mode == "direct":
            await self._complete(ctx, plan.answer or "")
            return
        await self._delegate(ctx, plan)

    async def _store_plan(self, ctx: RunContext, plan: Plan, warnings: list[str]) -> None:
        async with ctx.sessionmaker() as db:
            run = await lock_run(db, ctx.run_id)
            run.plan = {**plan.model_dump(), "warnings": warnings}
            await bus.emit(
                db,
                user_id=ctx.user_id,
                type="agent.message",
                agent_id=ctx.agent_id,
                task_id=ctx.task_id,
                run_id=ctx.run_id,
                payload={
                    "kind": "plan",
                    "mode": plan.mode,
                    "summary": plan.summary,
                    "subtasks": [
                        {
                            "key": s.key,
                            "title": s.title,
                            "agent": s.agent,
                            "depends_on": s.depends_on,
                        }
                        for s in plan.subtasks
                    ],
                    "new_agents": [a.name for a in plan.new_agents],
                    "review": plan.review,
                    "warnings": warnings,
                },
            )
            await bus.commit(db)

    async def _delegate(self, ctx: RunContext, plan: Plan) -> None:
        async with ctx.sessionmaker() as db:
            agent = await lock_agent(db, ctx.agent_id)
            task = await lock_task(db, ctx.task_id)
            run = await lock_run(db, ctx.run_id)
            if TaskStatus(task.status) != TaskStatus.RUNNING:
                return
            await create_subtasks(db, orchestrator=agent, parent_task=task, plan=plan)
            run.phase = "delegating"
            # The run fixes the active-parts limit for the whole plan.
            run.state = {**run.state, "max_active_parts": ctx.settings.max_active_parts_per_run}
            await self._wait_for_subtasks(db, agent, task, run)
            await bus.commit(db)

    async def _wait_for_subtasks(
        self, db: AsyncSession, agent: Agent, task: Task, run: AgentRun
    ) -> None:
        """The plan waits for its parts; the Orchestrator does not: it is free for the next
        task meanwhile (owner: «оркестратор делает сразу несколько задач»). When the parts are
        done the scheduler gives the plan back to it to merge (app/agents/waiting.py)."""
        await set_task_status(db, task, TaskStatus.WAITING, reason=WAITING_FOR_SUBTASKS, run=run)
        if agent.current_task_id == task.id:
            await release_agent(db, agent, to=AgentStatus.IDLE, reason="parts_under_way")

    # --- aggregation -----------------------------------------------------------------------

    async def _aggregate(self, ctx: RunContext, setup: RunSetup, segment_started: float) -> None:
        async with ctx.sessionmaker() as db:
            children = list(
                (
                    await db.execute(
                        select(Task)
                        .where(Task.parent_task_id == ctx.task_id)
                        .order_by(Task.created_at)
                    )
                ).scalars()
            )
            plan = Plan.model_validate(
                {k: v for k, v in (setup.run.plan or {}).items() if k != "warnings"}
            )
            completed = [
                c
                for c in children
                if c.status == TaskStatus.COMPLETED.value and c.task_type == TaskType.SUBTASK.value
            ]
            inputs = await inputs_for(db, setup.agent, ctx.run_id)
        if not completed:
            raise LimitExceeded("subtasks_failed", "None of the subtasks finished successfully.")

        async with ctx.sessionmaker() as db:
            run = await lock_run(db, ctx.run_id)
            run.phase = "aggregating"
            await bus.commit(db)
        prompt = f"{task_prompt(setup.task)}\n\n{inputs}"
        if notes := await self._owner_notes(ctx):
            prompt += f"\n\n{notes}"
        transcript = [ChatMessage(role="user", content=prompt)]
        system = with_owner_context(synthesis_system(review=plan.review), setup)
        result = await self._call(ctx, setup, system, transcript, segment_started)
        await self._complete(ctx, result.text)

    async def _owner_notes(self, ctx: RunContext) -> str:
        """What the owner wrote to the whole task (the parts at work got it too): read when
        the Orchestrator plans and when it merges, then the inbox is empty."""
        async with ctx.sessionmaker() as db:
            run = await lock_run(db, ctx.run_id)
            notes = [str(m["text"]) for m in (run.state or {}).get("owner_inbox") or []]
            if not notes:
                return ""
            run.state = {**(run.state or {}), "owner_inbox": []}
            await bus.emit(
                db,
                user_id=ctx.user_id,
                type="task.owner_message_read",
                agent_id=ctx.agent_id,
                task_id=ctx.task_id,
                run_id=ctx.run_id,
                payload={"count": len(notes)},
            )
            await bus.commit(db)
        return owner_note(notes)

    # --- results -----------------------------------------------------------------------------

    async def _complete(self, ctx: RunContext, final: str) -> None:
        async with ctx.sessionmaker() as db:
            run = await lock_run(db, ctx.run_id)
            run.phase = "done"
            await bus.commit(db)
        await super()._complete(ctx, final)
        await self._report_to_chat(ctx)

    async def _fail(
        self, ctx: RunContext, code: str, message: str, *, error_id: str | None = None
    ) -> None:
        await super()._fail(ctx, code, message, error_id=error_id)
        await self._report_to_chat(ctx)

    async def _report_to_chat(self, ctx: RunContext) -> None:
        """A run handed off from the chat posts its outcome back into that conversation."""
        async with ctx.sessionmaker() as db:
            run = await db.get(AgentRun, ctx.run_id)
            task = await db.get(Task, ctx.task_id)
            if (
                run is None
                or task is None
                or run.conversation_id is None
                or task.parent_task_id is not None
            ):
                return
            if task.status not in (TaskStatus.COMPLETED.value, TaskStatus.FAILED.value):
                return
            exists = await db.execute(
                select(Message.id)
                .where(Message.agent_run_id == run.id, Message.role == "assistant")
                .limit(1)
            )
            if exists.first() is not None:
                return
            now = datetime.now(UTC)
            ok = task.status == TaskStatus.COMPLETED.value
            message = Message(
                conversation_id=run.conversation_id,
                user_id=task.user_id,
                role="assistant",
                content=(task.result or "") if ok else "",
                status="completed" if ok else "failed",
                agent_run_id=run.id,
                provider_kind="agents",
                model="orchestrator",
                error_code=None if ok else task.error_code,
                error_message=None if ok else task.error_message,
                error_id=None if ok else task.error_id,
                completed_at=now,
                created_at=now,
            )
            db.add(message)
            await db.execute(
                update(Conversation)
                .where(Conversation.id == run.conversation_id)
                .values(last_message_at=now)
            )
            await db.flush()
            await bus.emit(
                db,
                user_id=task.user_id,
                type="chat.message_completed",
                run_id=run.id,
                task_id=task.id,
                payload={
                    "conversation_id": str(run.conversation_id),
                    "message": MessageOut.model_validate(message).model_dump(mode="json"),
                },
            )
            await bus.commit(db)


__all__ = ["ModelTarget", "OrchestratorRuntime"]

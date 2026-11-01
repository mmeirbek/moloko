"""Orchestrator runtime (spec 14.3) and the subagent runtime.

    planning ── direct answer ──────────────────────────────► reviewing → completed
        │
        └─ delegate: create subagents + subtasks, wait (task ``waiting``) ─┐
                                                                         │ scheduler
    aggregating ◄── all subtasks finished (task re-queued) ◄─────────────┘
        ├─ plan.review and not reviewed yet → Reviewer subagent, wait again
        └─ synthesis → completed (or failed if no subtask succeeded)

Limits (subagent count, depth, active subagents, steps, time) are enforced in code.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.engine import lock_agent, lock_run, lock_task, set_agent_status, set_task_status
from app.agents.state import AgentStatus, AgentType, TaskStatus, TaskType
from app.events import bus
from app.models.agent import Agent, AgentRun
from app.models.chat import Conversation, Message
from app.models.task import Task
from app.orchestrator.messaging import format_inputs, inbox
from app.orchestrator.plan import Plan, PlanError, parse_plan
from app.orchestrator.prompts import planning_system, synthesis_system
from app.orchestrator.scheduler import WAITING_FOR_SUBTASKS
from app.orchestrator.subagents import create_review_task, create_subtasks
from app.providers.base import ChatMessage, ChatRequest, ChatResult
from app.providers.gateway import ModelTarget
from app.runtimes.base import RunContext
from app.runtimes.native import LimitExceeded, NativeRuntime, RunSetup, task_prompt
from app.schemas.chat import MessageOut


async def _agent_names(db: AsyncSession, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
    return {i: n for i, n in rows.all()}


async def inputs_for(db: AsyncSession, agent: Agent) -> str:
    messages = await inbox(db, agent)
    names = await _agent_names(db, {m.sender_agent_id for m in messages})
    return format_inputs(messages, names)


class SubagentRuntime(NativeRuntime):
    """A native agent whose context includes the results passed to it by other agents."""

    name = "subagent"

    async def extra_system(
        self, ctx: RunContext, db: AsyncSession, agent: Agent, task: Task
    ) -> str:
        return await inputs_for(db, agent)


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
        can_create = agent.depth + 1 <= settings.max_subagent_depth
        can_delegate_further = agent.depth + 2 <= settings.max_subagent_depth
        system = planning_system(
            max_subtasks=settings.max_subtasks_per_plan,
            max_active=settings.max_active_subagents_per_run,
            can_delegate=can_delegate_further,
        )
        if setup.memory:
            system += "\n\n" + setup.memory
        async with ctx.sessionmaker() as db:
            inputs = await inputs_for(db, agent)
        prompt = task_prompt(task) + (f"\n\n{inputs}" if inputs else "")
        transcript = [ChatMessage(role="user", content=prompt)]
        attempts = 0
        while True:
            result = await self._call(ctx, setup, system, transcript, segment_started)
            try:
                plan, warnings = parse_plan(
                    result.text,
                    max_subtasks=settings.max_subtasks_per_plan,
                    can_delegate_further=can_delegate_further,
                )
                if plan.mode == "delegate" and not can_create:
                    raise PlanError("delegation is not allowed at this depth; answer directly")
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
                        {"key": s.key, "title": s.title, "depends_on": s.depends_on}
                        for s in plan.subtasks
                    ],
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
            await create_subtasks(
                db, orchestrator=agent, parent_task=task, plan=plan, settings=ctx.settings
            )
            run.phase = "delegating"
            if agent.agent_type == AgentType.ORCHESTRATOR.value:
                # The root run fixes the active-subagent limit for the whole tree.
                run.state = {
                    **run.state,
                    "max_active_subagents": ctx.settings.max_active_subagents_per_run,
                }
            await self._wait_for_subtasks(db, agent, task, run)
            await bus.commit(db)

    async def _wait_for_subtasks(
        self, db: AsyncSession, agent: Agent, task: Task, run: AgentRun
    ) -> None:
        if AgentStatus(agent.status) in (AgentStatus.PLANNING, AgentStatus.WORKING):
            if AgentStatus(agent.status) == AgentStatus.PLANNING:
                await set_agent_status(db, agent, AgentStatus.WORKING)
            await set_agent_status(db, agent, AgentStatus.WAITING, reason=WAITING_FOR_SUBTASKS)
        await set_task_status(db, task, TaskStatus.WAITING, reason=WAITING_FOR_SUBTASKS, run=run)

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
            reviewed = any(c.task_type == TaskType.REVIEW.value for c in children)
            if plan.review and not reviewed and completed:
                agent = await lock_agent(db, ctx.agent_id)
                task = await lock_task(db, ctx.task_id)
                run = await lock_run(db, ctx.run_id)
                if TaskStatus(task.status) != TaskStatus.RUNNING:
                    return
                await create_review_task(
                    db,
                    orchestrator=agent,
                    parent_task=task,
                    inputs=completed,
                    settings=ctx.settings,
                )
                run.phase = "reviewing"
                await self._ensure_working_in(db, agent)
                await self._wait_for_subtasks(db, agent, task, run)
                await bus.commit(db)
                return
            inputs = await inputs_for(db, setup.agent)
        if not completed:
            raise LimitExceeded("subtasks_failed", "None of the subtasks finished successfully.")

        async with ctx.sessionmaker() as db:
            run = await lock_run(db, ctx.run_id)
            run.phase = "aggregating"
            await bus.commit(db)
        transcript = [ChatMessage(role="user", content=f"{task_prompt(setup.task)}\n\n{inputs}")]
        system = synthesis_system() + (f"\n\n{setup.memory}" if setup.memory else "")
        result = await self._call(ctx, setup, system, transcript, segment_started)
        await self._complete(ctx, result.text)

    async def _ensure_working_in(self, db: AsyncSession, agent: Agent) -> None:
        if AgentStatus(agent.status) == AgentStatus.WAITING:
            await set_agent_status(db, agent, AgentStatus.WORKING)

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


__all__ = ["ModelTarget", "OrchestratorRuntime", "SubagentRuntime"]

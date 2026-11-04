"""Turns events into Web Push messages (worker cron, every few seconds).

A per-user cursor over ``agent_events.seq`` (in ``system_settings``) makes each event
announced at most once; on the very first run the cursor starts at "now" (no backlog).
Events older than ``MAX_AGE`` are skipped. The cursor moves before sending: a push that
fails is not retried (notifications are best-effort; the app shows everything anyway).
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.agent import Agent
from app.models.event import AgentEvent
from app.models.system import SystemSetting
from app.models.tooling import PushSubscription
from app.push import texts
from app.push.webpush import host_allowed, push_subject, send
from app.services.push import PushUnavailable, vapid_keys

logger = logging.getLogger("moloko.push")

CURSOR_KEY = "push_cursor"
MAX_AGE = timedelta(minutes=15)
TYPES = ("approval.required", "task.completed", "task.failed", "budget.warning")
TITLES = {
    "ru": {
        "approval": "Нужно ваше одобрение",
        "approvalNamed": "{name} ждёт вашего одобрения",
        "taskDone": "Готово: {task}",
        "taskDonePlain": "Задача выполнена",
        "taskFailed": "Сломалось: {task}",
        "taskFailedPlain": "Задача не выполнена",
        "taskQuestion": "Агент ждёт вашего ответа",
        "taskQuestionNamed": "{name} ждёт вашего ответа",
        "budget": "Месячный лимит расходов исчерпан",
        "agentBudget": "«{name}»: бюджет агента на месяц исчерпан",
    },
    "en": {
        "approval": "Your approval is needed",
        "approvalNamed": "{name} needs your approval",
        "taskDone": "Done: {task}",
        "taskDonePlain": "Task done",
        "taskFailed": "Didn't work out: {task}",
        "taskFailedPlain": "Task failed",
        "taskQuestion": "An agent is waiting for your answer",
        "taskQuestionNamed": "{name} is waiting for your answer",
        "budget": "The monthly cost limit is used up",
        "agentBudget": "{name}: the agent's monthly budget is used up",
    },
}


@dataclass(frozen=True)
class Notice:
    kind: str
    key: str
    subject: str  # task title / costs line (the raw text; shortened when sent)
    url: str
    percent: int = 0
    title: str = ""  # TITLES key when it differs from ``kind``
    name: str = ""  # the agent's name
    tool: str = ""  # approvals: which tool, and its arguments (worded in texts.py)
    args: dict[str, Any] = field(default_factory=dict)
    error_code: str = ""  # failed tasks
    summary: str = ""  # finished tasks: the short result, or the question the agent asks
    agent_id: str = ""  # tasks: whose name to look up
    tag: str = ""  # notifications with one tag replace each other (default: the key)


def notice_for(event: AgentEvent, now: datetime) -> Notice | None:
    """Same rules as the in-app notifications (apps/web/lib/notifications/rules.ts)."""
    if now - event.created_at > MAX_AGE:
        return None
    payload: dict[str, Any] = event.payload or {}
    if event.type == "approval.required":
        approval = payload.get("approval") or {}
        if not approval.get("id"):
            return None
        task_id = approval.get("task_id")
        return Notice(
            "approval",
            f"approval:{approval['id']}",
            str(approval.get("summary", "")),
            "/approvals",
            name=str(approval.get("agent_name") or "")[:100],
            tool=str(approval.get("tool_name") or ""),
            args=dict(approval.get("args") or {}),
            # one notification per task: the next request replaces the previous one
            tag=f"approval:task:{task_id}" if task_id else "",
        )
    if event.type == "budget.warning" and int(payload.get("percent", 0)) < 100:
        return None  # only a used-up budget stops agents (owner: notify when something broke)
    if event.type == "budget.warning" and payload.get("scope") == "agent":
        percent = int(payload.get("percent", 0))
        agent_id = str(payload.get("agent_id", ""))
        return Notice(
            "budget",
            f"budget:{payload.get('month')}:{agent_id}:{percent}",
            f"${payload.get('spent_usd')} / ${payload.get('limit_usd')}",
            f"/office/agents/{agent_id}",
            percent,
            title="agentBudget",
            name=str(payload.get("agent_name", ""))[:100],
        )
    if event.type == "budget.warning":
        percent = int(payload.get("percent", 0))
        return Notice(
            "budget",
            f"budget:{payload.get('month')}:{percent}",
            f"${payload.get('spent_usd')} / ${payload.get('limit_usd')}",
            "/settings/costs",
            percent,
        )
    if event.type in ("task.completed", "task.failed"):
        task = payload.get("task") or {}
        if not task.get("id") or task.get("parent_task_id"):
            return None  # subtasks are part of a bigger job
        done = event.type == "task.completed"
        result = str(task.get("result") or "") if done else ""
        question = texts.owner_question(result)
        return Notice(
            "taskDone" if done else "taskFailed",
            f"task:{task['id']}:{event.type}",
            str(task.get("title", "")),
            f"/tasks/{task['id']}",
            title="taskQuestion" if question else "",
            summary=question or texts.result_summary(result),
            error_code="" if done else str(task.get("error_code") or ""),
            agent_id=str(task.get("agent_id") or event.agent_id or ""),
        )
    return None


async def _advance(db: AsyncSession, user_id: uuid.UUID) -> tuple[int | None, int]:
    """(previous cursor or None on first run, new cursor) — the row stays locked."""
    head = int(
        (
            await db.execute(select(func.max(AgentEvent.seq)).where(AgentEvent.user_id == user_id))
        ).scalar()
        or 0
    )
    row = (
        await db.execute(
            select(SystemSetting)
            .where(SystemSetting.user_id == user_id, SystemSetting.key == CURSOR_KEY)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(SystemSetting(user_id=user_id, key=CURSOR_KEY, value={"seq": head}))
        return None, head
    previous = int(row.value.get("seq", 0))
    row.value = {"seq": head}
    return previous, head


async def dispatch(sessionmaker: async_sessionmaker[AsyncSession], settings: Settings) -> int:
    """One pass. Returns how many push messages were accepted by push services."""
    async with sessionmaker() as db:
        users = list((await db.execute(select(PushSubscription.user_id).distinct())).scalars())
    sent = 0
    for user_id in users:
        async with sessionmaker() as db:
            previous, head = await _advance(db, user_id)
            if previous is None or head <= previous:
                await db.commit()
                continue
            events = list(
                (
                    await db.execute(
                        select(AgentEvent)
                        .where(
                            AgentEvent.user_id == user_id,
                            AgentEvent.seq > previous,
                            AgentEvent.seq <= head,
                            AgentEvent.type.in_(TYPES),
                        )
                        .order_by(AgentEvent.seq)
                        .limit(50)
                    )
                ).scalars()
            )
            now = datetime.now(UTC)
            notices = [n for n in (notice_for(e, now) for e in events) if n is not None]
            notices = await _with_agent_names(db, notices)
            try:
                keys = await vapid_keys(db, settings, user_id) if notices else None
            except PushUnavailable:
                keys = None
            subs = list(
                (
                    await db.execute(
                        select(PushSubscription).where(PushSubscription.user_id == user_id)
                    )
                ).scalars()
            )
            await db.commit()  # the cursor moved: each event is announced at most once
            if keys is None:
                continue
            for notice in notices:
                for sub in subs:
                    if notice.kind not in (sub.kinds or []) or not host_allowed(
                        sub.endpoint, settings.push_allowed_hosts
                    ):
                        continue
                    sent += await _deliver(db, sub, notice, keys, settings)
            await db.commit()
    return sent


async def _with_agent_names(db: AsyncSession, notices: list[Notice]) -> list[Notice]:
    """Task notices say whose task it was."""
    ids: set[uuid.UUID] = set()
    for n in notices:
        try:
            if n.agent_id and not n.name:
                ids.add(uuid.UUID(n.agent_id))
        except ValueError:
            continue
    if not ids:
        return notices
    rows = await db.execute(select(Agent.id, Agent.name).where(Agent.id.in_(ids)))
    names = {str(i): name for i, name in rows.all()}
    return [
        replace(n, name=names.get(n.agent_id, n.name)[:100]) if n.agent_id else n for n in notices
    ]


def render(notice: Notice, locale: str) -> tuple[str, str]:
    """The notification's title and text in the owner's language: who, and what in plain
    words — never a raw command, file contents or a long path."""
    titles = TITLES.get(texts.lang(locale), TITLES["ru"])
    if notice.kind == "approval":
        title = (
            titles["approvalNamed"].format(name=notice.name) if notice.name else titles["approval"]
        )
        body = (
            texts.approval_text(locale, notice.tool, notice.args)
            if notice.tool
            else texts.short_text(notice.subject)
        )
        return title, body
    if notice.kind in ("taskDone", "taskFailed"):
        # Which task in the title; who and the short result (or why it failed) in the text.
        # An answer that ends with a question: the agent waits for the owner's reply.
        if notice.title == "taskQuestion":
            title = (
                titles["taskQuestionNamed"].format(name=notice.name)
                if notice.name
                else titles["taskQuestion"]
            )
            return title, notice.summary
        task = texts.short_text(notice.subject, texts.TASK_IN_TITLE_MAX)
        title = titles[notice.kind].format(task=task) if task else titles[f"{notice.kind}Plain"]
        detail = (
            notice.summary
            if notice.kind == "taskDone"
            else texts.failure_reason(locale, notice.error_code)
        )
        body = f"{notice.name}: {detail}" if notice.name and detail else notice.name or detail
        return title, body
    title = titles[notice.title or notice.kind].format(percent=notice.percent, name=notice.name)
    return title, texts.short_text(notice.subject, 300)


async def _deliver(
    db: AsyncSession, sub: PushSubscription, notice: Notice, keys: Any, settings: Settings
) -> int:
    title, body = render(notice, sub.locale)
    tag = notice.tag or notice.key
    payload: dict[str, object] = {"title": title, "body": body[:300], "url": notice.url, "tag": tag}
    topic = hashlib.sha256(tag.encode()).hexdigest()[:32]
    try:
        status = await send(
            sub.endpoint,
            sub.p256dh,
            sub.auth,
            payload,
            keys,
            subject=push_subject(settings.push_contact, settings.webauthn_origins),
            ttl=settings.push_ttl_seconds,
            urgency="high" if notice.kind in ("approval", "budget") else "normal",
            topic=topic,
        )
    except Exception as exc:  # noqa: BLE001 — a push service being down must not stop the worker
        logger.warning("push_send_failed", extra={"error": type(exc).__name__})
        status = 0
    fresh = await db.get(PushSubscription, sub.id)
    if fresh is None:
        return 0
    if status in (404, 410):  # the browser dropped the subscription
        await db.delete(fresh)
        return 0
    if 200 <= status < 300:
        fresh.last_sent_at, fresh.failures = datetime.now(UTC), 0
        return 1
    fresh.failures += 1
    if fresh.failures >= 20:
        await db.delete(fresh)
    return 0

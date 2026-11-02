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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.models.event import AgentEvent
from app.models.system import SystemSetting
from app.models.tooling import PushSubscription
from app.push.webpush import host_allowed, send
from app.services.push import PushUnavailable, vapid_keys

logger = logging.getLogger("moloko.push")

CURSOR_KEY = "push_cursor"
MAX_AGE = timedelta(minutes=15)
TYPES = ("approval.required", "task.completed", "task.failed")
TITLES = {
    "ru": {
        "approval": "Нужно ваше одобрение",
        "taskDone": "Задача выполнена",
        "taskFailed": "Задача не выполнена",
    },
    "en": {
        "approval": "Your approval is needed",
        "taskDone": "Task done",
        "taskFailed": "Task failed",
    },
}


@dataclass(frozen=True)
class Notice:
    kind: str
    key: str
    subject: str
    url: str


def notice_for(event: AgentEvent, now: datetime) -> Notice | None:
    """Same rules as the in-app notifications (apps/web/lib/notifications/rules.ts)."""
    if now - event.created_at > MAX_AGE:
        return None
    payload: dict[str, Any] = event.payload or {}
    if event.type == "approval.required":
        approval = payload.get("approval") or {}
        if not approval.get("id"):
            return None
        who = approval.get("agent_name")
        subject = (
            f"{who}: {approval.get('summary', '')}" if who else str(approval.get("summary", ""))
        )
        return Notice("approval", f"approval:{approval['id']}", subject, "/approvals")
    if event.type in ("task.completed", "task.failed"):
        task = payload.get("task") or {}
        if not task.get("id") or task.get("parent_task_id"):
            return None  # subtasks are part of a bigger job
        done = event.type == "task.completed"
        return Notice(
            "taskDone" if done else "taskFailed",
            f"task:{task['id']}:{event.type}",
            str(task.get("title", "")),
            f"/tasks/{task['id']}",
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


async def _deliver(
    db: AsyncSession, sub: PushSubscription, notice: Notice, keys: Any, settings: Settings
) -> int:
    title = TITLES.get(sub.locale, TITLES["ru"])[notice.kind]
    payload: dict[str, object] = {
        "title": title,
        "body": notice.subject[:300],
        "url": notice.url,
        "tag": notice.key,
    }
    topic = hashlib.sha256(notice.key.encode()).hexdigest()[:32]
    try:
        status = await send(
            sub.endpoint,
            sub.p256dh,
            sub.auth,
            payload,
            keys,
            subject=settings.push_contact,
            ttl=settings.push_ttl_seconds,
            urgency="high" if notice.kind == "approval" else "normal",
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

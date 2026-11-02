"""When a schedule runs: simple, readable rules → the next run time (pure, no I/O).

Every rule is a local wall-clock time in the owner's IANA time zone:

* ``once``     — one moment (``run_at``);
* ``hourly``   — every N hours from HH:MM, N divides 24, so the times are the same every day
  (every 6 hours from 08:00 = 02:00, 08:00, 14:00, 20:00);
* ``daily``    — every day at HH:MM;
* ``weekly``   — on chosen weekdays (ISO: 1 = Monday … 7 = Sunday) at HH:MM;
* ``monthly``  — on day N (1-31; a shorter month uses its last day) at HH:MM.

Daylight saving time: a local time that does not exist that day (clocks jump forward) runs
at the shifted time (02:30 → 03:30); a local time that happens twice (clocks fall back) runs
once, the first time.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as TimeOfDay
from functools import lru_cache
from typing import Literal, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

Kind = Literal["once", "hourly", "daily", "weekly", "monthly"]
KINDS: tuple[str, ...] = get_args(Kind)
ALL_WEEKDAYS = (1, 2, 3, 4, 5, 6, 7)
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class RecurrenceError(ValueError):
    """A rule that cannot be built. ``code`` is the API error code, ``field`` the culprit."""

    def __init__(self, code: str, field: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.field = field
        self.message = message


@lru_cache(maxsize=1)
def _zones() -> frozenset[str]:
    return frozenset(available_timezones())


def zone(name: str) -> ZoneInfo:
    """An IANA zone the server knows (e.g. ``Asia/Almaty``), or ``invalid_timezone``."""
    if not name or len(name) > 64 or name not in _zones():
        raise RecurrenceError("invalid_timezone", "timezone", "Unknown time zone.")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise RecurrenceError("invalid_timezone", "timezone", "Unknown time zone.") from None


def parse_time(value: str | None, field: str = "time") -> TimeOfDay:
    match = _HHMM.match(value or "")
    if match is None:
        raise RecurrenceError("invalid_recurrence", field, "Give a time as HH:MM.")
    return TimeOfDay(int(match.group(1)), int(match.group(2)))


def format_time(value: TimeOfDay) -> str:
    return f"{value.hour:02d}:{value.minute:02d}"


@dataclass(frozen=True)
class Rule:
    kind: Kind
    tz: ZoneInfo
    time: TimeOfDay | None = None
    weekdays: tuple[int, ...] = ()
    day_of_month: int | None = None
    interval_hours: int | None = None
    run_at: datetime | None = None  # once: the moment (aware, UTC)

    @property
    def timezone(self) -> str:
        return self.tz.key

    def slots(self) -> list[TimeOfDay]:
        """Local times of day this rule runs at (daily, weekly, monthly: one; hourly: 24 / N)."""
        assert self.time is not None
        if self.kind != "hourly":
            return [self.time]
        step = self.interval_hours or 24
        return sorted(
            TimeOfDay((self.time.hour + k * step) % 24, self.time.minute) for k in range(24 // step)
        )


def build_rule(
    *,
    kind: str,
    timezone: str,
    time_of_day: str | None = None,
    weekdays: list[int] | tuple[int, ...] = (),
    day_of_month: int | None = None,
    interval_hours: int | None = None,
    run_at: datetime | None = None,
    min_interval_minutes: int = 60,
) -> Rule:
    """Validate the fields a kind needs and drop the ones it ignores."""
    tz = zone(timezone)
    if kind not in KINDS:
        raise RecurrenceError("invalid_recurrence", "kind", "Unknown kind of schedule.")
    if kind == "once":
        if run_at is None:
            raise RecurrenceError("invalid_recurrence", "run_at", "Give a date and time.")
        moment = run_at.replace(tzinfo=tz) if run_at.tzinfo is None else run_at
        return Rule(kind="once", tz=tz, run_at=moment.astimezone(UTC).replace(microsecond=0))
    at = parse_time(time_of_day if kind != "hourly" or time_of_day else "00:00")
    if kind == "hourly":
        if interval_hours is None or interval_hours < 1 or 24 % interval_hours:
            raise RecurrenceError(
                "invalid_recurrence",
                "interval_hours",
                "Every N hours: N must divide 24 (1, 2, 3, 4, 6, 8 or 12).",
            )
        if interval_hours * 60 < min_interval_minutes:
            raise RecurrenceError(
                "interval_too_short", "interval_hours", "This repeats more often than allowed."
            )
        if interval_hours == 24:
            return Rule(kind="daily", tz=tz, time=at, weekdays=ALL_WEEKDAYS)
        return Rule(kind="hourly", tz=tz, time=at, interval_hours=interval_hours)
    if kind == "daily":
        return Rule(kind="daily", tz=tz, time=at, weekdays=ALL_WEEKDAYS)
    if kind == "weekly":
        days = tuple(sorted(set(weekdays)))
        if not days or any(d not in ALL_WEEKDAYS for d in days):
            raise RecurrenceError(
                "invalid_recurrence", "weekdays", "Choose at least one day of the week."
            )
        return Rule(kind="weekly", tz=tz, time=at, weekdays=days)
    if day_of_month is None or not 1 <= day_of_month <= 31:
        raise RecurrenceError(
            "invalid_recurrence", "day_of_month", "Choose a day of the month (1-31)."
        )
    return Rule(kind="monthly", tz=tz, time=at, day_of_month=day_of_month)


def local_moment(day: date, at: TimeOfDay, tz: ZoneInfo) -> datetime:
    """``day`` at ``at`` on the wall clock of ``tz``, as an aware UTC datetime (see DST above)."""
    return datetime.combine(day, at, tzinfo=tz).astimezone(UTC)


def next_after(rule: Rule, after: datetime) -> datetime | None:
    """The first run strictly after ``after`` (aware), or None when there is none (once, past).

    Strictly after: called with the moment a run was handled, every missed run in between
    collapses into that one run (catch-up runs once, not N times).
    """
    after = after.astimezone(UTC)
    if rule.kind == "once":
        return rule.run_at if rule.run_at is not None and rule.run_at > after else None
    assert rule.time is not None
    start = after.astimezone(rule.tz).date()
    if rule.kind == "monthly":
        assert rule.day_of_month is not None
        year, month = start.year, start.month
        for _ in range(14):
            last = calendar.monthrange(year, month)[1]
            day = date(year, month, min(rule.day_of_month, last))
            moment = local_moment(day, rule.time, rule.tz)
            if moment > after:
                return moment
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        raise AssertionError("monthly rule found no day")  # pragma: no cover
    days = set(rule.weekdays) if rule.kind == "weekly" else set(ALL_WEEKDAYS)
    slots = rule.slots()
    # From the day before (a zone may jump at midnight) through a full week and a day.
    for offset in range(-1, 9):
        day = start + timedelta(days=offset)
        if day.isoweekday() not in days:
            continue
        for at in slots:
            moment = local_moment(day, at, rule.tz)
            if moment > after:
                return moment
    raise AssertionError("rule found no day")  # pragma: no cover


def upcoming(rule: Rule, after: datetime, count: int) -> list[datetime]:
    """The next ``count`` runs after ``after`` (fewer for a one-off)."""
    runs: list[datetime] = []
    moment: datetime | None = after
    while len(runs) < count and moment is not None:
        moment = next_after(rule, moment)
        if moment is not None:
            runs.append(moment)
    return runs

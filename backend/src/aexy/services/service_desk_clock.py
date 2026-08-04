"""The Service Desk breach clock: working hours, IST.

The BRD's turnaround target is **2 business days**, and Bimaplan operates in
IST. Two things follow, and both are needed for the number to mean anything:

* The clock only runs during **working hours** on a working day. A ticket that
  lands at 18:00 has not consumed a day's allowance by 09:30 the next morning,
  and nothing accrues overnight, at the weekend, or on a holiday.
* "2 business days" is therefore ``2 × WORKING_DAY_SECONDS`` of working time —
  18 hours on a 09:30–18:30 day, not 48 hours of wall clock. ``to_days``
  divides by the working day, so a figure of ``1.0`` means one full working day
  of attention was available and went by.

Day boundaries and the working window resolve in **Asia/Kolkata**, because
whether an instant falls inside Tuesday's shift depends on the timezone you ask
in. IST has no DST, so the boundaries are unambiguous.

The window is per workspace (``Workspace.settings["service_desk"]``
``["working_hours"]`` as ``{"start": "HH:MM", "end": "HH:MM"}``) and falls back
to the default below. Everything breach-related lives here so the threshold
cannot drift: it was previously written as a bare ``> 2`` in the ticket service,
again in the digest service, and a third time in the digest email copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Mapping
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

IST = ZoneInfo("Asia/Kolkata")

# Default working window, IST. Override per workspace via settings.
DEFAULT_WORK_START = time(9, 30)
DEFAULT_WORK_END = time(18, 30)

# Thresholds for the CURRENT STAGE age, in working days.
BREACH_RED_DAYS = 2.0
BREACH_AMBER_DAYS = 1.0
TEST_SLA_STAGES = frozenset({"kam", "insurer", "partner"})


def _active_test_stage_slas(value: object) -> dict[str, tuple[int, int]]:
    """Read a safely ignorable test override from persisted workspace settings.

    Validation occurs at the API boundary. This defensive reader means a stale
    or hand-edited JSON setting cannot break ticket listing, and expiry alone is
    enough for the regular SLA to become active again.
    """
    if not isinstance(value, dict):
        return {}
    raw_expiry = value.get("expires_at")
    if not isinstance(raw_expiry, str):
        return {}
    try:
        expires_at = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
        if expires_at.tzinfo is None or expires_at <= datetime.now(timezone.utc):
            return {}
    except ValueError:
        return {}

    stages: dict[str, tuple[int, int]] = {}
    for stage in TEST_SLA_STAGES:
        rule = value.get(stage)
        if not isinstance(rule, dict):
            return {}
        amber, red = rule.get("amber_minutes"), rule.get("red_minutes")
        if not isinstance(amber, int) or not isinstance(red, int) or amber < 1 or red <= amber:
            return {}
        stages[stage] = (amber, red)
    return stages


def _aware(dt: datetime) -> datetime:
    """Treat naive datetimes (SQLite) as UTC so arithmetic is safe."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _parse_hhmm(value: object, fallback: time) -> time:
    """Lenient on purpose: a malformed setting must not break the dashboard."""
    if isinstance(value, str):
        try:
            hh, mm = value.split(":")[:2]
            return time(int(hh), int(mm))
        except (ValueError, TypeError):
            pass
    return fallback


@dataclass(frozen=True)
class Clock:
    """A workspace's working calendar: the shift, plus the days it doesn't run."""

    work_start: time = DEFAULT_WORK_START
    work_end: time = DEFAULT_WORK_END
    holidays: frozenset[date] = field(default_factory=frozenset)
    # These rules exist only for a short, explicitly configured test window.
    # Missing, malformed, or expired data falls back to the normal day targets.
    test_stage_slas: Mapping[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def working_day_seconds(self) -> float:
        start = self.work_start.hour * 3600 + self.work_start.minute * 60
        end = self.work_end.hour * 3600 + self.work_end.minute * 60
        # A nonsensical window would make every ticket instantly breach (or never
        # breach); fall back to a 9h day rather than divide by zero.
        return float(end - start) if end > start else 9 * 3600.0

    def is_working_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def seconds_between(self, start: datetime, end: datetime) -> int:
        """Working seconds between two instants — the SLA clock."""
        if end <= start:
            return 0
        begin = _aware(start).astimezone(IST)
        finish = _aware(end).astimezone(IST)

        total = 0.0
        day = begin.date()
        last = finish.date()
        while day <= last:
            if self.is_working_day(day):
                shift_open = datetime.combine(day, self.work_start, tzinfo=IST)
                shift_close = datetime.combine(day, self.work_end, tzinfo=IST)
                lo = max(begin, shift_open)
                hi = min(finish, shift_close)
                if hi > lo:
                    total += (hi - lo).total_seconds()
            day += timedelta(days=1)
        return int(total)

    def to_days(self, working_seconds: int) -> float:
        """Working seconds as working days — 1.0 means one full shift went by."""
        return round(working_seconds / self.working_day_seconds, 2)

    def breach_level(
        self,
        stage_working_seconds: int,
        pending_with: str | None = None,
        cumulative_working_seconds: int | None = None,
    ) -> str:
        """How late this ticket is with its current stakeholder.

        ``stage_working_seconds`` is the open segment's age and drives amber and
        red exactly as the BRD specifies.

        ``cumulative_working_seconds`` is everything this stakeholder has held the
        ticket for, across every hand-off, and can only ever raise the result to
        red. It exists because a stakeholder who answers "still checking" hands
        the ticket back, which restarts the stage clock: without this, a daily
        holding reply would keep a chronically late insurer permanently green.
        It never triggers amber, so a ticket that is healthy today cannot be
        pushed to amber by history alone.
        """
        if pending_with in self.test_stage_slas:
            amber_minutes, red_minutes = self.test_stage_slas[pending_with]
            if stage_working_seconds > red_minutes * 60:
                return "red"
            if (cumulative_working_seconds or 0) > red_minutes * 60:
                return "red"
            if stage_working_seconds >= amber_minutes * 60:
                return "amber"
            return "green"
        days = stage_working_seconds / self.working_day_seconds
        if days > BREACH_RED_DAYS:
            return "red"
        if (cumulative_working_seconds or 0) / self.working_day_seconds > BREACH_RED_DAYS:
            return "red"
        if days >= BREACH_AMBER_DAYS:
            return "amber"
        return "green"

    def is_breaching(self, stage_working_seconds: int, pending_with: str | None = None) -> bool:
        if pending_with in self.test_stage_slas:
            _, red_minutes = self.test_stage_slas[pending_with]
            return stage_working_seconds > red_minutes * 60
        return stage_working_seconds / self.working_day_seconds > BREACH_RED_DAYS


async def load_clock(db: AsyncSession, workspace_id: str) -> Clock:
    """Build the workspace's clock: its working window and its holidays.

    Holidays reuse the Leave module's ``holidays`` table (whose own docstring
    says it is for business-day calculations) rather than a hardcoded calendar.
    Optional holidays are excluded because they are not days off for everyone,
    and team-scoped ones are excluded because an SLA that changes depending on
    which team you ask about is not an SLA.
    """
    from aexy.models.leave import Holiday
    from aexy.models.workspace import Workspace

    rows = (
        await db.execute(
            select(Holiday.date, Holiday.is_optional, Holiday.applicable_team_ids).where(
                Holiday.workspace_id == workspace_id
            )
        )
    ).all()
    holidays = frozenset(
        day for day, is_optional, team_ids in rows if not is_optional and not (team_ids or [])
    )

    ws = await db.get(Workspace, workspace_id)
    service_desk = ((ws.settings or {}).get("service_desk") or {}) if ws else {}
    hours = service_desk.get("working_hours") or {}
    return Clock(
        work_start=_parse_hhmm(hours.get("start"), DEFAULT_WORK_START),
        work_end=_parse_hhmm(hours.get("end"), DEFAULT_WORK_END),
        holidays=holidays,
        test_stage_slas=_active_test_stage_slas(service_desk.get("test_sla")),
    )

"""Computing and reading the daily platform snapshot.

The admin area's platform figures were all live queries describing this
instant. That answers "what is MRR?" but not "is it growing?", and it cannot
be made to answer the second afterwards — nothing in the live tables records
that a workspace *was* active thirty days ago, or what a plan cost when it was
billed. `PlatformDailyStats` is where the answer gets written down.

Two things follow from that:

* **A past day can only be computed from rows that still carry their date.**
  Signups, cancellations and AI spend can be recomputed for any day, because
  `created_at` / `canceled_at` are still there. Subscription state, seat
  counts and the month-to-date bill cannot — they describe now. Backfilling a
  past day fills in what is derivable and records the rest in ``notes``, so a
  zero that means "we did not know" is never read as "there was none".

* **The expensive half is done once, overnight.** `/billing/totals` loops
  every active workspace and runs a full `BillingBreakdownService` pass per
  workspace on every request. That is this job's revenue section, so the
  endpoint reads one row instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.billing import Invoice, Subscription, UsageRecord
from aexy.models.developer import Developer
from aexy.models.entity_activity import EntityActivity
from aexy.models.plan import Plan
from aexy.models.platform_stats import PlatformDailyStats
from aexy.models.work_update import WorkUpdate
from aexy.models.workspace import Workspace, WorkspaceMember, WorkspaceSubscription

logger = logging.getLogger(__name__)

#: How far back "active" looks.
ACTIVITY_WINDOW_DAYS = 30

#: Subscription states that are paying us.
PAYING_STATUSES = ("active", "past_due")


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return start, start + timedelta(days=1)


def _month_bounds(moment: datetime) -> tuple[datetime, datetime]:
    start = moment.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        return start, start.replace(year=start.year + 1, month=1)
    return start, start.replace(month=start.month + 1)


@dataclass
class SnapshotResult:
    day: date
    created: bool
    notes: list[str]


class PlatformStatsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------ read

    async def series(self, days: int = 90) -> list[PlatformDailyStats]:
        """Snapshots for the last `days` days, oldest first (chart order)."""
        cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
        rows = await self.db.execute(
            select(PlatformDailyStats)
            .where(PlatformDailyStats.day >= cutoff)
            .order_by(PlatformDailyStats.day.asc())
        )
        return list(rows.scalars().all())

    async def latest(self) -> PlatformDailyStats | None:
        row = await self.db.execute(
            select(PlatformDailyStats).order_by(PlatformDailyStats.day.desc()).limit(1)
        )
        return row.scalar_one_or_none()

    async def on_day(self, day: date) -> PlatformDailyStats | None:
        row = await self.db.execute(
            select(PlatformDailyStats).where(PlatformDailyStats.day == day)
        )
        return row.scalar_one_or_none()

    # --------------------------------------------------------------- compute

    async def compute_day(
        self, day: date | None = None, *, include_revenue: bool = True
    ) -> SnapshotResult:
        """Write (or overwrite) the snapshot for `day`. Idempotent."""
        today = datetime.now(timezone.utc).date()
        day = day or today
        is_today = day >= today
        notes: list[str] = []

        values: dict[str, Any] = {}
        values.update(await self._growth(day))
        values.update(await self._llm_spend(day))

        if is_today:
            values.update(await self._subscriptions())
            values.update(await self._invoices())
            if include_revenue:
                revenue, revenue_notes = await self._revenue()
                values.update(revenue)
                notes.extend(revenue_notes)
            else:
                notes.append("revenue section skipped by request")
        else:
            # Subscription state, seats and the month-to-date bill describe
            # now. Recomputing them for a past day would silently stamp
            # today's numbers on it.
            notes.append(
                "historical day: subscription, seat, revenue and invoice "
                "figures are not recoverable after the fact and are left at zero"
            )

        values["notes"] = notes
        values["computed_at"] = datetime.now(timezone.utc)

        existing = await self.on_day(day)
        if existing is None:
            self.db.add(PlatformDailyStats(day=day, **values))
            created = True
        else:
            for key, value in values.items():
                setattr(existing, key, value)
            created = False
        await self.db.flush()
        return SnapshotResult(day=day, created=created, notes=notes)

    async def backfill(self, days: int = 90) -> list[SnapshotResult]:
        """Fill in the days before this table existed, as far as the source
        rows allow. Cheap: no revenue pass, and only the date-carrying parts
        are derivable anyway."""
        today = datetime.now(timezone.utc).date()
        results = []
        for offset in range(days, 0, -1):
            results.append(await self.compute_day(today - timedelta(days=offset)))
        return results

    # -------------------------------------------------------------- sections

    async def _growth(self, day: date) -> dict[str, Any]:
        start, end = _day_bounds(day)
        window = end - timedelta(days=ACTIVITY_WINDOW_DAYS)

        workspaces_total = await self.db.scalar(
            select(func.count(Workspace.id)).where(Workspace.created_at < end)
        )
        workspaces_created = await self.db.scalar(
            select(func.count(Workspace.id)).where(
                Workspace.created_at >= start, Workspace.created_at < end
            )
        )
        developers_total = await self.db.scalar(
            select(func.count(Developer.id)).where(Developer.created_at < end)
        )
        developers_created = await self.db.scalar(
            select(func.count(Developer.id)).where(
                Developer.created_at >= start, Developer.created_at < end
            )
        )

        # "Active" means somebody did something: created or changed a
        # document, task or project; posted a progress update; or spent AI
        # budget. The figure this replaces counted `WorkspaceMember.updated_at`
        # — a membership row's modification time, which is not activity at all.
        active_sources = [
            select(EntityActivity.workspace_id.label("ws")).where(
                EntityActivity.created_at >= window, EntityActivity.created_at < end
            ),
            select(WorkUpdate.workspace_id.label("ws")).where(
                WorkUpdate.created_at >= window, WorkUpdate.created_at < end
            ),
            select(UsageRecord.workspace_id.label("ws")).where(
                UsageRecord.created_at >= window,
                UsageRecord.created_at < end,
                UsageRecord.workspace_id.isnot(None),
            ),
        ]
        active = active_sources[0].union(*active_sources[1:]).subquery()
        workspaces_active_30d = await self.db.scalar(
            select(func.count(func.distinct(active.c.ws)))
        )

        return {
            "workspaces_total": workspaces_total or 0,
            "workspaces_created": workspaces_created or 0,
            "workspaces_active_30d": workspaces_active_30d or 0,
            "developers_total": developers_total or 0,
            "developers_created": developers_created or 0,
        }

    async def _llm_spend(self, day: date) -> dict[str, Any]:
        start, end = _day_bounds(day)
        row = (
            await self.db.execute(
                select(
                    func.count(UsageRecord.id),
                    func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                    func.coalesce(func.sum(UsageRecord.base_cost_cents), 0.0),
                    func.coalesce(func.sum(UsageRecord.total_cost_cents), 0.0),
                ).where(UsageRecord.created_at >= start, UsageRecord.created_at < end)
            )
        ).one()

        by_provider_rows = await self.db.execute(
            select(
                UsageRecord.provider,
                func.coalesce(func.sum(UsageRecord.total_tokens), 0),
                func.coalesce(func.sum(UsageRecord.total_cost_cents), 0.0),
            )
            .where(UsageRecord.created_at >= start, UsageRecord.created_at < end)
            .group_by(UsageRecord.provider)
        )
        by_provider = {
            provider or "unknown": {"tokens": int(tokens), "cents": float(cents)}
            for provider, tokens, cents in by_provider_rows
        }

        return {
            "llm_requests": int(row[0] or 0),
            "llm_tokens": int(row[1] or 0),
            "llm_base_cost_cents": float(row[2] or 0.0),
            "llm_billed_cents": float(row[3] or 0.0),
            "llm_by_provider": by_provider,
        }

    async def _subscriptions(self) -> dict[str, Any]:
        rows = await self.db.execute(
            select(WorkspaceSubscription.status, func.count(WorkspaceSubscription.id))
            .group_by(WorkspaceSubscription.status)
        )
        by_status = {status or "unknown": int(count) for status, count in rows}

        # Recurring money only: base fee plus the seats beyond those included.
        # Usage is deliberately out, so a heavy month of AI does not read as
        # subscription growth.
        mrr = await self.db.scalar(
            select(
                func.coalesce(
                    func.sum(
                        WorkspaceSubscription.base_fee_monthly_cents
                        + WorkspaceSubscription.additional_seats
                        * WorkspaceSubscription.price_per_additional_seat_cents
                    ),
                    0,
                )
            ).where(WorkspaceSubscription.status.in_(PAYING_STATUSES))
        )
        paying = await self.db.scalar(
            select(func.count(WorkspaceSubscription.id)).where(
                WorkspaceSubscription.status.in_(PAYING_STATUSES)
            )
        )
        trialing = await self.db.scalar(
            select(func.count(WorkspaceSubscription.id)).where(
                WorkspaceSubscription.status == "trialing"
            )
        )
        seats = await self.db.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.status == "active",
                WorkspaceMember.is_billable.is_(True),
            )
        )
        # Cancellations are dated, so this one is a real daily figure. It
        # comes off the Stripe-synced table, the only one that records when.
        yesterday = datetime.now(timezone.utc) - timedelta(days=1)
        canceled = await self.db.scalar(
            select(func.count(Subscription.id)).where(
                Subscription.canceled_at.isnot(None),
                Subscription.canceled_at >= yesterday,
            )
        )

        return {
            "subscriptions_by_status": by_status,
            "mrr_cents": float(mrr or 0),
            "paying_workspaces": int(paying or 0),
            "trialing_workspaces": int(trialing or 0),
            "billable_seats": int(seats or 0),
            "subscriptions_canceled": int(canceled or 0),
        }

    async def _invoices(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        open_row = (
            await self.db.execute(
                select(
                    func.count(Invoice.id),
                    func.coalesce(func.sum(Invoice.amount_due_cents), 0),
                ).where(Invoice.status == "open")
            )
        ).one()
        overdue_row = (
            await self.db.execute(
                select(
                    func.count(Invoice.id),
                    func.coalesce(func.sum(Invoice.amount_due_cents), 0),
                ).where(Invoice.status == "open", Invoice.due_date < now)
            )
        ).one()
        return {
            "invoices_open": int(open_row[0] or 0),
            "invoices_open_cents": float(open_row[1] or 0),
            "invoices_overdue": int(overdue_row[0] or 0),
            "invoices_overdue_cents": float(overdue_row[1] or 0),
        }

    async def _revenue(self) -> tuple[dict[str, Any], list[str]]:
        """The month-to-date bill across every active workspace.

        One `BillingBreakdownService` pass per workspace — the same loop
        `/billing/totals` used to run on every request, now run once a day.
        """
        from aexy.services.billing_breakdown_service import BillingBreakdownService

        period_start, period_end = _month_bounds(datetime.now(timezone.utc))
        workspaces = list(
            (
                await self.db.execute(
                    select(Workspace).where(Workspace.is_active.is_(True))
                )
            )
            .scalars()
            .all()
        )

        service = BillingBreakdownService(self.db, include_margin=True)
        revenue = base_cost = margin = 0.0
        by_tier: dict[str, float] = {}
        by_model: dict[str, float] = {}
        rows: list[dict[str, Any]] = []
        failed: list[str] = []

        for ws in workspaces:
            try:
                breakdown = await service.get_breakdown(
                    ws.id, period_start=period_start, period_end=period_end
                )
            except Exception:
                logger.exception("Snapshot breakdown failed for workspace %s", ws.id)
                failed.append(str(ws.id))
                continue
            ws_margin = breakdown.get("margin") or {}
            total = float(breakdown.get("total_cents", 0.0))
            tier = breakdown.get("plan_tier") or "unknown"
            model = breakdown.get("billing_model") or "unknown"
            revenue += total
            base_cost += float(ws_margin.get("base_cost_cents", 0.0))
            margin += float(ws_margin.get("margin_cents", 0.0))
            by_tier[tier] = by_tier.get(tier, 0.0) + total
            by_model[model] = by_model.get(model, 0.0) + total
            rows.append(
                {
                    "workspace_id": str(ws.id),
                    "workspace_name": ws.name,
                    "plan_tier": tier,
                    "billing_model": model,
                    "total_cents": total,
                    "base_cost_cents": float(ws_margin.get("base_cost_cents", 0.0)),
                    "margin_cents": float(ws_margin.get("margin_cents", 0.0)),
                    "seat_count": int(
                        (breakdown.get("info_counters") or {}).get("seat_count", 0)
                    ),
                    "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(),
                }
            )

        rows.sort(key=lambda r: r["total_cents"], reverse=True)
        notes = []
        if failed:
            notes.append(
                f"{len(failed)} workspace(s) could not be priced and are missing "
                f"from the revenue total: {', '.join(failed[:5])}"
                + (" …" if len(failed) > 5 else "")
            )
        return (
            {
                "revenue_workspace_count": len(rows),
                "revenue_cents": revenue,
                "base_cost_cents": base_cost,
                "margin_cents": margin,
                "revenue_by_plan_tier": by_tier,
                "revenue_by_billing_model": by_model,
                "top_workspaces": rows[:10],
            },
            notes,
        )


async def plan_tier_counts(db: AsyncSession) -> dict[str, int]:
    """How many active workspaces sit on each plan tier, right now."""
    rows = await db.execute(
        select(Plan.tier, func.count(Workspace.id))
        .select_from(Workspace)
        .outerjoin(Plan, Plan.id == Workspace.plan_id)
        .where(Workspace.is_active.is_(True))
        .group_by(Plan.tier)
    )
    return {tier or "none": int(count) for tier, count in rows}

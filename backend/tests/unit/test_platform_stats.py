"""The daily platform snapshot: what it records, and what it refuses to invent.

Every platform figure the admin area showed was a live query describing this
instant, so "is MRR growing?" had no answer and could not be given one after
the fact. These tests pin the two halves of the fix: the numbers written down
each day, and the honesty about the ones a past day cannot recover.
"""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from aexy.models.billing import CustomerBilling, Invoice, Subscription, UsageRecord
from aexy.models.developer import Developer
from aexy.models.entity_activity import EntityActivity
from aexy.models.platform_stats import PlatformDailyStats
from aexy.models.workspace import Workspace, WorkspaceMember, WorkspaceSubscription
from aexy.services.platform_stats_service import PlatformStatsService

# The revenue section prices every workspace through `BillingBreakdownService`,
# which lazily creates a free `Plan` whose `llm_provider_access` is a list —
# a column SQLite cannot bind. The tests below are about the other sections,
# so they leave it out; the revenue figures are checked against the live
# computation instead (see the pull request).

TODAY = datetime.now(timezone.utc)


def _ago(days: int, hours: int = 12) -> datetime:
    return (TODAY - timedelta(days=days)).replace(hour=hours, minute=0, second=0, microsecond=0)


async def _workspace(db, slug: str, *, created: datetime, owner: Developer) -> Workspace:
    ws = Workspace(name=slug, slug=slug, owner_id=owner.id, created_at=created)
    db.add(ws)
    await db.flush()
    return ws


async def _developer(db, email: str, *, created: datetime) -> Developer:
    dev = Developer(email=email, name=email.split("@")[0], created_at=created)
    db.add(dev)
    await db.flush()
    return dev


@pytest.mark.asyncio
class TestGrowthCounts:
    async def test_totals_are_as_at_the_day_and_creations_are_that_day_only(
        self, db_session
    ):
        owner = await _developer(db_session, "owner@example.com", created=_ago(10))
        await _workspace(db_session, "old", created=_ago(10), owner=owner)
        await _workspace(db_session, "recent-a", created=_ago(2), owner=owner)
        await _workspace(db_session, "recent-b", created=_ago(2), owner=owner)
        await db_session.commit()

        service = PlatformStatsService(db_session)
        two_days_ago = (TODAY - timedelta(days=2)).date()
        await service.compute_day(two_days_ago)
        await service.compute_day(TODAY.date(), include_revenue=False)
        await db_session.commit()

        then = await service.on_day(two_days_ago)
        now = await service.on_day(TODAY.date())

        assert then.workspaces_total == 3
        assert then.workspaces_created == 2
        # Nothing was created today, but the three still exist.
        assert now.workspaces_total == 3
        assert now.workspaces_created == 0

    async def test_a_workspace_created_after_the_day_is_not_counted(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(10))
        await _workspace(db_session, "later", created=_ago(1), owner=owner)
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day((TODAY - timedelta(days=5)).date())
        await db_session.commit()

        row = await service.on_day((TODAY - timedelta(days=5)).date())
        assert row.workspaces_total == 0


@pytest.mark.asyncio
class TestActiveMeansSomebodyDidSomething:
    """The figure this replaces counted `WorkspaceMember.updated_at` — a
    membership row's modification time, which is not activity at all."""

    async def _two_workspaces(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        busy = await _workspace(db_session, "busy", created=_ago(60), owner=owner)
        quiet = await _workspace(db_session, "quiet", created=_ago(60), owner=owner)
        await db_session.commit()
        return busy, quiet, owner

    async def test_a_workspace_with_recent_work_is_active(self, db_session):
        busy, quiet, owner = await self._two_workspaces(db_session)
        db_session.add(
            EntityActivity(
                workspace_id=busy.id,
                entity_type="task",
                entity_id=str(busy.id),
                activity_type="created",
                actor_id=owner.id,
                created_at=_ago(3),
            )
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        assert (await service.latest()).workspaces_active_30d == 1

    async def test_work_older_than_the_window_does_not_count(self, db_session):
        busy, quiet, owner = await self._two_workspaces(db_session)
        db_session.add(
            EntityActivity(
                workspace_id=busy.id,
                entity_type="task",
                entity_id=str(busy.id),
                activity_type="created",
                actor_id=owner.id,
                created_at=_ago(45),
            )
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        assert (await service.latest()).workspaces_active_30d == 0

    async def test_spending_ai_budget_also_counts_as_activity(self, db_session):
        busy, quiet, owner = await self._two_workspaces(db_session)
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add(
            UsageRecord(
                customer_id=billing.id,
                workspace_id=quiet.id,
                usage_type="llm_input_tokens",
                provider="claude",
                total_tokens=100,
                created_at=_ago(2),
            )
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        assert (await service.latest()).workspaces_active_30d == 1


@pytest.mark.asyncio
class TestMoney:
    async def _seed_subscriptions(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        paying = await _workspace(db_session, "paying", created=_ago(60), owner=owner)
        trial = await _workspace(db_session, "trial", created=_ago(60), owner=owner)
        gone = await _workspace(db_session, "gone", created=_ago(60), owner=owner)
        db_session.add_all(
            [
                WorkspaceSubscription(
                    workspace_id=paying.id,
                    billing_model="per_seat",
                    status="active",
                    base_fee_monthly_cents=5000,
                    base_seats=3,
                    additional_seats=2,
                    price_per_additional_seat_cents=1000,
                ),
                WorkspaceSubscription(
                    workspace_id=trial.id,
                    billing_model="per_seat",
                    status="trialing",
                    base_fee_monthly_cents=5000,
                    additional_seats=0,
                    price_per_additional_seat_cents=1000,
                ),
                # A cancelled subscription contributes nothing.
                WorkspaceSubscription(
                    workspace_id=gone.id,
                    billing_model="per_seat",
                    status="canceled",
                    base_fee_monthly_cents=9900,
                    additional_seats=5,
                    price_per_additional_seat_cents=1000,
                ),
            ]
        )
        await db_session.commit()
        return paying, trial, gone

    async def test_mrr_is_base_fee_plus_extra_seats_for_paying_subscriptions_only(
        self, db_session
    ):
        await self._seed_subscriptions(db_session)
        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        row = await service.latest()
        # 5000 base + 2 extra seats × 1000. The trial and the cancelled one
        # are out.
        assert row.mrr_cents == 7000
        assert row.paying_workspaces == 1
        assert row.trialing_workspaces == 1
        assert row.subscriptions_by_status == {
            "active": 1,
            "trialing": 1,
            "canceled": 1,
        }

    async def test_only_active_billable_members_are_counted_as_seats(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        ws = await _workspace(db_session, "ws", created=_ago(60), owner=owner)
        billable = await _developer(db_session, "b@example.com", created=_ago(60))
        free = await _developer(db_session, "f@example.com", created=_ago(60))
        removed = await _developer(db_session, "r@example.com", created=_ago(60))
        db_session.add_all(
            [
                WorkspaceMember(
                    workspace_id=ws.id, developer_id=billable.id,
                    role="member", status="active", is_billable=True,
                ),
                WorkspaceMember(
                    workspace_id=ws.id, developer_id=free.id,
                    role="member", status="active", is_billable=False,
                ),
                WorkspaceMember(
                    workspace_id=ws.id, developer_id=removed.id,
                    role="member", status="removed", is_billable=True,
                ),
            ]
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        assert (await service.latest()).billable_seats == 1

    async def test_ai_spend_is_for_the_snapshot_day_alone(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        ws = await _workspace(db_session, "ws", created=_ago(60), owner=owner)
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add_all(
            [
                UsageRecord(
                    customer_id=billing.id, workspace_id=ws.id,
                    usage_type="llm_input_tokens", provider="claude",
                    total_tokens=100, base_cost_cents=10.0, total_cost_cents=13.0,
                    created_at=_ago(0),
                ),
                UsageRecord(
                    customer_id=billing.id, workspace_id=ws.id,
                    usage_type="llm_input_tokens", provider="gemini",
                    total_tokens=50, base_cost_cents=2.0, total_cost_cents=3.0,
                    created_at=_ago(0),
                ),
                # Yesterday's spend belongs to yesterday's row.
                UsageRecord(
                    customer_id=billing.id, workspace_id=ws.id,
                    usage_type="llm_input_tokens", provider="claude",
                    total_tokens=999, base_cost_cents=99.0, total_cost_cents=99.0,
                    created_at=_ago(1),
                ),
            ]
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        row = await service.latest()
        assert row.llm_requests == 2
        assert row.llm_tokens == 150
        assert row.llm_billed_cents == 16.0
        assert row.llm_base_cost_cents == 12.0
        assert row.llm_by_provider == {
            "claude": {"tokens": 100, "cents": 13.0},
            "gemini": {"tokens": 50, "cents": 3.0},
        }

    async def test_overdue_invoices_are_a_subset_of_open_ones(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add_all(
            [
                Invoice(
                    customer_id=billing.id, status="open", currency="usd",
                    total_cents=1000, amount_due_cents=1000,
                    due_date=TODAY + timedelta(days=5),
                ),
                Invoice(
                    customer_id=billing.id, status="open", currency="usd",
                    total_cents=2000, amount_due_cents=2000,
                    due_date=TODAY - timedelta(days=5),
                ),
                Invoice(
                    customer_id=billing.id, status="paid", currency="usd",
                    total_cents=9000, amount_due_cents=0,
                ),
            ]
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        row = await service.latest()
        assert (row.invoices_open, row.invoices_open_cents) == (2, 3000)
        assert (row.invoices_overdue, row.invoices_overdue_cents) == (1, 2000)


@pytest.mark.asyncio
class TestWhatAPastDayCannotKnow:
    async def test_a_historical_day_says_so_instead_of_stamping_todays_figures(
        self, db_session
    ):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        ws = await _workspace(db_session, "ws", created=_ago(60), owner=owner)
        db_session.add(
            WorkspaceSubscription(
                workspace_id=ws.id, billing_model="per_seat", status="active",
                base_fee_monthly_cents=5000,
            )
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day((TODAY - timedelta(days=5)).date())
        await db_session.commit()

        row = await service.on_day((TODAY - timedelta(days=5)).date())
        # Today's subscription exists, but it is not evidence about last week.
        assert row.mrr_cents == 0
        assert row.paying_workspaces == 0
        assert any("historical day" in note for note in row.notes)
        # The dated parts are still real.
        assert row.workspaces_total == 1

    async def test_recomputing_a_day_overwrites_it_rather_than_duplicating(
        self, db_session
    ):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        await _workspace(db_session, "one", created=_ago(60), owner=owner)
        await db_session.commit()

        service = PlatformStatsService(db_session)
        first = await service.compute_day(include_revenue=False)
        await db_session.commit()
        assert first.created is True

        await _workspace(db_session, "two", created=_ago(60), owner=owner)
        await db_session.commit()
        second = await service.compute_day(include_revenue=False)
        await db_session.commit()
        assert second.created is False

        rows = (await db_session.execute(select(PlatformDailyStats))).scalars().all()
        assert len(rows) == 1
        assert rows[0].workspaces_total == 2

    async def test_backfill_writes_one_row_per_day_and_leaves_today_alone(
        self, db_session
    ):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        await _workspace(db_session, "one", created=_ago(60), owner=owner)
        await db_session.commit()

        service = PlatformStatsService(db_session)
        results = await service.backfill(5)
        await db_session.commit()

        assert len(results) == 5
        days = {r.day for r in results}
        assert date.today() not in days
        assert all(
            any("historical day" in note for note in r.notes) for r in results
        )


@pytest.mark.asyncio
class TestSeries:
    async def test_the_series_comes_back_oldest_first(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        await _workspace(db_session, "one", created=_ago(60), owner=owner)
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.backfill(4)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        points = await service.series(30)
        assert [p.day for p in points] == sorted(p.day for p in points)
        assert len(points) == 5


@pytest.mark.asyncio
class TestCancellations:
    async def test_a_cancellation_is_counted_the_day_it_happened(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add_all(
            [
                Subscription(
                    customer_id=billing.id, status="canceled",
                    stripe_subscription_id="sub_today",
                    stripe_price_id="price_test",
                    canceled_at=TODAY - timedelta(hours=3),
                ),
                # Cancelled a fortnight ago: not today's news.
                Subscription(
                    customer_id=billing.id, status="canceled",
                    stripe_subscription_id="sub_old",
                    stripe_price_id="price_test",
                    canceled_at=TODAY - timedelta(days=14),
                ),
                Subscription(
                    customer_id=billing.id, status="active",
                    stripe_subscription_id="sub_live",
                    stripe_price_id="price_test",
                ),
            ]
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        assert (await service.latest()).subscriptions_canceled == 1

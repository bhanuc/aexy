"""The daily platform snapshot: what it records, and what it refuses to invent.

Every platform figure the admin area showed was a live query describing this
instant, so "is MRR growing?" had no answer and could not be given one after
the fact. These tests pin the two halves of the fix: the numbers written down
each day, and the honesty about the ones a past day cannot recover.
"""

from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from aexy.models.billing import CustomerBilling, Invoice, Subscription, UsageRecord
from aexy.models.developer import Developer
from aexy.models.entity_activity import EntityActivity
from aexy.models.platform_stats import PlatformDailyStats, PlatformModuleAdoption
from aexy.models.workspace import Workspace, WorkspaceMember, WorkspaceSubscription
from aexy.services import platform_stats_service as stats
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

    async def test_a_partial_day_is_flagged_by_a_column_not_by_its_prose(
        self, db_session
    ):
        """The chart and the KPI comparison both branch on this. Recovering it
        by searching `notes` for a phrase meant that rewording a log message
        silently turned every backfilled day back into real data."""
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        await _workspace(db_session, "one", created=_ago(60), owner=owner)
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.backfill(3)
        await service.compute_day(include_revenue=False)
        await db_session.commit()

        rows = {r.day: r for r in await service.series(30)}
        today = datetime.now(timezone.utc).date()
        assert rows[today].is_partial is False
        assert all(row.is_partial for day, row in rows.items() if day != today)

    async def test_a_backfill_does_not_downgrade_a_day_that_was_written_live(
        self, db_session
    ):
        """Yesterday's row was written while it was current, so it holds the
        subscription figures a later pass cannot recover. Re-running it marked
        it partial and the growth chart then erased its revenue line."""
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
        yesterday = (TODAY - timedelta(days=1)).date()

        # Stand in for "written while it was today": the same values a live
        # run would have recorded.
        await service.compute_day(include_revenue=False)
        await db_session.commit()
        live = await service.latest()
        live.day = yesterday
        await db_session.commit()

        assert live.mrr_cents == 5000
        assert live.is_partial is False

        # A second workspace appears, then the day is revisited.
        await _workspace(db_session, "late", created=_ago(1), owner=owner)
        await db_session.commit()
        await service.compute_day(yesterday)
        await db_session.commit()

        row = await service.on_day(yesterday)
        # What it could not recover is left exactly as it was found …
        assert row.mrr_cents == 5000
        assert row.is_partial is False
        assert not any("historical day" in note for note in row.notes)
        # … and what it *can* recompute is brought up to date.
        assert row.workspaces_total == 2


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

    async def test_a_cancellation_is_still_countable_after_the_fact(self, db_session):
        """`canceled_at` is dated, so churn is one of the few figures a past
        day can be asked about. It sat on a rolling `now - 24h` window inside
        the section that only runs for today, which left every backfilled day
        at zero and attributed a midnight run's count to the wrong day."""
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add_all(
            [
                Subscription(
                    customer_id=billing.id, status="canceled",
                    stripe_subscription_id="sub_four_days_ago",
                    stripe_price_id="price_test",
                    canceled_at=_ago(4),
                ),
                Subscription(
                    customer_id=billing.id, status="canceled",
                    stripe_subscription_id="sub_five_days_ago",
                    stripe_price_id="price_test",
                    canceled_at=_ago(5),
                ),
            ]
        )
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.backfill(7)
        await db_session.commit()

        by_day = {row.day: row.subscriptions_canceled for row in await service.series(30)}
        assert by_day[_ago(4).date()] == 1
        assert by_day[_ago(5).date()] == 1
        assert by_day[_ago(3).date()] == 0


@pytest.mark.asyncio
class TestModuleAdoption:
    """What workspaces *do*, as opposed to how many of them there are.

    Each signal is the table whose rows mean somebody did that module's work,
    not the one that means somebody switched it on — creating a chat channel
    is configuration and happens once; sending a message is use.
    """

    async def _two_workspaces_with_tasks(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        busy = await _workspace(db_session, "busy", created=_ago(60), owner=owner)
        quiet = await _workspace(db_session, "quiet", created=_ago(60), owner=owner)
        await db_session.commit()
        return busy, quiet, owner

    async def _task(self, db_session, workspace, *, created):
        from aexy.models.sprint import SprintTask

        task = SprintTask(
            workspace_id=workspace.id,
            title="work",
            status="todo",
            source_type="manual",
            source_id=str(uuid4()),
            created_at=created,
        )
        db_session.add(task)
        await db_session.flush()
        return task

    async def test_a_module_counts_the_workspaces_that_used_it(self, db_session):
        busy, quiet, _ = await self._two_workspaces_with_tasks(db_session)
        await self._task(db_session, busy, created=_ago(3))
        await self._task(db_session, busy, created=_ago(4))
        await db_session.commit()

        counts = await PlatformStatsService(db_session).compute_module_adoption()
        await db_session.commit()

        assert counts["sprints"] == 1

        row = (
            await db_session.execute(
                select(PlatformModuleAdoption).where(
                    PlatformModuleAdoption.module == "sprints"
                )
            )
        ).scalar_one()
        # Reach is workspaces; volume is things made. Two tasks in one
        # workspace is reach 1, volume 2.
        assert (row.workspaces_active, row.events) == (1, 2)
        assert row.window_days == stats.ACTIVITY_WINDOW_DAYS

    async def test_work_older_than_the_window_does_not_count(self, db_session):
        busy, _, _ = await self._two_workspaces_with_tasks(db_session)
        await self._task(db_session, busy, created=_ago(60))
        await db_session.commit()

        counts = await PlatformStatsService(db_session).compute_module_adoption()
        await db_session.commit()
        assert counts["sprints"] == 0

    async def test_recomputing_a_day_overwrites_rather_than_duplicating(
        self, db_session
    ):
        busy, _, _ = await self._two_workspaces_with_tasks(db_session)
        await self._task(db_session, busy, created=_ago(1))
        await db_session.commit()

        service = PlatformStatsService(db_session)
        await service.compute_module_adoption()
        await db_session.commit()
        await self._task(db_session, busy, created=_ago(1))
        await db_session.commit()
        await service.compute_module_adoption()
        await db_session.commit()

        rows = (
            (
                await db_session.execute(
                    select(PlatformModuleAdoption).where(
                        PlatformModuleAdoption.module == "sprints"
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(rows) == 1
        assert rows[0].events == 2

    async def test_modules_without_a_signal_are_named_not_counted(self):
        """A module nobody can measure must not read as a module nobody uses."""
        measured = set(stats._module_signals())
        assert measured.isdisjoint(stats.MODULES_WITHOUT_SIGNAL)
        assert "chat" in measured
        assert "uptime" in stats.MODULES_WITHOUT_SIGNAL


@pytest.mark.asyncio
class TestAiSpendDrilldown:
    async def _usage(self, db_session):
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
                    analysis_type="code_review", total_tokens=100,
                    base_cost_cents=10.0, total_cost_cents=13.0, created_at=_ago(1),
                ),
                UsageRecord(
                    customer_id=billing.id, workspace_id=ws.id,
                    usage_type="llm_input_tokens", provider="gemini",
                    analysis_type="summary", total_tokens=50,
                    base_cost_cents=2.0, total_cost_cents=3.0, created_at=_ago(1),
                ),
                # Outside the window.
                UsageRecord(
                    customer_id=billing.id, workspace_id=ws.id,
                    usage_type="llm_input_tokens", provider="claude",
                    analysis_type="code_review", total_tokens=999,
                    base_cost_cents=99.0, total_cost_cents=99.0, created_at=_ago(60),
                ),
            ]
        )
        await db_session.commit()
        return ws

    async def test_spend_is_grouped_by_day_provider_workspace_and_feature(
        self, db_session
    ):
        ws = await self._usage(db_session)
        result = await stats.ai_spend(db_session, days=7)

        assert len(result["by_day"]) == 1
        day = result["by_day"][0]
        assert day["billed_cents"] == 16.0
        assert day["base_cost_cents"] == 12.0
        assert day["tokens"] == 150
        assert day["providers"] == {"claude": 13.0, "gemini": 3.0}

        assert [w["workspace_id"] for w in result["top_workspaces"]] == [str(ws.id)]
        assert result["top_workspaces"][0]["billed_cents"] == 16.0

        features = {f["feature"]: f["billed_cents"] for f in result["by_feature"]}
        assert features == {"code_review": 13.0, "summary": 3.0}

    async def test_spend_from_a_deleted_workspace_still_has_a_label(self, db_session):
        """The cost outlives the workspace; it should not appear nameless."""
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add(
            UsageRecord(
                customer_id=billing.id,
                # Letters on purpose: SQLite gives the column NUMERIC affinity,
                # so an all-digit uuid comes back as a float.
                workspace_id="deadbeef-0000-4000-8000-00000000cafe",
                usage_type="llm_input_tokens", provider="claude",
                total_tokens=10, total_cost_cents=5.0, created_at=_ago(1),
            )
        )
        await db_session.commit()

        result = await stats.ai_spend(db_session, days=7)
        assert result["top_workspaces"][0]["workspace_name"] == "(deleted workspace)"


@pytest.mark.asyncio
class TestAlerts:
    """Deliberately short: a list that always has ten entries is one nobody
    reads. The plan-allowance alert is not covered here — `Plan` uses a
    PostgreSQL ARRAY column, so no plan row can exist in the SQLite test
    database."""

    async def test_no_alerts_when_there_is_nothing_to_chase(self, db_session):
        assert await stats.platform_alerts(db_session) == []

    async def test_an_overdue_invoice_is_raised(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add_all(
            [
                Invoice(
                    customer_id=billing.id, status="open", currency="usd",
                    total_cents=2000, amount_due_cents=2000,
                    due_date=TODAY - timedelta(days=2),
                ),
                # Open but not yet due: not a problem.
                Invoice(
                    customer_id=billing.id, status="open", currency="usd",
                    total_cents=1000, amount_due_cents=1000,
                    due_date=TODAY + timedelta(days=9),
                ),
            ]
        )
        await db_session.commit()

        alerts = {a["kind"]: a for a in await stats.platform_alerts(db_session)}
        assert alerts["invoices_overdue"]["count"] == 1
        assert alerts["invoices_overdue"]["amount_cents"] == 2000
        assert alerts["invoices_overdue"]["severity"] == "high"

    async def test_a_subscription_stripe_could_not_charge_is_raised(self, db_session):
        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        billing = CustomerBilling(developer_id=owner.id)
        db_session.add(billing)
        await db_session.flush()
        db_session.add(
            Subscription(
                customer_id=billing.id, status="past_due",
                stripe_subscription_id="sub_x", stripe_price_id="price_x",
            )
        )
        await db_session.commit()

        alerts = {a["kind"]: a for a in await stats.platform_alerts(db_session)}
        assert alerts["subscriptions_unpaid"]["count"] == 1

    async def test_a_spend_spike_is_measured_against_the_trailing_week(
        self, db_session
    ):
        today = TODAY.date()
        db_session.add_all(
            [
                PlatformDailyStats(day=today - timedelta(days=n), llm_billed_cents=100.0)
                for n in range(1, 6)
            ]
        )
        db_session.add(PlatformDailyStats(day=today, llm_billed_cents=500.0))
        await db_session.commit()

        alerts = {a["kind"]: a for a in await stats.platform_alerts(db_session)}
        assert alerts["llm_spend_spike"]["amount_cents"] == 500.0
        assert alerts["llm_spend_spike"]["baseline_cents"] == 100.0

    async def test_a_quiet_run_of_days_is_not_a_spike(self, db_session):
        """Nothing divided by nothing is not a hundredfold increase."""
        today = TODAY.date()
        db_session.add_all(
            [
                PlatformDailyStats(day=today - timedelta(days=n), llm_billed_cents=0.0)
                for n in range(1, 6)
            ]
        )
        db_session.add(PlatformDailyStats(day=today, llm_billed_cents=5.0))
        await db_session.commit()

        kinds = {a["kind"] for a in await stats.platform_alerts(db_session)}
        assert "llm_spend_spike" not in kinds


@pytest.mark.asyncio
class TestWorkspaceDetail:
    async def test_an_unknown_workspace_is_none_rather_than_an_error(self, db_session):
        assert (
            await stats.workspace_detail(
                db_session, "00000000-0000-4000-8000-000000000000"
            )
            is None
        )

    async def test_one_customer_in_one_place(self, db_session):
        from aexy.models.sprint import SprintTask

        owner = await _developer(db_session, "owner@example.com", created=_ago(60))
        ws = await _workspace(db_session, "ws", created=_ago(60), owner=owner)
        member = await _developer(db_session, "m@example.com", created=_ago(60))
        db_session.add_all(
            [
                WorkspaceMember(
                    workspace_id=ws.id, developer_id=owner.id,
                    role="owner", status="active", is_billable=True,
                ),
                WorkspaceMember(
                    workspace_id=ws.id, developer_id=member.id,
                    role="member", status="active", is_billable=False,
                ),
                SprintTask(
                    workspace_id=ws.id, title="work", status="todo",
                    source_type="manual", source_id=str(uuid4()),
                    created_at=_ago(2),
                ),
            ]
        )
        await db_session.commit()

        detail = await stats.workspace_detail(db_session, str(ws.id))

        assert detail["name"] == "ws"
        assert detail["owner_email"] == "owner@example.com"
        assert detail["member_count"] == 2
        assert detail["billable_seats"] == 1
        # Only modules with something in them, so the page shows use rather
        # than a wall of zeros.
        assert detail["module_usage"] == {"sprints": 1}


class TestKpiComparison:
    """A backfilled day stores zero for what it could not recover. Comparing
    against it reported the whole of MRR as growth since last month — the same
    mistake `is_partial` exists to prevent, made on the headline cards while
    the chart beside them was already breaking its line."""

    class _Row:
        def __init__(self, **fields):
            self.is_partial = fields.pop("is_partial", False)
            for key, value in fields.items():
                setattr(self, key, value)

    def test_a_complete_previous_day_is_compared(self):
        from aexy.api.platform_admin import _kpi

        kpi = _kpi(self._Row(mrr_cents=1500), self._Row(mrr_cents=1000), "mrr_cents")

        assert kpi.previous == 1000
        assert kpi.delta == 500
        assert kpi.delta_pct == 50.0

    def test_a_partial_previous_day_offers_no_comparison_for_money(self):
        from aexy.api.platform_admin import _kpi

        kpi = _kpi(
            self._Row(mrr_cents=1500),
            self._Row(mrr_cents=0, is_partial=True),
            "mrr_cents",
        )

        assert kpi.value == 1500
        assert kpi.previous is None
        assert kpi.delta is None

    def test_a_partial_previous_day_still_compares_what_it_does_know(self):
        """Signups and AI spend are dated, so a backfilled day recovers them in
        full. Only the figures that describe *now* are missing."""
        from aexy.api.platform_admin import _kpi

        kpi = _kpi(
            self._Row(workspaces_total=40),
            self._Row(workspaces_total=25, is_partial=True),
            "workspaces_total",
        )

        assert kpi.previous == 25
        assert kpi.delta == 15

    def test_no_previous_day_at_all_offers_no_comparison(self):
        from aexy.api.platform_admin import _kpi

        kpi = _kpi(self._Row(mrr_cents=1500), None, "mrr_cents")

        assert kpi.previous is None

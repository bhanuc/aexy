"""Shapes for the platform overview and its daily series."""

from datetime import date, datetime

from pydantic import BaseModel, Field


class PlatformKpi(BaseModel):
    """One headline number, next to what it was on the comparison day.

    `previous` is None when there is no snapshot that far back — a new
    install, or a figure that predates the table. The UI must show "no
    comparison yet" rather than a fabricated 0% change.
    """

    value: float
    previous: float | None = None
    delta: float | None = None
    delta_pct: float | None = None


class PlatformOverviewResponse(BaseModel):
    #: The day the snapshot describes. None before the first one is written.
    as_of: date | None = None
    computed_at: datetime | None = None
    #: Nothing has been written for more than a day and a half — the daily job
    #: is not running, and every number below is older than it looks.
    is_stale: bool = False
    #: How far back `previous` looks on each KPI.
    comparison_days: int = 30

    mrr_cents: PlatformKpi
    revenue_cents: PlatformKpi
    margin_cents: PlatformKpi
    base_cost_cents: PlatformKpi
    paying_workspaces: PlatformKpi
    trialing_workspaces: PlatformKpi
    workspaces_total: PlatformKpi
    workspaces_active_30d: PlatformKpi
    developers_total: PlatformKpi
    billable_seats: PlatformKpi
    llm_billed_cents: PlatformKpi

    subscriptions_by_status: dict[str, int] = Field(default_factory=dict)
    revenue_by_plan_tier: dict[str, float] = Field(default_factory=dict)
    revenue_by_billing_model: dict[str, float] = Field(default_factory=dict)
    #: How many active workspaces sit on each tier right now, paying or not.
    workspaces_by_plan_tier: dict[str, int] = Field(default_factory=dict)

    invoices_open: int = 0
    invoices_open_cents: float = 0.0
    invoices_overdue: int = 0
    invoices_overdue_cents: float = 0.0

    #: What the snapshot could not work out. Surfaced, not swallowed.
    notes: list[str] = Field(default_factory=list)


class PlatformStatsPoint(BaseModel):
    """One day on the growth and revenue charts."""

    day: date
    workspaces_total: int
    workspaces_created: int
    workspaces_active_30d: int
    developers_total: int
    developers_created: int
    paying_workspaces: int
    trialing_workspaces: int
    subscriptions_canceled: int
    billable_seats: int
    mrr_cents: float
    revenue_cents: float
    base_cost_cents: float
    margin_cents: float
    llm_requests: int
    llm_tokens: int
    llm_billed_cents: float
    llm_base_cost_cents: float
    #: True for a day filled in after the fact, whose subscription, seat and
    #: revenue figures are zero because they are not recoverable. A chart must
    #: break the line here rather than draw a cliff to zero.
    is_partial: bool = False


class PlatformStatsSeriesResponse(BaseModel):
    days: int
    points: list[PlatformStatsPoint] = Field(default_factory=list)


class PlatformSnapshotRefreshResponse(BaseModel):
    day: date
    created: bool
    backfilled: int = 0
    notes: list[str] = Field(default_factory=list)

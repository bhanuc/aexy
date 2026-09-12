"""Shapes for the platform overview and its daily series."""

from datetime import date, datetime
from typing import Any

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
    #: A backfill is queued rather than run in the request: a year of it is
    #: thousands of queries in one transaction, and a proxy timeout would roll
    #: back the lot. False when one was asked for and the queue was unreachable.
    backfill_queued: bool = False
    #: How many days the queued backfill will cover. Zero when none was queued.
    backfill_days: int = 0
    notes: list[str] = Field(default_factory=list)


# =============================================================================
# Module adoption
# =============================================================================


class ModuleAdoptionPoint(BaseModel):
    day: date
    module: str
    workspaces_active: int
    #: How many things were created, so a module carrying real volume reads
    #: differently from one that saw a single row all month.
    events: int
    window_days: int


class ModuleAdoptionResponse(BaseModel):
    days: int
    window_days: int
    #: Workspaces that did *anything* inside the same trailing window each
    #: point is counted over — the denominator for a module's share. It has to
    #: be this and not "workspaces that exist", or a platform with dormant
    #: tenants reports every module as barely adopted.
    active_workspaces: int
    #: Every workspace that has not been switched off, for context beside the
    #: share: "9 of 30 active, 112 in total" is a different story from
    #: "9 of 30 active, 31 in total".
    total_workspaces: int = 0
    points: list[ModuleAdoptionPoint] = Field(default_factory=list)
    #: Modules with nothing that separates "somebody used this" from "somebody
    #: switched it on". Named rather than reported as zero.
    not_measured: list[str] = Field(default_factory=list)


# =============================================================================
# AI spend
# =============================================================================


class AiSpendDay(BaseModel):
    day: str
    billed_cents: float
    base_cost_cents: float
    tokens: int
    providers: dict[str, float] = Field(default_factory=dict)


class AiSpendWorkspace(BaseModel):
    workspace_id: str
    workspace_name: str
    billed_cents: float
    base_cost_cents: float
    tokens: int


class AiSpendFeature(BaseModel):
    feature: str
    billed_cents: float
    requests: int


class AiSpendResponse(BaseModel):
    days: int
    by_day: list[AiSpendDay] = Field(default_factory=list)
    top_workspaces: list[AiSpendWorkspace] = Field(default_factory=list)
    by_feature: list[AiSpendFeature] = Field(default_factory=list)


# =============================================================================
# Alerts and the per-workspace view
# =============================================================================


class PlatformAlert(BaseModel):
    """One thing worth looking at. Kept deliberately short — a list that
    always has ten entries is a list nobody reads."""

    kind: str
    severity: str
    count: int | None = None
    amount_cents: float | None = None
    baseline_cents: float | None = None
    href: str | None = None
    workspaces: list[dict[str, Any]] = Field(default_factory=list)


class PlatformAlertsResponse(BaseModel):
    alerts: list[PlatformAlert] = Field(default_factory=list)


class WorkspaceDetailResponse(BaseModel):
    workspace_id: str
    name: str
    slug: str
    is_active: bool
    created_at: datetime
    owner_name: str | None = None
    owner_email: str | None = None
    plan_name: str | None = None
    plan_tier: str | None = None
    has_plan_override: bool = False
    billing_model: str | None = None
    subscription_status: str | None = None
    current_period_end: datetime | None = None
    member_count: int = 0
    billable_seats: int = 0
    llm_requests_this_period: int = 0
    llm_tokens_this_period: int = 0
    llm_billed_cents_this_period: float = 0.0
    llm_base_cost_cents_this_period: float = 0.0
    #: module id -> things created in the trailing window. Absent means none.
    module_usage: dict[str, int] = Field(default_factory=dict)
    last_activity_at: datetime | None = None

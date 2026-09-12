"""A daily snapshot of the whole platform.

Every platform-level figure the admin area shows is computed live and
describes this instant: how many workspaces exist, what this month's bill
comes to. None of it can be asked about the past. "Was MRR growing in June?"
and "how many workspaces cancelled last quarter?" cannot be reconstructed
afterwards — nothing records that a workspace *was* active thirty days ago,
and a plan's price today is not the price it was billed at.

So a row is written once a day and kept. The reads are all "the last N days";
the write is idempotent per day, so the job can be re-run and history can be
backfilled where the source rows still support it.
"""

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import BigInteger, Date, DateTime, Float, Integer, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from aexy.core.database import Base


class PlatformDailyStats(Base):
    """One UTC day of platform-wide numbers."""

    __tablename__ = "platform_daily_stats"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4())
    )
    day: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)

    # --- growth -----------------------------------------------------------
    workspaces_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workspaces_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    workspaces_active_30d: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    developers_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    developers_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- subscriptions ----------------------------------------------------
    paying_workspaces: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    trialing_workspaces: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    subscriptions_canceled: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    billable_seats: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    #: Recurring money only — base fee plus seats. Deliberately excludes usage,
    #: so a heavy month of AI does not read as growth in subscriptions.
    mrr_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    subscriptions_by_status: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # --- money ------------------------------------------------------------
    revenue_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    base_cost_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    margin_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    #: How many workspaces the revenue figures cover. One that could not be
    #: priced is left out of the total rather than counted as zero.
    revenue_workspace_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    revenue_by_plan_tier: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    revenue_by_billing_model: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    top_workspaces: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list
    )

    # --- AI spend for this day alone --------------------------------------
    llm_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_tokens: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    llm_base_cost_cents: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    llm_billed_cents: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_by_provider: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    # --- unpaid money -----------------------------------------------------
    invoices_open: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invoices_open_cents: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )
    invoices_overdue: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    invoices_overdue_cents: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0
    )

    #: Sections that could not be computed, so a zero meaning "we did not
    #: know" is never read as a zero meaning "there was none".
    notes: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<PlatformDailyStats {self.day} mrr={self.mrr_cents}>"


__all__ = ["PlatformDailyStats"]

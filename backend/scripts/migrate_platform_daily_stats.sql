-- One row per day describing the whole platform: how many workspaces and
-- people there are, how many were active, what is being billed, and what the
-- AI cost to serve.
--
-- Every platform-level number the admin area shows today is "right now" or
-- "this month" — there is no way to ask what MRR was in June, whether signups
-- are accelerating, or how many workspaces cancelled last quarter. Those
-- questions cannot be answered from the live tables afterwards: nothing
-- records that a workspace *was* active thirty days ago, and a plan's price
-- today is not the price it was billed at. So the answer is written down once
-- a day and kept.
--
-- It also fixes a load problem. `/platform-admin/billing/totals` loops every
-- active workspace and runs a full billing breakdown per workspace on every
-- request, uncached. That is the same work this job does — once, overnight —
-- so the endpoint can read a single row instead.
CREATE TABLE IF NOT EXISTS platform_daily_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- The UTC day being described. One row per day; recomputing a day
    -- overwrites it, so the job is safe to re-run and to backfill.
    day DATE NOT NULL UNIQUE,

    -- Growth
    workspaces_total INTEGER NOT NULL DEFAULT 0,
    workspaces_created INTEGER NOT NULL DEFAULT 0,
    workspaces_active_30d INTEGER NOT NULL DEFAULT 0,
    developers_total INTEGER NOT NULL DEFAULT 0,
    developers_created INTEGER NOT NULL DEFAULT 0,

    -- Subscriptions. `mrr_cents` is the recurring part only — base fee plus
    -- seats — so it does not swing with a heavy month of usage.
    paying_workspaces INTEGER NOT NULL DEFAULT 0,
    trialing_workspaces INTEGER NOT NULL DEFAULT 0,
    subscriptions_canceled INTEGER NOT NULL DEFAULT 0,
    billable_seats INTEGER NOT NULL DEFAULT 0,
    mrr_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    subscriptions_by_status JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- What the month-to-date bill comes to across every workspace, what it
    -- cost us to serve, and the difference. Revenue is charged-for money;
    -- base cost is what the providers charged.
    revenue_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    base_cost_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    margin_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    -- How many workspaces the revenue figures actually cover. A workspace
    -- that could not be priced is left out of the total rather than counted
    -- as zero, and this is how the page can say so.
    revenue_workspace_count INTEGER NOT NULL DEFAULT 0,
    revenue_by_plan_tier JSONB NOT NULL DEFAULT '{}'::jsonb,
    revenue_by_billing_model JSONB NOT NULL DEFAULT '{}'::jsonb,
    top_workspaces JSONB NOT NULL DEFAULT '[]'::jsonb,

    -- AI spend for this day alone, so a spike is visible on the day it
    -- happened rather than smeared across the month.
    llm_requests INTEGER NOT NULL DEFAULT 0,
    llm_tokens BIGINT NOT NULL DEFAULT 0,
    llm_base_cost_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    llm_billed_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    llm_by_provider JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Unpaid money, as at the snapshot.
    invoices_open INTEGER NOT NULL DEFAULT 0,
    invoices_open_cents DOUBLE PRECISION NOT NULL DEFAULT 0,
    invoices_overdue INTEGER NOT NULL DEFAULT 0,
    invoices_overdue_cents DOUBLE PRECISION NOT NULL DEFAULT 0,

    -- Which parts of the snapshot could not be computed, and why. A failed
    -- section leaves zeros, and a zero that means "we did not know" must not
    -- read as a zero that means "there was none".
    notes JSONB NOT NULL DEFAULT '[]'::jsonb,

    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Every read is "the last N days, newest first".
CREATE INDEX IF NOT EXISTS idx_platform_daily_stats_day
    ON platform_daily_stats (day DESC);

SELECT
    (SELECT count(*) FROM workspaces) AS workspaces,
    (SELECT count(*) FROM developers) AS developers,
    (SELECT count(*) FROM platform_daily_stats) AS snapshots_existing;

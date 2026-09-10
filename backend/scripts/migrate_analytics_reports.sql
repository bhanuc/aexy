-- Analytics Reports Migration
-- Creates the reporting/analytics tables backing models/analytics.py:
--   custom_reports, scheduled_reports, export_jobs, predictive_insights
-- These models were registered in models/__init__.py but never had a
-- migration, so every /api/v1/reports and /api/v1/exports call 500'd with
-- "relation ... does not exist". This creates them idempotently.
--
-- `custom_reports.organization_id` below is the shape this table had when this
-- migration was written. It has since been replaced by `workspace_id`
-- (migrate_reports_workspace_scope.sql) and dropped
-- (migrate_drop_reports_organization_id.sql), both of which run after this one
-- alphabetically. So on an existing database this still describes the table it
-- created, and its column is removed two migrations later.
--
-- On a *fresh* database it never gets that far. `main.py` runs create_all at
-- startup, so by the time the runner reaches this file `custom_reports`
-- already exists in the current model's shape — with `workspace_id`, without
-- `organization_id`. The CREATE TABLE below is then a no-op, and the index on
-- `organization_id` used to fail with `column "organization_id" does not
-- exist`, which stopped the runner dead at migration 29 of 185. Its index is
-- therefore guarded on the column being present. Nothing is lost by skipping
-- it: the column it indexes is dropped before this run finishes.

-- 1. Custom reports ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS custom_reports (
    id              UUID PRIMARY KEY,
    creator_id      UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    organization_id UUID,

    name            VARCHAR(255) NOT NULL,
    description     TEXT,

    widgets         JSONB NOT NULL DEFAULT '[]',
    filters         JSONB NOT NULL DEFAULT '{}',
    layout          JSONB NOT NULL DEFAULT '{}',

    is_template     BOOLEAN NOT NULL DEFAULT FALSE,
    is_public       BOOLEAN NOT NULL DEFAULT FALSE,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_custom_reports_creator_id
    ON custom_reports(creator_id);
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'custom_reports' AND column_name = 'organization_id'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_custom_reports_organization_id
            ON custom_reports(organization_id);
    END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_custom_reports_is_template
    ON custom_reports(is_template);

-- 2. Scheduled reports ------------------------------------------------------
CREATE TABLE IF NOT EXISTS scheduled_reports (
    id              UUID PRIMARY KEY,
    report_id       UUID NOT NULL REFERENCES custom_reports(id) ON DELETE CASCADE,

    schedule        VARCHAR(20) NOT NULL,   -- "daily", "weekly", "monthly"
    day_of_week     INTEGER,                -- 0-6 for weekly
    day_of_month    INTEGER,                -- 1-31 for monthly
    time_utc        VARCHAR(5) NOT NULL,    -- "09:00"

    recipients      JSONB NOT NULL DEFAULT '[]',
    delivery_method VARCHAR(20) NOT NULL,   -- "email", "slack", "both"
    export_format   VARCHAR(10) NOT NULL,   -- "pdf", "csv", "json"

    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    last_sent_at    TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ NOT NULL,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scheduled_reports_report_id
    ON scheduled_reports(report_id);
-- Delivery worker polls active schedules whose next_run_at is due.
CREATE INDEX IF NOT EXISTS idx_scheduled_reports_due
    ON scheduled_reports(is_active, next_run_at);

-- 3. Export jobs ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS export_jobs (
    id              UUID PRIMARY KEY,
    requested_by    UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,

    export_type     VARCHAR(50) NOT NULL,   -- "report", "developer_profile", "team_analytics"
    format          VARCHAR(10) NOT NULL,   -- "pdf", "csv", "json", "xlsx"

    config          JSONB NOT NULL DEFAULT '{}',

    status          VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending/processing/completed/failed
    file_path       VARCHAR(500),
    file_size_bytes INTEGER,
    error_message   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_export_jobs_requested_by
    ON export_jobs(requested_by);
CREATE INDEX IF NOT EXISTS idx_export_jobs_status
    ON export_jobs(status);
-- Cleanup job scans for expired rows.
CREATE INDEX IF NOT EXISTS idx_export_jobs_expires_at
    ON export_jobs(expires_at);

-- 4. Predictive insights ----------------------------------------------------
CREATE TABLE IF NOT EXISTS predictive_insights (
    id                 UUID PRIMARY KEY,
    developer_id       UUID REFERENCES developers(id) ON DELETE CASCADE,  -- null for team-level
    team_id            UUID,

    insight_type       VARCHAR(50) NOT NULL,   -- attrition_risk, performance_trajectory, ...

    risk_score         DOUBLE PRECISION NOT NULL,  -- 0.0 - 1.0
    confidence         DOUBLE PRECISION NOT NULL,  -- 0.0 - 1.0
    risk_level         VARCHAR(20),                -- low/moderate/high/critical
    factors            JSONB NOT NULL DEFAULT '[]',
    recommendations    JSONB NOT NULL DEFAULT '[]',
    raw_analysis       JSONB NOT NULL DEFAULT '{}',

    data_window_days   INTEGER NOT NULL,
    generated_by_model VARCHAR(100) NOT NULL,
    generated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at         TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_predictive_insights_developer_id
    ON predictive_insights(developer_id);
CREATE INDEX IF NOT EXISTS idx_predictive_insights_team_id
    ON predictive_insights(team_id);
CREATE INDEX IF NOT EXISTS idx_predictive_insights_insight_type
    ON predictive_insights(insight_type);

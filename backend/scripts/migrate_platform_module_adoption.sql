-- Which modules are actually being used, per day, across the platform.
--
-- The admin area could say how many workspaces exist and what they pay. It
-- could not say what any of them *do* — whether the CRM is carrying real work
-- or whether Service Desk is the only thing anyone opens. That is the question
-- product planning needs and the one nothing answered.
--
-- Like the rest of the platform snapshot this has to be written down as it
-- happens: "how many workspaces used Hiring in June" cannot be recovered from
-- the live tables once the window has passed.
--
-- One row per (day, module). Recomputing a day overwrites it, so the job is
-- safe to re-run.
CREATE TABLE IF NOT EXISTS platform_module_adoption (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    day DATE NOT NULL,
    -- An id from the app catalog: sprints, crm, service_desk, …
    module VARCHAR(64) NOT NULL,

    -- Workspaces that created something in this module during the trailing
    -- window, and how many things they created. The count says whether the
    -- module is carrying real volume or one row a month.
    workspaces_active INTEGER NOT NULL DEFAULT 0,
    events INTEGER NOT NULL DEFAULT 0,

    -- How far back `workspaces_active` looked, so a later change to the
    -- window does not silently reinterpret old rows.
    window_days INTEGER NOT NULL DEFAULT 30,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_platform_module_adoption_day_module UNIQUE (day, module)
);

CREATE INDEX IF NOT EXISTS idx_platform_module_adoption_day
    ON platform_module_adoption (day DESC);
CREATE INDEX IF NOT EXISTS idx_platform_module_adoption_module
    ON platform_module_adoption (module, day DESC);

SELECT
    (SELECT count(*) FROM workspaces WHERE is_active) AS active_workspaces,
    (SELECT count(*) FROM platform_module_adoption) AS adoption_rows_existing;

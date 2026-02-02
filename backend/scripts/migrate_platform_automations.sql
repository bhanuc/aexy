-- Migration: Platform-Wide Automations
-- Extends CRM automations to support multiple modules (CRM, Tickets, Hiring, etc.)
-- Run this migration to enable platform-wide automation capabilities

-- ===========================================================================
-- Add module column to crm_automations table
-- ===========================================================================

-- Add module column with default 'crm' for backwards compatibility
ALTER TABLE crm_automations
ADD COLUMN IF NOT EXISTS module VARCHAR(50) NOT NULL DEFAULT 'crm';

-- Add module_config column for module-specific configuration
ALTER TABLE crm_automations
ADD COLUMN IF NOT EXISTS module_config JSONB NOT NULL DEFAULT '{}';

-- Add module column to automation runs for filtering
ALTER TABLE crm_automation_runs
ADD COLUMN IF NOT EXISTS module VARCHAR(50) NOT NULL DEFAULT 'crm';

-- ===========================================================================
-- Create indexes for module filtering
-- ===========================================================================

-- Index for filtering automations by workspace and module
CREATE INDEX IF NOT EXISTS idx_automations_workspace_module
ON crm_automations(workspace_id, module);

-- Index for filtering automation runs by module
CREATE INDEX IF NOT EXISTS idx_automation_runs_module
ON crm_automation_runs(module);

-- Composite index for common queries
CREATE INDEX IF NOT EXISTS idx_automations_workspace_module_active
ON crm_automations(workspace_id, module, is_active)
WHERE is_active = TRUE;

-- ===========================================================================
-- Create views for new API (automations without crm_ prefix)
-- These views provide a cleaner interface for the platform-wide automations API
-- ===========================================================================

-- Main automations view
CREATE OR REPLACE VIEW automations AS
SELECT
    id,
    workspace_id,
    name,
    description,
    object_id,
    module,
    module_config,
    trigger_type,
    trigger_config,
    conditions,
    actions,
    error_handling,
    is_active,
    run_limit_per_month,
    runs_this_month,
    total_runs,
    successful_runs,
    failed_runs,
    last_run_at,
    created_by_id,
    created_at,
    updated_at
FROM crm_automations;

-- Automation runs view
CREATE OR REPLACE VIEW automation_runs AS
SELECT
    id,
    automation_id,
    module,
    record_id,
    trigger_data,
    status,
    steps_executed,
    error_message,
    started_at,
    completed_at,
    duration_ms,
    created_at
FROM crm_automation_runs;

-- ===========================================================================
-- Update existing CRM automations to set module explicitly
-- ===========================================================================

UPDATE crm_automations
SET module = 'crm'
WHERE module IS NULL OR module = '';

UPDATE crm_automation_runs
SET module = 'crm'
WHERE module IS NULL OR module = '';

-- ===========================================================================
-- Add comments for documentation
-- ===========================================================================

COMMENT ON COLUMN crm_automations.module IS 'Module this automation belongs to: crm, tickets, hiring, email_marketing, uptime, sprints, forms, booking';
COMMENT ON COLUMN crm_automations.module_config IS 'Module-specific configuration (JSON)';
COMMENT ON COLUMN crm_automation_runs.module IS 'Module this run belongs to (denormalized for efficient filtering)';
COMMENT ON VIEW automations IS 'Platform-wide view of all automations across modules';
COMMENT ON VIEW automation_runs IS 'Platform-wide view of all automation runs across modules';

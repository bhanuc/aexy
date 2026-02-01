-- Migration: Automation Agent Triggers and Executions
-- Enables spawning AI agents from automations/workflows with full context passing

-- =============================================================================
-- AUTOMATION AGENT TRIGGERS
-- =============================================================================
-- Configures which agents should be triggered by automations at specific points

CREATE TABLE IF NOT EXISTS automation_agent_triggers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    automation_id UUID NOT NULL REFERENCES crm_automations(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES crm_agents(id) ON DELETE CASCADE,

    -- When to trigger: 'on_start', 'on_condition_match', 'as_action'
    trigger_point VARCHAR(50) NOT NULL,

    -- Configuration for the trigger (e.g., specific conditions)
    trigger_config JSONB DEFAULT '{}',

    -- Map automation context fields to agent input fields
    -- Example: {"contact_name": "record.values.name", "company": "record.values.company"}
    input_mapping JSONB DEFAULT '{}',

    -- Whether to wait for agent completion before continuing automation
    wait_for_completion BOOLEAN DEFAULT FALSE,

    -- Max time to wait for agent completion (seconds)
    timeout_seconds INTEGER DEFAULT 300,

    -- Whether this trigger is active
    is_active BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- Each agent can only be triggered once per trigger point per automation
    CONSTRAINT uq_automation_agent_trigger UNIQUE(automation_id, agent_id, trigger_point)
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_automation_agent_triggers_automation
    ON automation_agent_triggers(automation_id)
    WHERE is_active = TRUE;

CREATE INDEX IF NOT EXISTS idx_automation_agent_triggers_agent
    ON automation_agent_triggers(agent_id);

-- =============================================================================
-- AUTOMATION AGENT EXECUTIONS
-- =============================================================================
-- Tracks individual agent executions triggered by automations/workflows

CREATE TABLE IF NOT EXISTS automation_agent_executions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Link to the automation run (for simple automations)
    automation_run_id UUID REFERENCES crm_automation_runs(id) ON DELETE SET NULL,

    -- Link to workflow execution (for visual workflow automations)
    workflow_execution_id UUID REFERENCES crm_workflow_executions(id) ON DELETE SET NULL,

    -- Link to specific workflow step (for agent nodes in workflows)
    workflow_step_id UUID REFERENCES crm_workflow_execution_steps(id) ON DELETE SET NULL,

    -- The agent that was executed
    agent_id UUID NOT NULL REFERENCES crm_agents(id) ON DELETE CASCADE,

    -- Link to the actual agent execution record for detailed trace
    agent_execution_id UUID REFERENCES crm_agent_executions(id) ON DELETE SET NULL,

    -- When in the automation this agent was triggered
    trigger_point VARCHAR(50) NOT NULL,

    -- Input context passed to the agent
    input_context JSONB DEFAULT '{}',

    -- Output/result from the agent
    output_result JSONB,

    -- Execution status: 'pending', 'running', 'completed', 'failed', 'timeout'
    status VARCHAR(20) DEFAULT 'pending',

    -- Error message if failed
    error_message TEXT,

    -- Timing
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,

    -- Record timestamp
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes for efficient lookups
CREATE INDEX IF NOT EXISTS idx_auto_agent_exec_run
    ON automation_agent_executions(automation_run_id)
    WHERE automation_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auto_agent_exec_workflow
    ON automation_agent_executions(workflow_execution_id)
    WHERE workflow_execution_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_auto_agent_exec_agent
    ON automation_agent_executions(agent_id);

CREATE INDEX IF NOT EXISTS idx_auto_agent_exec_status
    ON automation_agent_executions(status)
    WHERE status IN ('pending', 'running');

-- =============================================================================
-- TRIGGER FOR UPDATED_AT
-- =============================================================================

-- Create trigger function if it doesn't exist
CREATE OR REPLACE FUNCTION update_automation_agent_trigger_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Attach trigger to automation_agent_triggers
DROP TRIGGER IF EXISTS trg_automation_agent_triggers_updated_at ON automation_agent_triggers;
CREATE TRIGGER trg_automation_agent_triggers_updated_at
    BEFORE UPDATE ON automation_agent_triggers
    FOR EACH ROW
    EXECUTE FUNCTION update_automation_agent_trigger_updated_at();

-- Agent Invocations Migration
-- Adds tables for tracking agent invocations from Aexy (comments, direct calls)
-- and the human review workflow for agent actions.

-- ============================================
-- AGENT INVOCATIONS (from Aexy mentions/calls)
-- ============================================

CREATE TABLE IF NOT EXISTS mailagent_agent_invocations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES mailagent_agents(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL,

    -- Source context (from Aexy)
    source_type VARCHAR(50) NOT NULL,  -- 'comment', 'direct', 'scheduled', 'webhook'
    entity_type VARCHAR(50),           -- 'task', 'ticket', 'crm_record', 'booking', etc.
    entity_id UUID,
    activity_id UUID,                   -- Reference to Aexy's entity_activities.id

    -- The invoking user
    invoked_by UUID NOT NULL,
    invoked_by_name VARCHAR(255),

    -- The instruction/prompt given to the agent
    instruction TEXT,
    context JSONB DEFAULT '{}',

    -- Status
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, processing, completed, failed
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    error TEXT,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_invocations_agent ON mailagent_agent_invocations(agent_id);
CREATE INDEX IF NOT EXISTS idx_invocations_workspace ON mailagent_agent_invocations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_invocations_status ON mailagent_agent_invocations(status);
CREATE INDEX IF NOT EXISTS idx_invocations_entity ON mailagent_agent_invocations(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_invocations_pending ON mailagent_agent_invocations(status)
    WHERE status IN ('pending', 'processing');

-- ============================================
-- AGENT ACTIONS (proposed actions for review)
-- ============================================

CREATE TABLE IF NOT EXISTS mailagent_agent_actions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    invocation_id UUID NOT NULL REFERENCES mailagent_agent_invocations(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES mailagent_agents(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL,

    -- Action type and details
    action_type VARCHAR(50) NOT NULL,
    -- Types: create_task, update_task, move_task, create_crm_record, update_crm_record,
    --        schedule_meeting, send_email, update_ticket, add_comment, escalate,
    --        create_document, update_document, link_entities

    -- Target entity (if modifying something)
    target_entity_type VARCHAR(50),
    target_entity_id UUID,

    -- The proposed action payload
    action_payload JSONB NOT NULL DEFAULT '{}',

    -- Agent's reasoning
    confidence DECIMAL(3,2) NOT NULL,
    reasoning TEXT,

    -- Preview for human review
    preview_summary TEXT,
    preview_diff JSONB,

    -- Review status
    requires_review BOOLEAN DEFAULT TRUE,
    review_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- Values: pending, approved, rejected, auto_approved, expired

    -- Review details
    reviewed_by UUID,
    reviewed_by_name VARCHAR(255),
    reviewed_at TIMESTAMP WITH TIME ZONE,
    review_notes TEXT,

    -- Modified payload (if reviewer made changes)
    modified_payload JSONB,

    -- Execution
    executed BOOLEAN DEFAULT FALSE,
    executed_at TIMESTAMP WITH TIME ZONE,
    execution_result JSONB,
    execution_error TEXT,

    -- Expiry for auto-cleanup
    expires_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_actions_invocation ON mailagent_agent_actions(invocation_id);
CREATE INDEX IF NOT EXISTS idx_actions_agent ON mailagent_agent_actions(agent_id);
CREATE INDEX IF NOT EXISTS idx_actions_workspace ON mailagent_agent_actions(workspace_id);
CREATE INDEX IF NOT EXISTS idx_actions_review_status ON mailagent_agent_actions(review_status);
CREATE INDEX IF NOT EXISTS idx_actions_pending_review ON mailagent_agent_actions(requires_review, review_status)
    WHERE requires_review = TRUE AND review_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_actions_executed ON mailagent_agent_actions(executed)
    WHERE executed = FALSE;

-- ============================================
-- AGENT REGISTRY (for Aexy to discover agents)
-- ============================================

-- Add workspace-scoped unique name constraint for agents
-- This allows @agent-name mentions to work within a workspace
ALTER TABLE mailagent_agents
ADD COLUMN IF NOT EXISTS mention_handle VARCHAR(50);

-- Create unique index for mention handles within a workspace
CREATE UNIQUE INDEX IF NOT EXISTS idx_agents_mention_handle
ON mailagent_agents(workspace_id, mention_handle)
WHERE mention_handle IS NOT NULL;

-- Update existing agents to have mention handles based on their names
UPDATE mailagent_agents
SET mention_handle = LOWER(REPLACE(REPLACE(name, ' ', '-'), '_', '-'))
WHERE mention_handle IS NULL;

-- ============================================
-- FUNCTIONS
-- ============================================

-- Function to auto-approve actions above confidence threshold
CREATE OR REPLACE FUNCTION check_auto_approve_action()
RETURNS TRIGGER AS $$
DECLARE
    agent_threshold DECIMAL(3,2);
BEGIN
    -- Get the agent's auto-approval threshold
    SELECT confidence_threshold INTO agent_threshold
    FROM mailagent_agents
    WHERE id = NEW.agent_id;

    -- If confidence is above threshold and requires_review is true, auto-approve
    IF NEW.confidence >= COALESCE(agent_threshold, 0.90) AND NEW.requires_review = FALSE THEN
        NEW.review_status := 'auto_approved';
        NEW.reviewed_at := NOW();
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for auto-approval
DROP TRIGGER IF EXISTS trigger_check_auto_approve ON mailagent_agent_actions;
CREATE TRIGGER trigger_check_auto_approve
    BEFORE INSERT ON mailagent_agent_actions
    FOR EACH ROW
    EXECUTE FUNCTION check_auto_approve_action();

-- Function to update invocation status when all actions are processed
CREATE OR REPLACE FUNCTION update_invocation_status()
RETURNS TRIGGER AS $$
DECLARE
    pending_count INTEGER;
    failed_count INTEGER;
BEGIN
    -- Count pending actions for this invocation
    SELECT
        COUNT(*) FILTER (WHERE review_status = 'pending'),
        COUNT(*) FILTER (WHERE execution_error IS NOT NULL)
    INTO pending_count, failed_count
    FROM mailagent_agent_actions
    WHERE invocation_id = NEW.invocation_id;

    -- If no pending actions and the action was executed, update invocation
    IF NEW.executed = TRUE AND pending_count = 0 THEN
        UPDATE mailagent_agent_invocations
        SET
            status = CASE WHEN failed_count > 0 THEN 'completed_with_errors' ELSE 'completed' END,
            completed_at = NOW(),
            updated_at = NOW()
        WHERE id = NEW.invocation_id;
    END IF;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for invocation status update
DROP TRIGGER IF EXISTS trigger_update_invocation_status ON mailagent_agent_actions;
CREATE TRIGGER trigger_update_invocation_status
    AFTER UPDATE ON mailagent_agent_actions
    FOR EACH ROW
    WHEN (NEW.executed = TRUE AND OLD.executed = FALSE)
    EXECUTE FUNCTION update_invocation_status();

-- Done
SELECT 'Agent invocations migration completed' as status;

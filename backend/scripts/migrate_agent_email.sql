-- Agent Email Integration Migration
-- Adds email capabilities to agents including email addresses, inboxes, and routing

-- ============================================
-- ADD EMAIL FIELDS TO AGENTS
-- ============================================

-- Add email address to agents (unique email for receiving emails)
ALTER TABLE crm_agents
ADD COLUMN IF NOT EXISTS email_address VARCHAR(255) UNIQUE;

-- Enable/disable email for the agent
ALTER TABLE crm_agents
ADD COLUMN IF NOT EXISTS email_enabled BOOLEAN DEFAULT FALSE;

-- Auto-reply when confidence is above threshold
ALTER TABLE crm_agents
ADD COLUMN IF NOT EXISTS auto_reply_enabled BOOLEAN DEFAULT TRUE;

-- Custom email signature
ALTER TABLE crm_agents
ADD COLUMN IF NOT EXISTS email_signature TEXT;

-- Index for email lookup
CREATE INDEX IF NOT EXISTS idx_crm_agents_email_address
ON crm_agents(email_address)
WHERE email_address IS NOT NULL;

-- ============================================
-- AGENT INBOXES
-- ============================================

CREATE TABLE IF NOT EXISTS agent_inboxes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID NOT NULL REFERENCES crm_agents(id) ON DELETE CASCADE,
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,

    -- Email metadata
    message_id VARCHAR(255) NOT NULL,
    thread_id VARCHAR(255),
    from_email VARCHAR(255) NOT NULL,
    from_name VARCHAR(255),
    to_email VARCHAR(255) NOT NULL,
    subject TEXT,
    body_text TEXT,
    body_html TEXT,

    -- Processing state
    status VARCHAR(50) DEFAULT 'pending',  -- pending, processing, responded, escalated, archived
    priority VARCHAR(20) DEFAULT 'normal',  -- low, normal, high, urgent

    -- AI processing results
    classification JSONB,  -- {intent, sentiment, urgency, topics}
    summary TEXT,
    suggested_response TEXT,
    confidence_score DECIMAL(3,2),

    -- Response tracking
    response_id UUID,  -- References sent email
    responded_at TIMESTAMP WITH TIME ZONE,
    escalated_to UUID REFERENCES developers(id) ON DELETE SET NULL,
    escalated_at TIMESTAMP WITH TIME ZONE,

    -- Metadata
    headers JSONB,
    attachments JSONB,
    raw_payload JSONB,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for inbox queries
CREATE INDEX IF NOT EXISTS idx_agent_inboxes_agent ON agent_inboxes(agent_id, status);
CREATE INDEX IF NOT EXISTS idx_agent_inboxes_workspace ON agent_inboxes(workspace_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_inboxes_thread ON agent_inboxes(thread_id) WHERE thread_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_agent_inboxes_from ON agent_inboxes(from_email);
CREATE INDEX IF NOT EXISTS idx_agent_inboxes_status ON agent_inboxes(status);
CREATE INDEX IF NOT EXISTS idx_agent_inboxes_message_id ON agent_inboxes(message_id);

-- ============================================
-- EMAIL ROUTING RULES
-- ============================================

CREATE TABLE IF NOT EXISTS agent_email_routing_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES crm_agents(id) ON DELETE CASCADE,

    -- Rule definition
    rule_type VARCHAR(50) NOT NULL,  -- domain, sender, subject_contains, keyword
    rule_value TEXT NOT NULL,
    priority INTEGER DEFAULT 0,
    is_active BOOLEAN DEFAULT TRUE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_routing_rules_workspace ON agent_email_routing_rules(workspace_id, is_active);
CREATE INDEX IF NOT EXISTS idx_routing_rules_agent ON agent_email_routing_rules(agent_id);

-- ============================================
-- UPDATE TIMESTAMP TRIGGER FOR INBOX
-- ============================================

CREATE OR REPLACE FUNCTION update_inbox_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_inbox_updated_at ON agent_inboxes;
CREATE TRIGGER trigger_update_inbox_updated_at
    BEFORE UPDATE ON agent_inboxes
    FOR EACH ROW
    EXECUTE FUNCTION update_inbox_updated_at();

-- ============================================
-- COMMENTS
-- ============================================

COMMENT ON COLUMN crm_agents.email_address IS 'Unique email address for receiving emails (e.g., support@workspace.aexy.email)';
COMMENT ON COLUMN crm_agents.email_enabled IS 'Whether email processing is enabled for this agent';
COMMENT ON COLUMN crm_agents.auto_reply_enabled IS 'Whether to automatically send AI-generated replies when confidence is above threshold';
COMMENT ON COLUMN crm_agents.email_signature IS 'Custom signature appended to agent emails';

COMMENT ON TABLE agent_inboxes IS 'Stores emails received by agents for processing';
COMMENT ON TABLE agent_email_routing_rules IS 'Rules for routing incoming emails to specific agents';

-- Done
SELECT 'Agent email integration migration completed' as status;

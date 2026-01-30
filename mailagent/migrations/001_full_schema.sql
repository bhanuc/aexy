-- Mailagent Full Schema Migration
-- Run: docker exec aexy-postgres psql -U postgres -d aexy -f /migrations/001_full_schema.sql

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- Vector extension for embeddings (optional - install pgvector if needed)
-- CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================
-- INFRASTRUCTURE TABLES
-- ============================================

-- Messages for AI agent inboxes
CREATE TABLE IF NOT EXISTS mailagent_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    inbox_id UUID NOT NULL REFERENCES mailagent_inboxes(id) ON DELETE CASCADE,
    thread_id UUID,
    message_id VARCHAR(500),  -- RFC 5322 Message-ID
    in_reply_to VARCHAR(500),
    "references" TEXT[],

    -- Envelope
    from_address VARCHAR(255) NOT NULL,
    from_name VARCHAR(255),
    to_addresses JSONB NOT NULL DEFAULT '[]',
    cc_addresses JSONB DEFAULT '[]',
    bcc_addresses JSONB DEFAULT '[]',
    reply_to VARCHAR(255),

    -- Content
    subject TEXT,
    body_text TEXT,
    body_html TEXT,
    attachments JSONB DEFAULT '[]',
    headers JSONB DEFAULT '{}',

    -- Metadata
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    status VARCHAR(20) NOT NULL DEFAULT 'received',
    labels TEXT[] DEFAULT '{}',
    is_read BOOLEAN DEFAULT FALSE,

    -- AI extraction
    extracted_data JSONB,
    intent VARCHAR(50),
    sentiment VARCHAR(20),
    summary TEXT,

    -- Tracking
    provider_used VARCHAR(50),
    domain_used VARCHAR(255),
    delivery_status VARCHAR(20),
    delivered_at TIMESTAMP WITH TIME ZONE,
    opened_at TIMESTAMP WITH TIME ZONE,
    clicked_at TIMESTAMP WITH TIME ZONE,
    bounced_at TIMESTAMP WITH TIME ZONE,
    bounce_reason TEXT,

    -- Timestamps
    received_at TIMESTAMP WITH TIME ZONE,
    sent_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_inbox ON mailagent_messages(inbox_id);
CREATE INDEX IF NOT EXISTS idx_messages_thread ON mailagent_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_messages_direction ON mailagent_messages(direction);
CREATE INDEX IF NOT EXISTS idx_messages_status ON mailagent_messages(status);
CREATE INDEX IF NOT EXISTS idx_messages_created ON mailagent_messages(created_at DESC);

-- Threads for conversation grouping
CREATE TABLE IF NOT EXISTS mailagent_threads (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    inbox_id UUID NOT NULL REFERENCES mailagent_inboxes(id) ON DELETE CASCADE,
    subject TEXT,
    participants JSONB DEFAULT '[]',
    message_count INTEGER DEFAULT 0,
    last_message_at TIMESTAMP WITH TIME ZONE,
    labels TEXT[] DEFAULT '{}',
    is_archived BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_threads_inbox ON mailagent_threads(inbox_id);
CREATE INDEX IF NOT EXISTS idx_threads_last_message ON mailagent_threads(last_message_at DESC);

-- Webhook subscriptions
CREATE TABLE IF NOT EXISTS mailagent_webhooks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID,
    url VARCHAR(2048) NOT NULL,
    secret VARCHAR(64),
    event_types TEXT[] NOT NULL,
    inbox_ids UUID[],
    headers JSONB DEFAULT '{}',
    retry_policy JSONB DEFAULT '{"max_retries": 3, "backoff": "exponential"}',
    is_active BOOLEAN DEFAULT TRUE,
    last_triggered_at TIMESTAMP WITH TIME ZONE,
    failure_count INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhooks_active ON mailagent_webhooks(is_active) WHERE is_active = TRUE;

-- Webhook delivery log
CREATE TABLE IF NOT EXISTS mailagent_webhook_deliveries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    webhook_id UUID NOT NULL REFERENCES mailagent_webhooks(id) ON DELETE CASCADE,
    event_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    response_status INTEGER,
    response_body TEXT,
    latency_ms INTEGER,
    attempt INTEGER DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_webhook ON mailagent_webhook_deliveries(webhook_id);
CREATE INDEX IF NOT EXISTS idx_webhook_deliveries_status ON mailagent_webhook_deliveries(status);

-- Domain warming progress
CREATE TABLE IF NOT EXISTS mailagent_warming_progress (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID NOT NULL REFERENCES mailagent_domains(id) ON DELETE CASCADE,
    day_number INTEGER NOT NULL,
    target_volume INTEGER NOT NULL,
    actual_sent INTEGER DEFAULT 0,
    delivered INTEGER DEFAULT 0,
    bounced INTEGER DEFAULT 0,
    complained INTEGER DEFAULT 0,
    delivery_rate DECIMAL(5,2),
    bounce_rate DECIMAL(5,2),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    notes TEXT,
    date DATE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(domain_id, date)
);

CREATE INDEX IF NOT EXISTS idx_warming_domain ON mailagent_warming_progress(domain_id);

-- Domain health metrics
CREATE TABLE IF NOT EXISTS mailagent_domain_health (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    domain_id UUID NOT NULL REFERENCES mailagent_domains(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    health_score INTEGER CHECK (health_score >= 0 AND health_score <= 100),
    sent_count INTEGER DEFAULT 0,
    delivered_count INTEGER DEFAULT 0,
    bounced_count INTEGER DEFAULT 0,
    complained_count INTEGER DEFAULT 0,
    opened_count INTEGER DEFAULT 0,
    clicked_count INTEGER DEFAULT 0,
    delivery_rate DECIMAL(5,2),
    bounce_rate DECIMAL(5,2),
    complaint_rate DECIMAL(5,4),
    open_rate DECIMAL(5,2),
    click_rate DECIMAL(5,2),
    isp_metrics JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(domain_id, date)
);

CREATE INDEX IF NOT EXISTS idx_health_domain ON mailagent_domain_health(domain_id);
CREATE INDEX IF NOT EXISTS idx_health_date ON mailagent_domain_health(date DESC);

-- ============================================
-- AI AGENT TABLES
-- ============================================

-- Agent definitions
CREATE TABLE IF NOT EXISTS mailagent_agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workspace_id UUID,
    name VARCHAR(100) NOT NULL,
    agent_type VARCHAR(50) NOT NULL,
    description TEXT,

    -- LLM Configuration
    llm_provider VARCHAR(50) NOT NULL DEFAULT 'claude',
    llm_model VARCHAR(100) NOT NULL DEFAULT 'claude-3-opus-20240229',
    temperature DECIMAL(2,1) DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 2000,

    -- Behavior
    system_prompt TEXT,
    custom_instructions TEXT,
    auto_respond BOOLEAN DEFAULT TRUE,
    confidence_threshold DECIMAL(3,2) DEFAULT 0.70,
    require_approval_below DECIMAL(3,2) DEFAULT 0.80,
    max_daily_responses INTEGER DEFAULT 100,
    response_delay_minutes INTEGER DEFAULT 5,

    -- Working hours (NULL = 24/7)
    working_hours JSONB,

    -- Escalation
    escalation_email VARCHAR(255),
    escalation_slack_channel VARCHAR(100),
    escalation_conditions TEXT[] DEFAULT '{}',

    -- Integration
    crm_sync BOOLEAN DEFAULT FALSE,
    calendar_sync BOOLEAN DEFAULT FALSE,
    calendar_id VARCHAR(255),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_active_at TIMESTAMP WITH TIME ZONE,

    -- Stats cache
    total_processed INTEGER DEFAULT 0,
    total_auto_replied INTEGER DEFAULT 0,
    total_escalated INTEGER DEFAULT 0,
    avg_confidence DECIMAL(3,2),

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_workspace ON mailagent_agents(workspace_id);
CREATE INDEX IF NOT EXISTS idx_agents_type ON mailagent_agents(agent_type);
CREATE INDEX IF NOT EXISTS idx_agents_active ON mailagent_agents(is_active) WHERE is_active = TRUE;

-- Agent-Inbox association (many-to-many)
CREATE TABLE IF NOT EXISTS mailagent_inbox_agents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    inbox_id UUID NOT NULL REFERENCES mailagent_inboxes(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES mailagent_agents(id) ON DELETE CASCADE,
    priority INTEGER DEFAULT 100,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(inbox_id, agent_id)
);

CREATE INDEX IF NOT EXISTS idx_inbox_agents_inbox ON mailagent_inbox_agents(inbox_id);
CREATE INDEX IF NOT EXISTS idx_inbox_agents_agent ON mailagent_inbox_agents(agent_id);

-- Agent knowledge base
CREATE TABLE IF NOT EXISTS mailagent_agent_knowledge (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES mailagent_agents(id) ON DELETE CASCADE,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    content_type VARCHAR(50) DEFAULT 'text',
    source_url VARCHAR(2048),
    embedding BYTEA,  -- Store embeddings as binary (use vector(1536) if pgvector installed)
    metadata JSONB DEFAULT '{}',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_knowledge_agent ON mailagent_agent_knowledge(agent_id);
-- Vector index (enable when pgvector is installed):
-- CREATE INDEX IF NOT EXISTS idx_knowledge_embedding ON mailagent_agent_knowledge
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Agent decision logs
CREATE TABLE IF NOT EXISTS mailagent_agent_decisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES mailagent_agents(id) ON DELETE CASCADE,
    message_id UUID NOT NULL REFERENCES mailagent_messages(id) ON DELETE CASCADE,

    -- Decision
    action VARCHAR(50) NOT NULL,
    confidence DECIMAL(3,2) NOT NULL,
    reasoning TEXT,
    response_draft TEXT,
    metadata JSONB DEFAULT '{}',

    -- Execution
    executed BOOLEAN DEFAULT FALSE,
    executed_at TIMESTAMP WITH TIME ZONE,
    execution_result JSONB,

    -- Approval
    requires_approval BOOLEAN DEFAULT FALSE,
    approved BOOLEAN,
    approved_by UUID,
    approved_at TIMESTAMP WITH TIME ZONE,
    approval_notes TEXT,

    -- Human feedback
    feedback_rating INTEGER CHECK (feedback_rating >= 1 AND feedback_rating <= 5),
    feedback_correction TEXT,
    feedback_notes TEXT,
    feedback_by UUID,
    feedback_at TIMESTAMP WITH TIME ZONE,

    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_decisions_agent ON mailagent_agent_decisions(agent_id);
CREATE INDEX IF NOT EXISTS idx_decisions_message ON mailagent_agent_decisions(message_id);
CREATE INDEX IF NOT EXISTS idx_decisions_pending ON mailagent_agent_decisions(requires_approval, approved)
    WHERE requires_approval = TRUE AND approved IS NULL;
CREATE INDEX IF NOT EXISTS idx_decisions_feedback ON mailagent_agent_decisions(feedback_rating)
    WHERE feedback_rating IS NOT NULL;

-- Agent sequences (for sales, onboarding, etc.)
CREATE TABLE IF NOT EXISTS mailagent_sequences (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES mailagent_agents(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    trigger_conditions JSONB DEFAULT '{}',
    steps JSONB NOT NULL DEFAULT '[]',
    is_active BOOLEAN DEFAULT TRUE,
    total_enrolled INTEGER DEFAULT 0,
    total_completed INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sequences_agent ON mailagent_sequences(agent_id);

-- Sequence enrollments
CREATE TABLE IF NOT EXISTS mailagent_sequence_enrollments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sequence_id UUID NOT NULL REFERENCES mailagent_sequences(id) ON DELETE CASCADE,
    contact_email VARCHAR(255) NOT NULL,
    contact_name VARCHAR(255),
    current_step INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'active',
    next_action_at TIMESTAMP WITH TIME ZONE,
    completed_steps JSONB DEFAULT '[]',
    variables JSONB DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    paused_reason TEXT,
    exited_reason TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_enrollments_sequence ON mailagent_sequence_enrollments(sequence_id);
CREATE INDEX IF NOT EXISTS idx_enrollments_email ON mailagent_sequence_enrollments(contact_email);
CREATE INDEX IF NOT EXISTS idx_enrollments_next_action ON mailagent_sequence_enrollments(next_action_at)
    WHERE status = 'active';

-- Agent daily metrics
CREATE TABLE IF NOT EXISTS mailagent_agent_metrics (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id UUID NOT NULL REFERENCES mailagent_agents(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    messages_received INTEGER DEFAULT 0,
    messages_processed INTEGER DEFAULT 0,
    auto_responses INTEGER DEFAULT 0,
    escalations INTEGER DEFAULT 0,
    approvals_requested INTEGER DEFAULT 0,
    approvals_granted INTEGER DEFAULT 0,
    approvals_rejected INTEGER DEFAULT 0,
    avg_confidence DECIMAL(3,2),
    avg_response_time_seconds INTEGER,
    positive_feedback INTEGER DEFAULT 0,
    negative_feedback INTEGER DEFAULT 0,
    meetings_scheduled INTEGER DEFAULT 0,
    sequences_triggered INTEGER DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(agent_id, date)
);

CREATE INDEX IF NOT EXISTS idx_agent_metrics_agent ON mailagent_agent_metrics(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_metrics_date ON mailagent_agent_metrics(date DESC);

-- ============================================
-- PROVIDER EVENT LOG (for webhook tracking)
-- ============================================

CREATE TABLE IF NOT EXISTS mailagent_provider_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider VARCHAR(50) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    message_id UUID REFERENCES mailagent_messages(id),
    external_message_id VARCHAR(255),
    payload JSONB NOT NULL,
    processed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_provider_events_message ON mailagent_provider_events(message_id);
CREATE INDEX IF NOT EXISTS idx_provider_events_external ON mailagent_provider_events(external_message_id);
CREATE INDEX IF NOT EXISTS idx_provider_events_unprocessed ON mailagent_provider_events(processed)
    WHERE processed = FALSE;

-- ============================================
-- HELPER FUNCTIONS
-- ============================================

-- Function to update thread message count
CREATE OR REPLACE FUNCTION update_thread_message_count()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE mailagent_threads
    SET
        message_count = message_count + 1,
        last_message_at = NEW.created_at,
        updated_at = NOW()
    WHERE id = NEW.thread_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for message count
DROP TRIGGER IF EXISTS trigger_update_thread_count ON mailagent_messages;
CREATE TRIGGER trigger_update_thread_count
    AFTER INSERT ON mailagent_messages
    FOR EACH ROW
    WHEN (NEW.thread_id IS NOT NULL)
    EXECUTE FUNCTION update_thread_message_count();

-- Function to update agent stats
CREATE OR REPLACE FUNCTION update_agent_stats()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE mailagent_agents
    SET
        total_processed = total_processed + 1,
        total_auto_replied = total_auto_replied + CASE WHEN NEW.action = 'reply' AND NEW.executed THEN 1 ELSE 0 END,
        total_escalated = total_escalated + CASE WHEN NEW.action = 'escalate' THEN 1 ELSE 0 END,
        last_active_at = NOW(),
        updated_at = NOW()
    WHERE id = NEW.agent_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Trigger for agent stats
DROP TRIGGER IF EXISTS trigger_update_agent_stats ON mailagent_agent_decisions;
CREATE TRIGGER trigger_update_agent_stats
    AFTER INSERT ON mailagent_agent_decisions
    FOR EACH ROW
    EXECUTE FUNCTION update_agent_stats();

-- ============================================
-- INITIAL DATA
-- ============================================

-- Insert default warming schedules reference (stored in code, but documented here)
COMMENT ON TABLE mailagent_warming_progress IS 'Warming schedules:
conservative: 50,100,200,400,800,1500,2500,4000,6000,8000,10000,15000,20000,30000,40000,50000,60000,75000,90000,100000 (21 days)
moderate: 100,250,500,1000,2000,4000,7000,12000,20000,35000,50000,75000,100000 (14 days)
aggressive: 200,500,2000,5000,10000,25000,50000,100000 (7 days)';

-- Done
SELECT 'Migration completed successfully' as status;

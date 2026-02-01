-- Agent Conversations Migration
-- Adds tables for agent chat conversations and messages
-- to support interactive chat interface with agents

-- ============================================
-- AGENT CONVERSATIONS
-- ============================================

CREATE TABLE IF NOT EXISTS crm_agent_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    agent_id UUID NOT NULL REFERENCES crm_agents(id) ON DELETE CASCADE,
    record_id UUID,  -- Optional CRM record context
    title VARCHAR(255),  -- Auto-generated or user-set
    status VARCHAR(20) NOT NULL DEFAULT 'active',  -- active, completed, archived
    conversation_metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    ended_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX IF NOT EXISTS idx_conversations_workspace ON crm_agent_conversations(workspace_id);
CREATE INDEX IF NOT EXISTS idx_conversations_agent ON crm_agent_conversations(agent_id);
CREATE INDEX IF NOT EXISTS idx_conversations_status ON crm_agent_conversations(status);
CREATE INDEX IF NOT EXISTS idx_conversations_record ON crm_agent_conversations(record_id) WHERE record_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_conversations_created ON crm_agent_conversations(created_at DESC);

-- ============================================
-- AGENT MESSAGES
-- ============================================

CREATE TABLE IF NOT EXISTS crm_agent_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES crm_agent_conversations(id) ON DELETE CASCADE,
    execution_id UUID REFERENCES crm_agent_executions(id) ON DELETE SET NULL,  -- Links to execution if agent response
    role VARCHAR(20) NOT NULL,  -- 'user', 'assistant', 'system', 'tool'
    content TEXT NOT NULL,
    tool_calls JSONB,  -- For assistant messages with tool calls
    tool_name VARCHAR(100),  -- For tool messages
    tool_output JSONB,  -- For tool messages
    message_index INTEGER NOT NULL,  -- Order in conversation
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON crm_agent_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_execution ON crm_agent_messages(execution_id) WHERE execution_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_messages_role ON crm_agent_messages(role);
CREATE INDEX IF NOT EXISTS idx_messages_order ON crm_agent_messages(conversation_id, message_index);

-- ============================================
-- ADD CONVERSATION_ID TO EXECUTIONS
-- ============================================

ALTER TABLE crm_agent_executions
ADD COLUMN IF NOT EXISTS conversation_id UUID REFERENCES crm_agent_conversations(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_executions_conversation ON crm_agent_executions(conversation_id) WHERE conversation_id IS NOT NULL;

-- ============================================
-- UPDATE TIMESTAMP TRIGGER
-- ============================================

CREATE OR REPLACE FUNCTION update_conversation_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    UPDATE crm_agent_conversations
    SET updated_at = NOW()
    WHERE id = NEW.conversation_id;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_update_conversation_timestamp ON crm_agent_messages;
CREATE TRIGGER trigger_update_conversation_timestamp
    AFTER INSERT ON crm_agent_messages
    FOR EACH ROW
    EXECUTE FUNCTION update_conversation_timestamp();

-- Done
SELECT 'Agent conversations migration completed' as status;

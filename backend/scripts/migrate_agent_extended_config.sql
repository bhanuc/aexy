-- Migration: Add extended configuration fields to AI Agents
-- This adds support for LLM provider selection, behavior configuration, working hours, and escalation settings

-- Add mention_handle column (unique per workspace for @mentions)
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS mention_handle VARCHAR(50);

-- Create unique index for mention_handle within workspace (allowing nulls)
CREATE UNIQUE INDEX IF NOT EXISTS idx_crm_agents_mention_handle_unique
ON crm_agents (workspace_id, mention_handle)
WHERE mention_handle IS NOT NULL;

-- Add LLM configuration columns
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS llm_provider VARCHAR(50) NOT NULL DEFAULT 'claude';
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS temperature FLOAT NOT NULL DEFAULT 0.7;
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS max_tokens INTEGER NOT NULL DEFAULT 4096;

-- Add behavior configuration columns
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS confidence_threshold FLOAT NOT NULL DEFAULT 0.7;
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS require_approval_below FLOAT NOT NULL DEFAULT 0.5;
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS max_daily_responses INTEGER;
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS response_delay_minutes INTEGER NOT NULL DEFAULT 0;

-- Add working hours configuration (JSONB)
-- Schema: { enabled: bool, timezone: str, start: str, end: str, days: int[] }
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS working_hours JSONB;

-- Add custom instructions (separate from system prompt)
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS custom_instructions TEXT;

-- Add escalation settings
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS escalation_email VARCHAR(255);
ALTER TABLE crm_agents ADD COLUMN IF NOT EXISTS escalation_slack_channel VARCHAR(100);

-- Create index for mention_handle lookups
CREATE INDEX IF NOT EXISTS idx_crm_agents_mention_handle ON crm_agents(mention_handle) WHERE mention_handle IS NOT NULL;

-- Comments
COMMENT ON COLUMN crm_agents.mention_handle IS 'Unique @mention handle for triggering the agent';
COMMENT ON COLUMN crm_agents.llm_provider IS 'LLM provider: claude, gemini, or ollama';
COMMENT ON COLUMN crm_agents.temperature IS 'LLM temperature setting (0.0-2.0)';
COMMENT ON COLUMN crm_agents.max_tokens IS 'Maximum tokens for LLM response';
COMMENT ON COLUMN crm_agents.confidence_threshold IS 'Minimum confidence to auto-execute (0.0-1.0)';
COMMENT ON COLUMN crm_agents.require_approval_below IS 'Require human approval below this confidence (0.0-1.0)';
COMMENT ON COLUMN crm_agents.max_daily_responses IS 'Maximum daily responses (null = unlimited)';
COMMENT ON COLUMN crm_agents.response_delay_minutes IS 'Delay in minutes before responding';
COMMENT ON COLUMN crm_agents.working_hours IS 'Working hours config: {enabled, timezone, start, end, days}';
COMMENT ON COLUMN crm_agents.custom_instructions IS 'Additional instructions beyond system prompt';
COMMENT ON COLUMN crm_agents.escalation_email IS 'Email address for escalations';
COMMENT ON COLUMN crm_agents.escalation_slack_channel IS 'Slack channel for escalations';

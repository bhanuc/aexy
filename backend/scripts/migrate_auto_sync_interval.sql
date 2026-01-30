-- Migration: Add auto_sync_interval_minutes to google_integrations
-- This enables configurable automatic email sync intervals

-- Add auto_sync_interval_minutes column (0 = disabled, >0 = interval in minutes)
ALTER TABLE google_integrations
ADD COLUMN IF NOT EXISTS auto_sync_interval_minutes INTEGER NOT NULL DEFAULT 0;

-- Add comment for documentation
COMMENT ON COLUMN google_integrations.auto_sync_interval_minutes IS 'Auto-sync interval in minutes. 0 = disabled, minimum 1 when enabled.';

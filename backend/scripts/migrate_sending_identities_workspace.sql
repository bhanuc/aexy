-- Migration: Add workspace_id to sending_identities
-- This column was missing from the original migration but is required by the model

-- Add workspace_id column if it doesn't exist
ALTER TABLE sending_identities
ADD COLUMN IF NOT EXISTS workspace_id UUID REFERENCES workspaces(id) ON DELETE CASCADE;

-- Populate workspace_id from the related domain's workspace_id
UPDATE sending_identities si
SET workspace_id = sd.workspace_id
FROM sending_domains sd
WHERE si.domain_id = sd.id
AND si.workspace_id IS NULL;

-- Make workspace_id NOT NULL after populating
ALTER TABLE sending_identities
ALTER COLUMN workspace_id SET NOT NULL;

-- Create index for workspace lookups
CREATE INDEX IF NOT EXISTS ix_sending_identity_workspace ON sending_identities(workspace_id);

-- Done
COMMENT ON COLUMN sending_identities.workspace_id IS 'Workspace that owns this identity (denormalized from domain for efficient queries)';

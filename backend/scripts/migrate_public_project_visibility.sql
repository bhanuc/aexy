-- Migration: Add public project visibility support
-- Enables projects to be publicly accessible via a unique slug URL

-- Add is_public column (FALSE by default, all existing projects stay private)
ALTER TABLE projects
ADD COLUMN IF NOT EXISTS is_public BOOLEAN NOT NULL DEFAULT FALSE;

-- Add public_slug column for shareable URLs (nullable, only set when public)
ALTER TABLE projects
ADD COLUMN IF NOT EXISTS public_slug VARCHAR(120);

-- Index on is_public for filtering public projects
CREATE INDEX IF NOT EXISTS ix_projects_is_public ON projects(is_public);

-- Unique index on public_slug for URL lookups
CREATE UNIQUE INDEX IF NOT EXISTS ix_projects_public_slug ON projects(public_slug);

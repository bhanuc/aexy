-- Migration script for Roadmap Voting feature
-- Creates tables for feature requests, votes, and comments on public project pages

-- ============================================================================
-- Roadmap Requests Table
-- Stores feature requests submitted by users for public roadmap voting
-- ============================================================================
CREATE TABLE IF NOT EXISTS roadmap_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,

    -- Request info
    title VARCHAR(500) NOT NULL,
    description TEXT,

    -- Category/type of request: feature, improvement, integration, bug_fix, other
    category VARCHAR(50) NOT NULL DEFAULT 'feature',

    -- Status managed by project owners: under_review, planned, in_progress, completed, declined
    status VARCHAR(50) NOT NULL DEFAULT 'under_review',

    -- Vote count (denormalized for performance)
    vote_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,

    -- Submitter (required - user must be logged in)
    submitted_by_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,

    -- Admin response/notes
    admin_response TEXT,
    responded_at TIMESTAMP WITH TIME ZONE,
    responded_by_id UUID REFERENCES developers(id) ON DELETE SET NULL,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Indexes for roadmap_requests
CREATE INDEX IF NOT EXISTS ix_roadmap_requests_workspace_id ON roadmap_requests(workspace_id);
CREATE INDEX IF NOT EXISTS ix_roadmap_requests_project_id ON roadmap_requests(project_id);
CREATE INDEX IF NOT EXISTS ix_roadmap_requests_submitted_by_id ON roadmap_requests(submitted_by_id);
CREATE INDEX IF NOT EXISTS ix_roadmap_requests_status ON roadmap_requests(project_id, status);
CREATE INDEX IF NOT EXISTS ix_roadmap_requests_category ON roadmap_requests(project_id, category);
CREATE INDEX IF NOT EXISTS ix_roadmap_requests_vote_count ON roadmap_requests(project_id, vote_count DESC);


-- ============================================================================
-- Roadmap Votes Table
-- Stores votes on roadmap requests (one vote per user per request)
-- ============================================================================
CREATE TABLE IF NOT EXISTS roadmap_votes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES roadmap_requests(id) ON DELETE CASCADE,

    -- Voter (required - user must be logged in)
    voter_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Indexes for roadmap_votes
CREATE INDEX IF NOT EXISTS ix_roadmap_votes_request_id ON roadmap_votes(request_id);
CREATE INDEX IF NOT EXISTS ix_roadmap_votes_voter_id ON roadmap_votes(voter_id);

-- One vote per user per request
CREATE UNIQUE INDEX IF NOT EXISTS uq_roadmap_vote_user ON roadmap_votes(request_id, voter_id);


-- ============================================================================
-- Roadmap Comments Table
-- Stores comments on roadmap requests
-- ============================================================================
CREATE TABLE IF NOT EXISTS roadmap_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES roadmap_requests(id) ON DELETE CASCADE,

    -- Comment content
    content TEXT NOT NULL,

    -- Author (required - user must be logged in)
    author_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,

    -- Admin/official comment flag
    is_admin_response BOOLEAN NOT NULL DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- Indexes for roadmap_comments
CREATE INDEX IF NOT EXISTS ix_roadmap_comments_request_id ON roadmap_comments(request_id);
CREATE INDEX IF NOT EXISTS ix_roadmap_comments_author_id ON roadmap_comments(author_id);
CREATE INDEX IF NOT EXISTS ix_roadmap_comments_created_at ON roadmap_comments(request_id, created_at);

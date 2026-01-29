-- GitHub Intelligence System Enhancement Migration
-- Adds fields for semantic commit analysis, review quality metrics,
-- expertise confidence, and burnout risk indicators

-- =============================================================================
-- COMMIT SEMANTIC ANALYSIS
-- =============================================================================

-- Add semantic analysis to commits table
ALTER TABLE commits
ADD COLUMN IF NOT EXISTS semantic_analysis JSONB;

COMMENT ON COLUMN commits.semantic_analysis IS 'LLM-derived semantic analysis: type, scope, breaking, quality_score, semantic_tags';

-- Example structure:
-- {
--   "type": "feature",           -- feat, fix, refactor, chore, docs, test, style, perf
--   "scope": "auth",             -- Component affected
--   "breaking": false,           -- Breaking change flag
--   "quality_score": 85,         -- Message clarity 0-100
--   "semantic_tags": ["authentication", "security", "oauth"],
--   "analyzed_at": "2024-01-15T10:30:00Z"
-- }

-- =============================================================================
-- CODE REVIEW QUALITY METRICS
-- =============================================================================

-- Add quality metrics to code_reviews table
ALTER TABLE code_reviews
ADD COLUMN IF NOT EXISTS quality_metrics JSONB;

COMMENT ON COLUMN code_reviews.quality_metrics IS 'Review quality analysis: depth, thoroughness, mentoring indicators';

-- Example structure:
-- {
--   "depth_score": 3.5,          -- 1-5 scale (1=superficial, 5=thorough)
--   "thoroughness": "detailed",  -- cursory, standard, detailed, exhaustive
--   "has_suggestions": true,
--   "has_code_examples": false,
--   "mentoring_indicators": ["explains_why", "provides_alternatives"],
--   "response_time_hours": 4.5,
--   "analyzed_at": "2024-01-15T10:30:00Z"
-- }

-- =============================================================================
-- DEVELOPER INTELLIGENCE ENHANCEMENTS
-- =============================================================================

-- Add expertise confidence to developers table
ALTER TABLE developers
ADD COLUMN IF NOT EXISTS expertise_confidence JSONB;

COMMENT ON COLUMN developers.expertise_confidence IS 'Enhanced skill scores with confidence intervals and context';

-- Example structure:
-- {
--   "skills": [
--     {
--       "name": "Python",
--       "proficiency": 85,
--       "confidence": 0.92,
--       "recency_factor": 0.95,
--       "depth": "expert",
--       "context": "production",
--       "last_activity_at": "2024-01-15T10:30:00Z"
--     }
--   ],
--   "updated_at": "2024-01-15T10:30:00Z"
-- }

-- Add burnout risk indicators to developers table
ALTER TABLE developers
ADD COLUMN IF NOT EXISTS burnout_indicators JSONB;

COMMENT ON COLUMN developers.burnout_indicators IS 'Burnout risk analysis: score, indicators, trends';

-- Example structure:
-- {
--   "risk_score": 0.35,          -- 0-1 scale
--   "risk_level": "low",         -- low, moderate, high, critical
--   "indicators": {
--     "after_hours_percentage": 15.5,
--     "weekend_commits_percentage": 8.2,
--     "avg_daily_commits": 4.5,
--     "review_quality_trend": "stable",
--     "consecutive_high_activity_days": 3,
--     "days_since_break": 45
--   },
--   "alerts": [],
--   "trend": "stable",           -- improving, stable, worsening
--   "updated_at": "2024-01-15T10:30:00Z"
-- }

-- Add last intelligence analysis timestamp
ALTER TABLE developers
ADD COLUMN IF NOT EXISTS last_intelligence_analysis_at TIMESTAMPTZ;

COMMENT ON COLUMN developers.last_intelligence_analysis_at IS 'When the GitHub intelligence analysis was last run';

-- =============================================================================
-- PULL REQUEST ENHANCEMENTS
-- =============================================================================

-- Add complexity analysis to pull_requests
ALTER TABLE pull_requests
ADD COLUMN IF NOT EXISTS complexity_analysis JSONB;

COMMENT ON COLUMN pull_requests.complexity_analysis IS 'PR complexity metrics: score, classification, impact';

-- Example structure:
-- {
--   "complexity_score": 65,      -- 0-100
--   "classification": "medium",  -- trivial, simple, medium, complex, architectural
--   "impact_areas": ["api", "database"],
--   "files_distribution": {
--     "single_component": false,
--     "cross_cutting": true,
--     "infrastructure": false
--   },
--   "risk_level": "low"          -- low, medium, high
-- }

-- =============================================================================
-- INDEXES FOR PERFORMANCE
-- =============================================================================

-- Index for querying commits by semantic type
CREATE INDEX IF NOT EXISTS ix_commits_semantic_type
ON commits ((semantic_analysis->>'type'))
WHERE semantic_analysis IS NOT NULL;

-- Index for querying developers by burnout risk
CREATE INDEX IF NOT EXISTS ix_developers_burnout_risk
ON developers ((burnout_indicators->>'risk_level'))
WHERE burnout_indicators IS NOT NULL;

-- Index for querying reviews by quality
CREATE INDEX IF NOT EXISTS ix_code_reviews_quality
ON code_reviews (((quality_metrics->>'depth_score')::float))
WHERE quality_metrics IS NOT NULL;

-- =============================================================================
-- COLLABORATION NETWORK TABLE (for future use)
-- =============================================================================

CREATE TABLE IF NOT EXISTS developer_collaborations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    developer_a_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,
    developer_b_id UUID NOT NULL REFERENCES developers(id) ON DELETE CASCADE,

    -- Interaction metrics
    interaction_count INTEGER NOT NULL DEFAULT 0,
    review_count INTEGER NOT NULL DEFAULT 0,
    co_author_count INTEGER NOT NULL DEFAULT 0,
    mention_count INTEGER NOT NULL DEFAULT 0,

    -- Calculated strength
    strength_score FLOAT NOT NULL DEFAULT 0.0,

    -- Timestamps
    first_interaction_at TIMESTAMPTZ,
    last_interaction_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Ensure unique pairs (order-independent)
    CONSTRAINT unique_collaboration_pair UNIQUE (developer_a_id, developer_b_id),
    CONSTRAINT ordered_collaboration_pair CHECK (developer_a_id < developer_b_id)
);

CREATE INDEX IF NOT EXISTS ix_developer_collaborations_a ON developer_collaborations(developer_a_id);
CREATE INDEX IF NOT EXISTS ix_developer_collaborations_b ON developer_collaborations(developer_b_id);
CREATE INDEX IF NOT EXISTS ix_developer_collaborations_strength ON developer_collaborations(strength_score DESC);

COMMENT ON TABLE developer_collaborations IS 'Tracks collaboration relationships between developers for network analysis';

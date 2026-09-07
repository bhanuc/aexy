-- Repair: project category sets that got truncated to a single bucket.
--
-- `get_categories_for_project` resolves *either* the project's own category
-- rows *or* the workspace defaults — never a union. `create_status` guards
-- against that by cloning the workspace set into the project before the
-- first project-scoped insert; `create_category` did not. So an admin who
-- opened a project's status settings (which lists the inherited workspace
-- categories) and clicked "Add Category" wrote one project-scoped row, and
-- the very next read flipped the project off fallback: six inherited buckets
-- became one. Nothing was deleted — the workspace rows were still there,
-- just masked — but the status admin and the bucket dropdown showed a single
-- category, and statuses could no longer be filed under the others.
--
-- `create_category` now clones first (see
-- TaskConfigService.clone_workspace_categories_to_project). This migration
-- fixes the scopes already truncated in the wild by backfilling every
-- workspace-default category that the project scope is missing, then
-- renumbering so the inherited buckets keep workspace order and the
-- project's own additions sort after them.
--
-- Idempotent and additive: projects that never forked (zero rows) stay on
-- fallback and are untouched; a project that already has the full set gets
-- nothing new thanks to the NOT EXISTS guard.

-- 1. Legacy workspaces that never got category rows at all — without these,
--    step 2 has nothing to copy. Mirrors
--    TaskConfigService.DEFAULT_CATEGORIES.
INSERT INTO workspace_status_categories (id, workspace_id, project_id, slug, label, color, semantics, position, is_default)
SELECT gen_random_uuid(), w.id, NULL, vals.slug, vals.label, vals.color, vals.semantics, vals.position, vals.is_default
FROM workspaces w
CROSS JOIN (
    VALUES
        ('backlog',     'Backlog',     '#9CA3AF', 'open',      0, TRUE),
        ('todo',        'To Do',       '#3B82F6', 'open',      1, FALSE),
        ('in_progress', 'In Progress', '#F59E0B', 'active',    2, FALSE),
        ('in_review',   'In Review',   '#8B5CF6', 'active',    3, FALSE),
        ('done',        'Done',        '#10B981', 'done',      4, FALSE),
        ('cancelled',   'Cancelled',   '#EF4444', 'cancelled', 5, FALSE)
) AS vals(slug, label, color, semantics, position, is_default)
WHERE NOT EXISTS (
    SELECT 1 FROM workspace_status_categories c
    WHERE c.workspace_id = w.id AND c.project_id IS NULL
)
ON CONFLICT (workspace_id, COALESCE(project_id::text, ''), slug) DO NOTHING;

-- 2. Backfill the missing inherited buckets into every project scope that
--    has at least one row of its own. Copies the workspace row's label /
--    color / semantics so an admin's renamed bucket carries over rather
--    than reverting to the canonical wording.
INSERT INTO workspace_status_categories (id, workspace_id, project_id, slug, label, color, semantics, position, is_default)
SELECT
    gen_random_uuid(),
    ws_cat.workspace_id,
    forked.project_id,
    ws_cat.slug,
    ws_cat.label,
    ws_cat.color,
    ws_cat.semantics,
    ws_cat.position,
    ws_cat.is_default
FROM (
    SELECT DISTINCT workspace_id, project_id
    FROM workspace_status_categories
    WHERE project_id IS NOT NULL
) AS forked
JOIN workspace_status_categories ws_cat
  ON ws_cat.workspace_id = forked.workspace_id
 AND ws_cat.project_id IS NULL
WHERE NOT EXISTS (
    SELECT 1 FROM workspace_status_categories existing
    WHERE existing.workspace_id = forked.workspace_id
      AND existing.project_id = forked.project_id
      AND existing.slug = ws_cat.slug
)
ON CONFLICT (workspace_id, COALESCE(project_id::text, ''), slug) DO NOTHING;

-- 3. Renumber the scopes step 2 repaired. The truncating insert took
--    position 0 (the scope looked empty), so after the backfill several rows
--    share a position and `ORDER BY position` is arbitrary. Inherited
--    buckets take the workspace ordering; the project's own additions land
--    after them, keeping the order they were added in.
--
--    Restricted to scopes whose positions actually collide. A scope repaired
--    by step 2 always collides — the truncating insert took position 0 and
--    so does the first backfilled workspace bucket — while a scope that
--    already held the full set has distinct positions and keeps whatever
--    order an admin gave it through the reorder endpoint. Without this the
--    statement would rewrite the ordering of scopes it has no business
--    touching, and re-running the file would undo a deliberate reorder.
WITH ambiguous_scopes AS (
    SELECT workspace_id, project_id
    FROM workspace_status_categories
    WHERE project_id IS NOT NULL
    GROUP BY workspace_id, project_id
    HAVING count(*) <> count(DISTINCT position)
),
ordered AS (
    SELECT
        c.id,
        ROW_NUMBER() OVER (
            PARTITION BY c.workspace_id, c.project_id
            -- `c.position` before `c.slug`: the project's own additions
            -- already carry their insertion order (0, 1, 2 …) and no
            -- workspace row to sort them by, so falling straight to slug
            -- would reorder them alphabetically and lose that. Slug is only
            -- the last resort for rows that genuinely tie.
            ORDER BY COALESCE(ws.position, 1000), c.position, c.slug
        ) - 1 AS new_position
    FROM workspace_status_categories c
    JOIN ambiguous_scopes a
      ON a.workspace_id = c.workspace_id
     AND a.project_id = c.project_id
    LEFT JOIN workspace_status_categories ws
      ON ws.workspace_id = c.workspace_id
     AND ws.project_id IS NULL
     AND ws.slug = c.slug
    WHERE c.project_id IS NOT NULL
)
UPDATE workspace_status_categories c
SET position = ordered.new_position,
    updated_at = now()
FROM ordered
WHERE c.id = ordered.id
  AND c.position <> ordered.new_position;

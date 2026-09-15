-- Scoped project visibility, and the permission that opts out of it.
--
-- Until now `GET /workspaces/{id}/projects` returned every project in the
-- workspace to anyone holding `can_view_projects` — which is everyone except a
-- role that was explicitly stripped of it. A developer on one team saw, and
-- could open, every other team's board.
--
-- Two things make the new rule safe to deploy:
--
-- 1. `can_view_all_projects` is added to the roles that already manage the
--    workspace (owner, admin, manager), so nobody who is *supposed* to see
--    everything loses anything. It is appended to stored role rows here
--    because a workspace's roles are copies of the templates taken at creation
--    time: changing the template in Python does nothing for a workspace that
--    already exists.
--
-- 2. Every existing workspace is stamped `project_visibility = 'workspace'`,
--    which is the behaviour it has today. Nothing disappears on deploy. An
--    admin switches a workspace over when its project membership is right,
--    and `scripts/report_project_visibility.py` says what that switch would
--    cost before anyone makes it. Workspaces created from here on have no
--    such stamp and start scoped, which is the intended default.

-- =============================================================================
-- ROLES: hand `can_view_all_projects` to the roles that manage the workspace
-- =============================================================================

UPDATE custom_roles
SET permissions = permissions || '["can_view_all_projects"]'::jsonb
WHERE based_on_template IN ('owner', 'admin', 'manager')
  AND NOT (permissions @> '["can_view_all_projects"]'::jsonb);

-- A role built from scratch that already holds every *other* project
-- permission was plainly meant to be an administrative one; leaving it out
-- would quietly demote it.
UPDATE custom_roles
SET permissions = permissions || '["can_view_all_projects"]'::jsonb
WHERE based_on_template IS NULL
  AND permissions @> '["can_view_projects", "can_edit_projects", "can_create_projects"]'::jsonb
  AND NOT (permissions @> '["can_view_all_projects"]'::jsonb);

-- =============================================================================
-- WORKSPACES: keep today's behaviour until somebody chooses otherwise
-- =============================================================================

UPDATE workspaces
SET settings = COALESCE(settings, '{}'::jsonb)
             || '{"project_visibility": "workspace"}'::jsonb
WHERE settings IS NULL
   OR NOT (settings ? 'project_visibility');

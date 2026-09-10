-- Give developers `can_view_tickets`, in the workspaces that already exist.
--
-- `can_create_tickets` has always defaulted to developers and `can_view_tickets`
-- has not, so a developer could raise a ticket and then not read the queue it
-- landed in. The tickets app is filed under Engineering and its Alerts view is
-- an on-call queue, which makes that the wrong way round.
--
-- The code change alone does not reach existing workspaces. `create_system_roles`
-- snapshots each template's permission list into `custom_roles.permissions` when
-- a workspace is created, so a workspace made before today keeps the old list
-- until something rewrites it. The other path — `workspace_members.role` with no
-- `role_id` — reads ROLE_TEMPLATES live and needs nothing here.
--
-- Only untouched snapshots are rewritten. A role whose permission set no longer
-- matches the old developer template has been edited by an admin, and an admin
-- who removed a permission deliberately should not have it handed back by a
-- deploy. Those keep whatever they were set to; an admin can use "reset to
-- template" if they want the new default.

-- The developer template as it stood before this change: 18 permissions,
-- `can_view_tickets` absent. Compared as a sorted set, so a role that holds the
-- same permissions in a different order still matches.
WITH old_developer_template AS (
    SELECT ARRAY[
        'can_create_docs',
        'can_create_tables',
        'can_create_tickets',
        'can_edit_docs',
        'can_manage_tasks',
        'can_request_leaves',
        'can_submit_feedback',
        'can_submit_standups',
        'can_view_docs',
        'can_view_learning',
        'can_view_members',
        'can_view_oncall',
        'can_view_org',
        'can_view_projects',
        'can_view_service_desk',
        'can_view_sprints',
        'can_view_tables',
        'can_view_tracking'
    ]::text[] AS perms
),
untouched AS (
    SELECT r.id
    FROM custom_roles r, old_developer_template t
    WHERE r.based_on_template = 'developer'
      AND r.is_system IS TRUE
      AND (
          SELECT array_agg(p ORDER BY p)
          FROM jsonb_array_elements_text(r.permissions) AS p
      ) = (SELECT array_agg(p ORDER BY p) FROM unnest(t.perms) AS p)
)
UPDATE custom_roles
SET permissions = permissions || '["can_view_tickets"]'::jsonb,
    updated_at = NOW()
WHERE id IN (SELECT id FROM untouched);

-- What was left alone, and why. A developer role that is neither in the count
-- above nor already holding the permission is an edited one.
SELECT
    count(*) FILTER (WHERE permissions ? 'can_view_tickets') AS developer_roles_with_view,
    count(*) FILTER (WHERE NOT (permissions ? 'can_view_tickets')) AS developer_roles_without_view
FROM custom_roles
WHERE based_on_template = 'developer';

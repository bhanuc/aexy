"""Who gets to read the ticket queue by default.

`can_create_tickets` has always included developers and `can_view_tickets` has
not, so a developer could raise a ticket and then not read the queue it landed
in. The two lists were written apart and nothing compared them.

There are two paths from a role to a permission and they do not agree with each
other on their own:

* `workspace_members.role` with no `role_id` reads `ROLE_TEMPLATES` live, so a
  change to `default_for` reaches it on deploy;
* `role_id` points at a `custom_roles` row whose `permissions` list was
  snapshotted from the template when the workspace was created, and nothing
  rewrites it afterwards.

Only the first is testable here. The second is what
`migrate_developer_can_view_tickets.sql` exists for, and it is verified against
a real Postgres rather than SQLite because it turns on `jsonb` set comparison.
"""

from aexy.models.app_definitions import get_default_app_access_for_role
from aexy.models.permissions import (
    PERMISSIONS,
    ROLE_TEMPLATES,
    WIDGET_PERMISSIONS,
    get_permissions_for_template,
)


def test_developers_can_view_tickets():
    assert "developer" in PERMISSIONS["can_view_tickets"]["default_for"]


def test_viewing_and_creating_agree():
    """The specific accident this guards: create without view.

    Asserted as a relationship rather than as two lists, because the failure
    mode is not "someone deleted a role" — it is someone adding a role to one
    of these and not the other, which is how the two drifted apart.
    """
    view = set(PERMISSIONS["can_view_tickets"]["default_for"])
    create = set(PERMISSIONS["can_create_tickets"]["default_for"])
    assert create <= view, (
        f"{sorted(create - view)} can create a ticket and not read the queue "
        f"it lands in"
    )


def test_the_developer_template_carries_it():
    # `default_for` is the declaration; this is the lookup every legacy-role
    # member actually goes through, and the one the migration mirrors.
    assert "can_view_tickets" in get_permissions_for_template("developer")


def test_the_migration_matches_the_template_it_claims_to_patch():
    """The migration hardcodes the *old* developer list to find untouched rows.

    A row is only rewritten when its permissions equal that list exactly, so if
    the template drifts and the migration's copy does not, it silently stops
    matching anything and the rewrite quietly does nothing. Pinning the one
    difference keeps that visible: the migration's list must be today's
    template minus `can_view_tickets`, and nothing else.
    """
    from pathlib import Path
    import re

    sql = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "migrate_developer_can_view_tickets.sql"
    ).read_text()

    block = sql.split("ARRAY[", 1)[1].split("]::text[]", 1)[0]
    in_migration = set(re.findall(r"'([a-z_]+)'", block))

    today = set(get_permissions_for_template("developer"))
    assert in_migration == today - {"can_view_tickets"}


# ==================== what the permission is actually for ====================

# Roles whose app-access default and `can_view_tickets` deliberately disagree.
# Both are decisions; the test below fails on any *third* role, which is how a
# new drift gets noticed.
ACCEPTED_MISMATCHES = {
    # Read-only, and deliberately minimal: four permissions in total, none of
    # the other `can_view_*` for gated modules either. Its app-access default
    # is the generous one; narrowing that is a separate question about the
    # viewer bundle, not about this permission.
    "viewer",
    # Holds `can_view_service_desk` but not this. The two are different
    # products — the desk is customer-facing, tickets is the internal
    # engineering queue — so a salesperson having the first and not the second
    # is coherent. That the business bundle grants them the tickets *app* is
    # the part worth revisiting, again separately.
    "sales",
}


def test_the_widget_flag_follows_who_can_reach_the_app():
    """`can_view_tickets` decides widgets, so it should track app access.

    Not `can_manage_tickets`, and not the other ticket permissions. Offering
    somebody the tickets app and then hiding every ticket widget from their
    dashboard is the shape of accident that put `developer` in one list and
    not the other, and it is invisible until someone notices an empty
    dashboard.
    """
    drifted = []
    for template_id, template in ROLE_TEMPLATES.items():
        if template_id in ACCEPTED_MISMATCHES:
            continue
        app = get_default_app_access_for_role(template_id)
        reaches_app = bool(app.get("tickets", {}).get("enabled"))
        has_flag = "can_view_tickets" in template["permissions"]
        if reaches_app != has_flag:
            drifted.append(
                f"{template_id}: app_access={reaches_app} can_view_tickets={has_flag}"
            )
    assert not drifted, (
        "these roles are offered the tickets app and its widgets "
        f"inconsistently: {drifted}. Either fix the default, or add the role "
        "to ACCEPTED_MISMATCHES with the reason."
    )


def test_the_permission_is_only_read_by_widgets():
    """Guards the decision recorded in `api/__init__.py`.

    The permission looks unenforced, which invites somebody to "fix" that by
    hanging `require_workspace_permission("can_view_tickets")` off
    `tickets_router`. That would put a second gate beside `require_app_access`
    on the same question, and the two can disagree — the loser being somebody
    whose navigation offers a page that 403s.

    Reads are app access. Writes are role plus Service Desk row scoping inside
    `tickets.py`. This asserts the middle ground stays empty.
    """
    from pathlib import Path

    api_init = (
        Path(__file__).resolve().parents[2] / "src" / "aexy" / "api" / "__init__.py"
    ).read_text()

    mount = next(
        line
        for line in api_init.splitlines()
        if "include_router(tickets_router" in line
    )
    assert 'require_app_access("tickets")' in mount
    assert "can_view_tickets" not in mount, (
        "tickets_router must not gate on can_view_tickets — see the comment "
        "above the mount for why"
    )
    # And it is read by widgets, which is the role the comment claims for it.
    assert any(
        "can_view_tickets" in perms for perms in WIDGET_PERMISSIONS.values()
    )


def test_ticket_writes_are_not_gated_on_a_permission_developers_lack():
    """A developer must be able to answer the ticket they raised.

    `POST /{id}/responses` is a write, so a router-wide
    `require_workspace_permission_for_writes("can_manage_tickets")` — the
    pattern the escalation and ticket-form routers use — would silently stop
    developers commenting. If someone adds one, this says why not to.
    """
    from pathlib import Path

    api_init = (
        Path(__file__).resolve().parents[2] / "src" / "aexy" / "api" / "__init__.py"
    ).read_text()
    mount = next(
        line
        for line in api_init.splitlines()
        if "include_router(tickets_router" in line
    )
    assert "require_workspace_permission_for_writes" not in mount

    manage = set(PERMISSIONS["can_manage_tickets"]["default_for"])
    create = set(PERMISSIONS["can_create_tickets"]["default_for"])
    # The premise of the paragraph above: there really are roles that may
    # raise a ticket and could not manage one.
    assert create - manage

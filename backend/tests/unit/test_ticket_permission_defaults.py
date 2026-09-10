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

from aexy.models.permissions import PERMISSIONS, get_permissions_for_template


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

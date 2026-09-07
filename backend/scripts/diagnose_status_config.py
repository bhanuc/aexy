#!/usr/bin/env python3
"""Read-only report on a workspace's status categories and statuses.

Written to answer, for a production workspace where "adding a category
removed the existing categories":

  * are the workspace-default categories still in the table, or were rows
    actually deleted?
  * which projects have forked (project-scoped) category sets, and are any
    of them truncated — i.e. missing buckets the workspace defines?
  * same question for statuses, plus whether each scope still has an
    is_default status and a status in a `done`-semantics bucket (the two
    things whose absence breaks task creation and velocity).

The usual cause of the "everything vanished" report is masking, not
deletion: `get_categories_for_project` returns the project's own rows *or*
the workspace defaults, never both, so the first project-scoped row hides
all six inherited ones. Rows marked TRUNCATED below are that case, and
`scripts/migrate_status_categories_project_backfill.sql` repairs them.

Touches nothing. Usage:

    docker exec aexy-backend python scripts/diagnose_status_config.py <workspace_id>

Or piped over stdin (no file deploy needed):

    cat scripts/diagnose_status_config.py | \\
        docker exec -i aexy-backend python - <workspace_id>
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Resolve src whether run as a file or piped via `python -` (no __file__).
try:
    sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
except NameError:
    for candidate in ("/app/src", os.path.join(os.getcwd(), "src")):
        if os.path.isdir(candidate):
            sys.path.insert(0, candidate)
            break

from sqlalchemy import select  # noqa: E402

from aexy.core.database import async_session_maker  # noqa: E402
from aexy.models.project import Project  # noqa: E402
from aexy.models.sprint import (  # noqa: E402
    SprintTask,
    WorkspaceStatusCategory,
    WorkspaceTaskStatus,
)
from aexy.models.workspace import Workspace  # noqa: E402
from aexy.services.task_config_service import (  # noqa: E402
    DEFAULT_CATEGORIES,
    DEFAULT_STATUSES,
)

CANONICAL_CATEGORY_SLUGS = {c["slug"] for c in DEFAULT_CATEGORIES}
CANONICAL_STATUS_SLUGS = {s["slug"] for s in DEFAULT_STATUSES}


async def diagnose(workspace_id: str) -> int:
    async with async_session_maker() as db:
        ws = (
            await db.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        if ws is None:
            print(f"No workspace {workspace_id}")
            return 1
        print(f"\n=== Workspace {ws.name} ({ws.id}) ===")

        projects = (
            await db.execute(
                select(Project.id, Project.name)
                .where(Project.workspace_id == workspace_id)
                .order_by(Project.name)
            )
        ).all()
        project_names = {str(p.id): p.name for p in projects}

        cats = (
            await db.execute(
                select(WorkspaceStatusCategory)
                .where(WorkspaceStatusCategory.workspace_id == workspace_id)
                .order_by(WorkspaceStatusCategory.position)
            )
        ).scalars().all()
        statuses = (
            await db.execute(
                select(WorkspaceTaskStatus)
                .where(WorkspaceTaskStatus.workspace_id == workspace_id)
                .order_by(WorkspaceTaskStatus.position)
            )
        ).scalars().all()

        def by_scope(rows):
            out: dict[str | None, list] = {}
            for r in rows:
                out.setdefault(
                    str(r.project_id) if r.project_id else None, []
                ).append(r)
            return out

        cats_by_scope = by_scope(cats)
        statuses_by_scope = by_scope(statuses)

        # ---- Categories ----
        ws_cats = cats_by_scope.get(None, [])
        print(f"\n--- Categories: workspace scope ({len(ws_cats)} rows) ---")
        if not ws_cats:
            print(
                "  NONE. Nothing to inherit — every project falls through to "
                "an empty set. The backfill migration reseeds the canonical six."
            )
        for c in ws_cats:
            flag = " [default]" if c.is_default else ""
            print(
                f"  {c.position:>2}  {c.slug:<18} {c.semantics:<10} "
                f"{c.label!r}{flag}"
            )
        missing_canonical = CANONICAL_CATEGORY_SLUGS - {c.slug for c in ws_cats}
        if ws_cats and missing_canonical:
            print(
                f"  NOTE: canonical slugs absent from the workspace scope: "
                f"{sorted(missing_canonical)} (fine if renamed/removed on purpose)"
            )

        ws_cat_slugs = {c.slug for c in ws_cats}
        forked_cat_scopes = [s for s in cats_by_scope if s is not None]
        print(f"\n--- Categories: project scopes ({len(forked_cat_scopes)}) ---")
        if not forked_cat_scopes:
            print("  None — every project inherits the workspace categories.")
        for scope in sorted(
            forked_cat_scopes, key=lambda s: project_names.get(s, s)
        ):
            rows = cats_by_scope[scope]
            missing = ws_cat_slugs - {r.slug for r in rows}
            label = project_names.get(scope, f"<unknown project {scope}>")
            verdict = (
                f"TRUNCATED — missing {sorted(missing)}" if missing else "complete"
            )
            print(f"  {label} ({scope}): {len(rows)} rows — {verdict}")
            for r in sorted(rows, key=lambda r: r.position):
                print(
                    f"      {r.position:>2}  {r.slug:<18} {r.semantics:<10} "
                    f"{r.label!r}"
                )

        # ---- Statuses ----
        print("\n--- Statuses by scope ---")
        for scope in [None] + sorted(
            (s for s in statuses_by_scope if s is not None),
            key=lambda s: project_names.get(s, s),
        ):
            rows = statuses_by_scope.get(scope, [])
            label = (
                "workspace scope"
                if scope is None
                else f"{project_names.get(scope, scope)} ({scope})"
            )
            active = [r for r in rows if r.is_active]
            inactive = [r for r in rows if not r.is_active]
            print(
                f"\n  {label}: {len(active)} active"
                + (f", {len(inactive)} soft-deleted" if inactive else "")
            )
            if not rows and scope is None:
                print(
                    "    NONE — this workspace has no default statuses. Every "
                    "project without its own set has an empty board."
                )
            for r in sorted(rows, key=lambda r: r.position):
                marks = []
                if r.is_default:
                    marks.append("default")
                if not r.is_active:
                    marks.append("DELETED")
                # A status whose category isn't resolvable in its own scope
                # renders without a bucket and breaks burndown.
                scope_cat_slugs = {
                    c.slug for c in cats_by_scope.get(scope, [])
                } or ws_cat_slugs
                if r.category not in scope_cat_slugs:
                    marks.append(f"ORPHAN CATEGORY {r.category!r}")
                suffix = f"  [{', '.join(marks)}]" if marks else ""
                print(
                    f"    {r.position:>2}  {r.slug:<18} cat={r.category:<14} "
                    f"{r.name!r}{suffix}"
                )
            if active and not any(r.is_default for r in active):
                print(
                    "    WARNING: no is_default status in this scope — new "
                    "tasks fall back to the resolver instead of an explicit "
                    "default column."
                )
            # Does this scope have anywhere to put finished work?
            scope_cats = cats_by_scope.get(scope) or ws_cats
            done_slugs = {c.slug for c in scope_cats if c.semantics == "done"}
            if active and not any(r.category in done_slugs for r in active):
                print(
                    "    WARNING: no active status in a done-semantics "
                    "category — velocity and burndown will read zero here."
                )
            if scope is None:
                gone = CANONICAL_STATUS_SLUGS - {r.slug for r in rows}
                if gone:
                    print(
                        f"    NOTE: seeded slugs no longer present: "
                        f"{sorted(gone)} (renamed or deleted)"
                    )

        # ---- Tasks pointing at nothing ----
        # `sprint_tasks` carries team_id, not project_id, so scoping a task
        # to a project scope needs the project_teams join. Not worth it for a
        # diagnostic: check each task's status against the union of every
        # active status slug in the workspace. A hit here is unambiguous —
        # no scope defines that column, so the task renders nowhere.
        active_slugs = {r.slug for r in statuses if r.is_active}
        task_rows = (
            await db.execute(
                select(SprintTask.status, SprintTask.id)
                .where(SprintTask.workspace_id == workspace_id)
            )
        ).all()
        orphaned: dict[str, int] = {}
        for status_slug, _task_id in task_rows:
            if status_slug not in active_slugs:
                orphaned[status_slug] = orphaned.get(status_slug, 0) + 1
        print(
            f"\n--- Tasks whose status matches no active column "
            f"({len(task_rows)} tasks scanned) ---"
        )
        if not orphaned:
            print("  None — every task resolves to an active status somewhere.")
        for slug, n in sorted(orphaned.items(), key=lambda kv: -kv[1]):
            print(f"  {n} task(s) with status={slug!r} — invisible on every board")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace_id", help="UUID of the workspace to inspect")
    args = parser.parse_args()
    sys.exit(asyncio.run(diagnose(args.workspace_id)))


if __name__ == "__main__":
    main()

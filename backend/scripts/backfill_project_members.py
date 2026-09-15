"""Make today's implicit project access explicit, before it starts being enforced.

Until membership scoping landed, every active workspace member could see every
project — no `project_members` row required, and projects only ever auto-enrol
their creator. So the membership table is, for most workspaces, close to empty
while everybody in fact has access.

This writes down what is already true: every active workspace member becomes an
active member of every active project in that workspace. Nothing is granted that
anyone lacks today; it only means that switching a workspace to
`project_visibility = "members"` afterwards takes nothing away by surprise. From
there, an admin prunes each project's membership to the people who belong, and
`scripts/report_project_visibility.py` says what the switch would cost at any
point.

    python scripts/backfill_project_members.py --dry-run      # default: change nothing
    python scripts/backfill_project_members.py --apply
    python scripts/backfill_project_members.py --apply --workspace <id>

Idempotent: people who already have a row, in any status, are left exactly as
they are — including anyone deliberately removed from a project.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select  # noqa: E402

import aexy.models  # noqa: E402,F401  (register every mapper so FKs resolve)
from aexy.core.database import get_async_session  # noqa: E402
from aexy.models.project import Project, ProjectMember  # noqa: E402
from aexy.models.workspace import Workspace, WorkspaceMember  # noqa: E402


async def main(apply: bool, workspace_filter: str | None) -> int:
    async with get_async_session() as db:
        stmt = select(Workspace.id, Workspace.name)
        if workspace_filter:
            stmt = stmt.where(Workspace.id == workspace_filter)
        workspaces = (await db.execute(stmt)).all()

        if not workspaces:
            print("No workspaces matched.")
            return 1

        total_added = 0

        for ws_id, ws_name in workspaces:
            members = (
                await db.execute(
                    select(WorkspaceMember.developer_id).where(
                        WorkspaceMember.workspace_id == ws_id,
                        WorkspaceMember.status == "active",
                    )
                )
            ).scalars().all()
            projects = (
                await db.execute(
                    select(Project.id, Project.name).where(
                        Project.workspace_id == ws_id,
                        Project.is_active.is_(True),
                    )
                )
            ).all()

            if not members or not projects:
                continue

            print(f"\n{ws_name}  ({ws_id})")
            for project_id, project_name in projects:
                existing = {
                    str(d)
                    for d in (
                        await db.execute(
                            select(ProjectMember.developer_id).where(
                                ProjectMember.project_id == project_id
                            )
                        )
                    ).scalars().all()
                }
                missing = [str(d) for d in members if str(d) not in existing]
                if not missing:
                    print(f"  ok        {project_name}")
                    continue

                verb = "added" if apply else "would add"
                print(f"  {verb} {len(missing):>4}  {project_name}")
                total_added += len(missing)

                if not apply:
                    continue

                now = datetime.now(timezone.utc)
                for developer_id in missing:
                    db.add(
                        ProjectMember(
                            id=str(uuid4()),
                            project_id=str(project_id),
                            developer_id=developer_id,
                            role_id=None,
                            status="active",
                            joined_at=now,
                        )
                    )

        if apply:
            await db.commit()
            print(f"\nAdded {total_added} project memberships.")
        else:
            print(
                f"\nDry run: {total_added} memberships would be added."
                " Re-run with --apply to write them."
            )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="write the rows (default is a dry run)"
    )
    parser.add_argument("--dry-run", action="store_true", help="the default; accepted for clarity")
    parser.add_argument("--workspace", help="restrict to one workspace id")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.apply and not args.dry_run, args.workspace)))

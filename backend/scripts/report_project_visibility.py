"""Say what switching a workspace to member-scoped projects would cost.

`project_visibility = "members"` narrows a workspace's project list to the
projects each person actually belongs to — as a project member, or through a
team on the project's board. Existing workspaces are left on `"workspace"` by
the migration, so nothing changes until somebody chooses to switch one.

This is the thing to run before making that choice. It prints, per project, who
can see it today and who would still see it afterwards, and it changes nothing.

    python scripts/report_project_visibility.py
    python scripts/report_project_visibility.py --workspace <id>

People holding `can_view_all_projects` (owners, admins and managers by default)
are counted separately, because they keep seeing everything either way.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy import select  # noqa: E402

import aexy.models  # noqa: E402,F401  (register every mapper so FKs resolve)
from aexy.core.database import get_async_session  # noqa: E402
from aexy.models.project import ProjectMember, ProjectTeam  # noqa: E402
from aexy.models.team import TeamMember  # noqa: E402
from aexy.models.workspace import Workspace, WorkspaceMember  # noqa: E402
from aexy.services.permission_service import PermissionService  # noqa: E402
from aexy.services.project_service import ProjectService  # noqa: E402


async def main(workspace_filter: str | None) -> int:
    async with get_async_session() as db:
        stmt = select(Workspace.id, Workspace.name, Workspace.settings)
        if workspace_filter:
            stmt = stmt.where(Workspace.id == workspace_filter)
        workspaces = (await db.execute(stmt)).all()

        if not workspaces:
            print("No workspaces matched.")
            return 1

        permissions = PermissionService(db)

        for ws_id, ws_name, settings in workspaces:
            mode = (settings or {}).get("project_visibility") or "members (unset)"
            members = (
                await db.execute(
                    select(WorkspaceMember.developer_id).where(
                        WorkspaceMember.workspace_id == ws_id,
                        WorkspaceMember.status == "active",
                    )
                )
            ).scalars().all()

            sees_all = set()
            for developer_id in members:
                if await permissions.check_permission(
                    str(ws_id), str(developer_id), "can_view_all_projects"
                ):
                    sees_all.add(str(developer_id))

            projects = await ProjectService(db).list_projects(str(ws_id))

            print(f"\n{ws_name}  ({ws_id})")
            print(f"  project_visibility: {mode}")
            print(
                f"  {len(members)} active members, "
                f"{len(sees_all)} of them see every project regardless"
            )

            if not projects:
                print("  no projects")
                continue

            for project in projects:
                direct = (
                    await db.execute(
                        select(ProjectMember.developer_id).where(
                            ProjectMember.project_id == project.id,
                            ProjectMember.status == "active",
                        )
                    )
                ).scalars().all()
                via_team = (
                    await db.execute(
                        select(TeamMember.developer_id)
                        .join(ProjectTeam, ProjectTeam.team_id == TeamMember.team_id)
                        .where(ProjectTeam.project_id == project.id)
                    )
                ).scalars().all()

                attached = {str(d) for d in direct} | {str(d) for d in via_team}
                keeps = attached | sees_all
                losing = {str(d) for d in members} - keeps

                marker = "  " if not losing else "! "
                print(
                    f"  {marker}{project.name}"
                    f" — {len(keeps)} keep access, {len(losing)} lose it"
                    f"  (members: {len(direct)} direct, {len(via_team)} via board)"
                )

        print(
            "\nLines marked ! would hide that project from somebody who can see it today."
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", help="report on one workspace id")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(main(args.workspace)))

"""Who can see which projects.

Before this, `GET /workspaces/{id}/projects` returned every project in the
workspace to anyone holding `can_view_projects` — which every role except a
deliberately stripped one holds. A developer on one team saw, and could open,
every other team's board.

The rule now: a workspace set to `project_visibility = "members"` shows a
person the projects they are attached to, either directly (`project_members`)
or through a team on the project's board. Owners, admins and managers hold
`can_view_all_projects` and keep seeing everything. Workspaces still on
`"workspace"` behave exactly as they did.

The board route matters as much as the direct one: projects only auto-enrol
their *creator* as a member, so in practice people are attached through the
board. A rule that checked only `project_members` would hide projects from the
people working in them, which is why `test_team_member_sees_the_board_they_work_on`
is here.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.role import CustomRole
from aexy.models.team import TeamMember, TeamMemberRole
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.project_service import (
    PROJECT_VISIBILITY_MEMBERS,
    PROJECT_VISIBILITY_WORKSPACE,
    ProjectService,
    can_see_project,
)


async def _developer(db: AsyncSession, name: str) -> Developer:
    dev = Developer(name=name)
    db.add(dev)
    await db.flush()
    return dev


async def _workspace(db: AsyncSession, slug: str, mode: str) -> tuple[Workspace, Developer]:
    owner = await _developer(db, f"owner-{slug}")
    ws = Workspace(
        name=f"WS {slug}",
        slug=slug,
        owner_id=owner.id,
        settings={"project_visibility": mode},
    )
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws, owner


async def _join(
    db: AsyncSession, ws: Workspace, dev: Developer, role: str = "member"
) -> WorkspaceMember:
    member = WorkspaceMember(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        developer_id=dev.id,
        role=role,
        status="active",
    )
    db.add(member)
    await db.commit()
    return member


async def _project(db: AsyncSession, ws: Workspace, slug: str, creator: Developer | None = None):
    project = await ProjectService(db).create_project(
        workspace_id=ws.id,
        name=f"P {slug}",
        created_by_id=str(creator.id) if creator else None,
    )
    await db.commit()
    await db.refresh(project)
    return project


@pytest.mark.asyncio
async def test_member_sees_only_their_own_projects(db_session: AsyncSession) -> None:
    ws, _ = await _workspace(db_session, "ws-scoped", PROJECT_VISIBILITY_MEMBERS)
    dev = await _developer(db_session, "dev")
    await _join(db_session, ws, dev)

    mine = await _project(db_session, ws, "mine", creator=dev)
    await _project(db_session, ws, "theirs")

    service = ProjectService(db_session)
    visible = await service.list_projects(ws.id, visible_to_developer_id=str(dev.id))

    assert [p.id for p in visible] == [mine.id]


@pytest.mark.asyncio
async def test_team_member_sees_the_board_they_work_on(db_session: AsyncSession) -> None:
    """Attached through the board, with no `project_members` row of their own."""
    ws, _ = await _workspace(db_session, "ws-board", PROJECT_VISIBILITY_MEMBERS)
    dev = await _developer(db_session, "dev-board")
    await _join(db_session, ws, dev)

    project = await _project(db_session, ws, "board")

    service = ProjectService(db_session)
    assert await service.list_projects(ws.id, visible_to_developer_id=str(dev.id)) == []

    # The board shares the project's id.
    db_session.add(
        TeamMember(
            id=str(uuid.uuid4()),
            team_id=project.id,
            developer_id=dev.id,
            role=TeamMemberRole.MEMBER.value,
            source="manual",
        )
    )
    await db_session.commit()

    visible = await service.list_projects(ws.id, visible_to_developer_id=str(dev.id))
    assert [p.id for p in visible] == [project.id]


@pytest.mark.asyncio
async def test_removed_member_stops_seeing_the_project(db_session: AsyncSession) -> None:
    ws, _ = await _workspace(db_session, "ws-removed", PROJECT_VISIBILITY_MEMBERS)
    dev = await _developer(db_session, "dev-removed")
    await _join(db_session, ws, dev)
    # Added as a project member only: the creator of a project also lands on
    # its board as lead, and that second attachment would keep the project
    # visible here for a reason this test is not about.
    project = await _project(db_session, ws, "removed")
    service = ProjectService(db_session)
    await service.add_member(project_id=project.id, developer_id=str(dev.id))
    await db_session.commit()

    assert len(await service.list_projects(ws.id, visible_to_developer_id=str(dev.id))) == 1

    await service.remove_member(project.id, str(dev.id))
    await db_session.commit()

    assert await service.list_projects(ws.id, visible_to_developer_id=str(dev.id)) == []


@pytest.mark.asyncio
async def test_workspace_mode_shows_everything(db_session: AsyncSession) -> None:
    """A workspace that has not switched over behaves exactly as before."""
    ws, _ = await _workspace(db_session, "ws-open", PROJECT_VISIBILITY_WORKSPACE)
    dev = await _developer(db_session, "dev-open")
    await _join(db_session, ws, dev)
    a = await _project(db_session, ws, "a")
    b = await _project(db_session, ws, "b")

    assert await can_see_project(db_session, ws.id, a.id, str(dev.id)) is True
    assert await can_see_project(db_session, ws.id, b.id, str(dev.id)) is True


@pytest.mark.asyncio
async def test_can_view_all_projects_opts_a_role_out_of_scoping(
    db_session: AsyncSession,
) -> None:
    ws, _ = await _workspace(db_session, "ws-manager", PROJECT_VISIBILITY_MEMBERS)
    manager = await _developer(db_session, "manager")
    membership = await _join(db_session, ws, manager)

    role = CustomRole(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="Manager",
        slug="manager",
        based_on_template="manager",
        is_system=True,
        permissions=["can_view_projects", "can_view_all_projects"],
        is_active=True,
    )
    db_session.add(role)
    await db_session.flush()
    membership.role_id = role.id
    await db_session.commit()

    project = await _project(db_session, ws, "not-theirs")

    assert await can_see_project(db_session, ws.id, project.id, str(manager.id)) is True


@pytest.mark.asyncio
async def test_workspace_owner_always_sees_every_project(db_session: AsyncSession) -> None:
    """Resolved from `workspaces.owner_id`, so an owner sitting on an admin
    membership row is not locked out of their own workspace."""
    ws, owner = await _workspace(db_session, "ws-owner", PROJECT_VISIBILITY_MEMBERS)
    await _join(db_session, ws, owner, role="admin")
    project = await _project(db_session, ws, "someone-elses")

    assert await can_see_project(db_session, ws.id, project.id, str(owner.id)) is True


@pytest.mark.asyncio
async def test_non_member_sees_nothing(db_session: AsyncSession) -> None:
    ws, _ = await _workspace(db_session, "ws-stranger", PROJECT_VISIBILITY_MEMBERS)
    stranger = await _developer(db_session, "stranger")
    await _join(db_session, ws, stranger)
    project = await _project(db_session, ws, "closed")

    service = ProjectService(db_session)
    assert await service.list_projects(ws.id, visible_to_developer_id=str(stranger.id)) == []
    assert await can_see_project(db_session, ws.id, project.id, str(stranger.id)) is False


@pytest.mark.asyncio
async def test_visibility_mode_defaults_to_members_when_unset(
    db_session: AsyncSession,
) -> None:
    """The migration stamps existing workspaces explicitly; anything created
    after it starts scoped."""
    owner = await _developer(db_session, "owner-unset")
    ws = Workspace(name="WS unset", slug="ws-unset", owner_id=owner.id, settings={})
    db_session.add(ws)
    await db_session.commit()

    assert await ProjectService(db_session).get_visibility_mode(ws.id) == (
        PROJECT_VISIBILITY_MEMBERS
    )

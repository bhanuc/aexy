"""The team-keyed routes outside sprints, when a workspace scopes its projects.

A project's sprint board is a `Team` carrying the project's own id, so every
`/teams/{team_id}/...` route in the product is a route that can be handed a
project id. The sprint and board surfaces were closed with the scoping itself;
these three were not, and each describes the project plainly enough:

* **on-call** — who is on the rota for it, and the ability to change that;
* **learning** — the team's people, their skill gaps and recommendations;
* **repositories** — which repositories the project works on, and linking more.

Each module funnels its team routes through one helper, so one call each closes
all of them. These tests pin the helpers, not the routes, because the helper is
the thing every route shares.

The guard is silent for a team that is not a project's board, which is what
keeps ordinary teams — the majority — working exactly as before.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.learning import _require_team_workspace_member
from aexy.api.oncall import verify_workspace_access as oncall_verify
from aexy.api.workspace_repositories import _verify_team_role
from aexy.models.developer import Developer
from aexy.models.team import Team
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.services.project_service import (
    PROJECT_VISIBILITY_MEMBERS,
    PROJECT_VISIBILITY_WORKSPACE,
    ProjectService,
)


async def _developer(db: AsyncSession, name: str) -> Developer:
    dev = Developer(name=name)
    db.add(dev)
    await db.flush()
    return dev


async def _scoped_workspace(db: AsyncSession, slug: str, mode: str = PROJECT_VISIBILITY_MEMBERS):
    """A workspace, its owner, and a plain member who is on nothing."""
    owner = await _developer(db, f"owner-{slug}")
    ws = Workspace(
        name=f"WS {slug}",
        slug=slug,
        owner_id=owner.id,
        settings={"project_visibility": mode},
    )
    db.add(ws)
    await db.flush()

    outsider = await _developer(db, f"outsider-{slug}")
    # Both hold a membership row: these helpers ask `WorkspaceService` for a
    # workspace role before anything else, and that reads the row rather than
    # `workspaces.owner_id`. Without one for the owner the test would be
    # measuring a 403 it never meant to provoke.
    for developer, role in ((owner, "owner"), (outsider, "member")):
        db.add(
            WorkspaceMember(
                id=str(uuid.uuid4()),
                workspace_id=ws.id,
                developer_id=developer.id,
                role=role,
                status="active",
            )
        )
    await db.commit()
    await db.refresh(ws)
    return ws, owner, outsider


async def _project(db: AsyncSession, ws: Workspace, slug: str, creator: Developer | None = None):
    project = await ProjectService(db).create_project(
        workspace_id=ws.id,
        name=f"P {slug}",
        created_by_id=str(creator.id) if creator else None,
    )
    await db.commit()
    await db.refresh(project)
    return project


async def _plain_team(db: AsyncSession, ws: Workspace, name: str) -> Team:
    """A team that is nobody's board — the majority of them."""
    team = Team(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name=name,
        slug=name.lower().replace(" ", "-"),
    )
    db.add(team)
    await db.commit()
    return team


@pytest.mark.asyncio
async def test_oncall_hides_the_rota_of_a_project_the_caller_is_not_on(
    db_session: AsyncSession,
) -> None:
    ws, owner, outsider = await _scoped_workspace(db_session, "ws-oncall")
    project = await _project(db_session, ws, "oncall", creator=owner)

    with pytest.raises(HTTPException) as caught:
        await oncall_verify(ws.id, outsider, db_session, "viewer", team_id=project.id)
    assert caught.value.status_code == 404

    # The person whose project it is still gets through.
    await oncall_verify(ws.id, owner, db_session, "viewer", team_id=project.id)


@pytest.mark.asyncio
async def test_learning_hides_a_board_the_caller_is_not_on(
    db_session: AsyncSession,
) -> None:
    ws, owner, outsider = await _scoped_workspace(db_session, "ws-learning")
    project = await _project(db_session, ws, "learning", creator=owner)

    with pytest.raises(HTTPException) as caught:
        await _require_team_workspace_member(db_session, project.id, str(outsider.id))
    assert caught.value.status_code == 404

    team = await _require_team_workspace_member(db_session, project.id, str(owner.id))
    assert str(team.id) == project.id


@pytest.mark.asyncio
async def test_repositories_hide_a_board_the_caller_is_not_on(
    db_session: AsyncSession,
) -> None:
    ws, owner, outsider = await _scoped_workspace(db_session, "ws-repos")
    project = await _project(db_session, ws, "repos", creator=owner)

    with pytest.raises(HTTPException) as caught:
        await _verify_team_role(db_session, project.id, str(outsider.id), "viewer")
    assert caught.value.status_code == 404

    team = await _verify_team_role(db_session, project.id, str(owner.id), "viewer")
    assert str(team.id) == project.id


@pytest.mark.asyncio
async def test_a_team_that_is_not_a_board_is_untouched(
    db_session: AsyncSession,
) -> None:
    """The guard must ignore ids that name no project.

    Most teams are not boards, and every route in these three modules now calls
    it — so a guard that treated "no project with this id" as "not allowed"
    would take on-call, learning and repositories away from every ordinary team
    in a scoped workspace.
    """
    ws, _, outsider = await _scoped_workspace(db_session, "ws-plain")
    team = await _plain_team(db_session, ws, "Support")

    await oncall_verify(ws.id, outsider, db_session, "viewer", team_id=str(team.id))
    assert await _require_team_workspace_member(db_session, str(team.id), str(outsider.id))
    assert await _verify_team_role(db_session, str(team.id), str(outsider.id), "viewer")


@pytest.mark.asyncio
async def test_an_unscoped_workspace_is_unchanged(
    db_session: AsyncSession,
) -> None:
    """Every workspace that exists today is on this setting."""
    ws, owner, outsider = await _scoped_workspace(
        db_session, "ws-unscoped", PROJECT_VISIBILITY_WORKSPACE
    )
    project = await _project(db_session, ws, "unscoped", creator=owner)

    await oncall_verify(ws.id, outsider, db_session, "viewer", team_id=project.id)
    assert await _require_team_workspace_member(db_session, project.id, str(outsider.id))
    assert await _verify_team_role(db_session, project.id, str(outsider.id), "viewer")

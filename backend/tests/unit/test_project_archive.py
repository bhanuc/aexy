"""Archiving a project, as distinct from deleting one.

`list_projects` has always taken an `include_archived` flag and it has never
worked: deleting a project wrote both `is_active = False` and
`status = "archived"`, while the listing filters on `is_active`
unconditionally — so the only thing that ever set the archived status also made
the row permanently invisible, flag or no flag.

These tests pin the two apart: archiving owns `status` and is reversible,
deleting owns `is_active` and is not.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.team import Team
from aexy.models.workspace import Workspace
from aexy.services.project_service import ProjectService


async def _make_workspace(db: AsyncSession, slug: str) -> Workspace:
    dev = Developer(name=f"U {slug}")
    db.add(dev)
    await db.flush()

    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _make_project(db: AsyncSession, ws: Workspace, slug: str):
    """A project through the service, so it gets the board team as in production."""
    service = ProjectService(db)
    project = await service.create_project(workspace_id=ws.id, name=f"P {slug}")
    await db.commit()
    await db.refresh(project)
    return project


@pytest.mark.asyncio
async def test_archived_project_is_hidden_by_default_and_returned_on_request(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-archive")
    project = await _make_project(db_session, ws, "p-archive")
    service = ProjectService(db_session)

    assert [p.id for p in await service.list_projects(ws.id)] == [project.id]

    await service.archive_project(project.id)
    await db_session.commit()

    assert await service.list_projects(ws.id) == []

    with_archived = await service.list_projects(ws.id, include_archived=True)
    assert [p.id for p in with_archived] == [project.id]
    assert with_archived[0].status == "archived"


@pytest.mark.asyncio
async def test_archiving_takes_the_board_out_of_circulation(
    db_session: AsyncSession,
) -> None:
    """The board shares the project's id, and an active board is still offered
    by every team picker in the product."""
    ws = await _make_workspace(db_session, "ws-board")
    project = await _make_project(db_session, ws, "p-board")
    service = ProjectService(db_session)

    async def board_is_active() -> bool:
        team = (
            await db_session.execute(select(Team).where(Team.id == project.id))
        ).scalar_one()
        return team.is_active

    assert await board_is_active() is True

    await service.archive_project(project.id)
    await db_session.commit()
    assert await board_is_active() is False

    await service.unarchive_project(project.id)
    await db_session.commit()
    assert await board_is_active() is True


@pytest.mark.asyncio
async def test_unarchive_restores_the_project_to_the_default_listing(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-unarchive")
    project = await _make_project(db_session, ws, "p-unarchive")
    service = ProjectService(db_session)

    await service.archive_project(project.id)
    await db_session.commit()
    assert await service.list_projects(ws.id) == []

    restored = await service.unarchive_project(project.id)
    await db_session.commit()

    assert restored is not None
    assert restored.status == "active"
    assert [p.id for p in await service.list_projects(ws.id)] == [project.id]


@pytest.mark.asyncio
async def test_deleted_project_stays_hidden_even_with_include_archived(
    db_session: AsyncSession,
) -> None:
    """Deleting is not a louder archive. `include_archived` is for projects
    somebody chose to put away, not for ones they removed."""
    ws = await _make_workspace(db_session, "ws-delete")
    project = await _make_project(db_session, ws, "p-delete")
    service = ProjectService(db_session)

    await service.delete_project(project.id)
    await db_session.commit()

    assert await service.list_projects(ws.id) == []
    assert await service.list_projects(ws.id, include_archived=True) == []


@pytest.mark.asyncio
async def test_delete_leaves_the_recorded_status_alone(
    db_session: AsyncSession,
) -> None:
    """A project deleted while on hold was on hold when it was deleted.
    Overwriting `status` on the way out loses that and nothing needs it."""
    ws = await _make_workspace(db_session, "ws-status")
    project = await _make_project(db_session, ws, "p-status")
    service = ProjectService(db_session)

    await service.update_project(project.id, status="on_hold")
    await db_session.commit()

    await service.delete_project(project.id)
    await db_session.commit()
    await db_session.refresh(project)

    assert project.is_active is False
    assert project.status == "on_hold"

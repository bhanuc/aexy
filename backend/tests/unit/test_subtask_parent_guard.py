"""Subtask parents — `SprintTaskService.resolve_parent_task`.

Three create paths could produce a subtask and none of them checked the parent:

  * `POST /teams/{id}/tasks` (`ProjectTaskCreate`) had no `parent_task_id`
    field at all, so Pydantic dropped it and the caller got a *sibling* task
    with no error to say so.
  * `add_workspace_task` validated the sprint and the status against the
    project but wrote whatever `parent_task_id` it was handed straight onto
    the row.
  * `add_task` did the same.

So a subtree could straddle two projects — or two workspaces — which is the
inconsistency `move_to_project` refuses outright, and the board owning the
parent would show a child on a board it does not own.

The contract now: a parent must be a live, top-level task on the same board.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.project import Project, ProjectTeam
from aexy.models.sprint import Sprint, SprintTask
from aexy.models.team import Team
from aexy.models.workspace import Workspace
from aexy.services.sprint_task_service import (
    SprintTaskService,
    TaskValidationError,
)


async def _make_workspace(db: AsyncSession, slug: str) -> Workspace:
    dev = Developer(name=f"U {slug}")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _make_project(db: AsyncSession, ws: Workspace, slug: str) -> Project:
    p = Project(id=str(uuid.uuid4()), workspace_id=ws.id, name=f"P {slug}", slug=slug)
    db.add(p)
    # SprintTask.team_id FKs to teams.id while the service treats it as the
    # project id, so the matching Team row has to exist (Postgres enforces it).
    db.add(Team(id=p.id, workspace_id=ws.id, name=f"P {slug}", slug=slug))
    # `add_workspace_task` resolves the board from ProjectTeam rather than
    # assuming project_id == team_id, so the link row is part of the fixture.
    db.add(ProjectTeam(id=str(uuid.uuid4()), project_id=p.id, team_id=p.id))
    await db.commit()
    await db.refresh(p)
    return p


async def _make_task(
    db: AsyncSession,
    ws: Workspace,
    project_id: str,
    *,
    title: str = "parent",
    parent_task_id: str | None = None,
    is_archived: bool = False,
) -> SprintTask:
    task = SprintTask(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        team_id=project_id,
        sprint_id=None,
        title=title,
        status="todo",
        source_type="manual",
        source_id=str(uuid.uuid4()),
        priority="medium",
        labels=[],
        parent_task_id=parent_task_id,
        is_archived=is_archived,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)
    return task


@pytest.mark.asyncio
async def test_no_parent_is_not_an_error(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "sp-none")
    project = await _make_project(db_session, ws, "sp-none-p")
    resolved = await SprintTaskService(db_session).resolve_parent_task(
        parent_task_id=None, workspace_id=str(ws.id), team_id=str(project.id)
    )
    assert resolved is None


@pytest.mark.asyncio
async def test_parent_on_the_same_board_is_accepted(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "sp-ok")
    project = await _make_project(db_session, ws, "sp-ok-p")
    parent = await _make_task(db_session, ws, str(project.id))

    resolved = await SprintTaskService(db_session).resolve_parent_task(
        parent_task_id=str(parent.id),
        workspace_id=str(ws.id),
        team_id=str(project.id),
    )
    assert resolved == str(parent.id)


@pytest.mark.asyncio
async def test_parent_in_a_sibling_project_is_refused(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "sp-sib")
    here = await _make_project(db_session, ws, "sp-sib-here")
    there = await _make_project(db_session, ws, "sp-sib-there")
    parent = await _make_task(db_session, ws, str(there.id))

    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).resolve_parent_task(
            parent_task_id=str(parent.id),
            workspace_id=str(ws.id),
            team_id=str(here.id),
        )
    assert exc.value.code == "parent_task_other_project"


@pytest.mark.asyncio
async def test_parent_in_another_workspace_is_refused(db_session: AsyncSession):
    ws_a = await _make_workspace(db_session, "sp-wsa")
    ws_b = await _make_workspace(db_session, "sp-wsb")
    project_a = await _make_project(db_session, ws_a, "sp-wsa-p")
    project_b = await _make_project(db_session, ws_b, "sp-wsb-p")
    parent = await _make_task(db_session, ws_b, str(project_b.id))

    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).resolve_parent_task(
            parent_task_id=str(parent.id),
            workspace_id=str(ws_a.id),
            team_id=str(project_a.id),
        )
    # Workspace is checked before project, so this is the code that surfaces.
    assert exc.value.code == "parent_task_other_workspace"


@pytest.mark.asyncio
async def test_unknown_parent_is_refused(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "sp-404")
    project = await _make_project(db_session, ws, "sp-404-p")

    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).resolve_parent_task(
            parent_task_id=str(uuid.uuid4()),
            workspace_id=str(ws.id),
            team_id=str(project.id),
        )
    assert exc.value.code == "parent_task_not_found"


@pytest.mark.asyncio
async def test_archived_parent_is_refused(db_session: AsyncSession):
    ws = await _make_workspace(db_session, "sp-arch")
    project = await _make_project(db_session, ws, "sp-arch-p")
    parent = await _make_task(db_session, ws, str(project.id), is_archived=True)

    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).resolve_parent_task(
            parent_task_id=str(parent.id),
            workspace_id=str(ws.id),
            team_id=str(project.id),
        )
    assert exc.value.code == "parent_task_not_found"


@pytest.mark.asyncio
async def test_a_subtask_cannot_itself_be_a_parent(db_session: AsyncSession):
    """One level only — `move_to_project` treats grandchildren as orphans and
    the rollup paths assume a single generation, so the depth is capped here
    rather than left to produce a tree nothing downstream handles."""
    ws = await _make_workspace(db_session, "sp-deep")
    project = await _make_project(db_session, ws, "sp-deep-p")
    parent = await _make_task(db_session, ws, str(project.id))
    child = await _make_task(
        db_session, ws, str(project.id), title="child", parent_task_id=str(parent.id)
    )

    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).resolve_parent_task(
            parent_task_id=str(child.id),
            workspace_id=str(ws.id),
            team_id=str(project.id),
        )
    assert exc.value.code == "parent_task_is_subtask"


@pytest.mark.asyncio
async def test_parent_with_no_board_recorded_is_accepted(db_session: AsyncSession):
    """`add_task` — the /sprints/{id}/tasks path — has never written `team_id`,
    deriving the board from the sprint at read time instead. Those parents
    record no board, so there is nothing for a board check to contradict and
    rejecting them would break adding a subtask to an ordinary sprint task."""
    ws = await _make_workspace(db_session, "sp-null")
    project = await _make_project(db_session, ws, "sp-null-p")
    parent = await _make_task(db_session, ws, str(project.id))
    parent.team_id = None
    await db_session.commit()

    resolved = await SprintTaskService(db_session).resolve_parent_task(
        parent_task_id=str(parent.id),
        workspace_id=str(ws.id),
        team_id=str(project.id),
    )
    assert resolved == str(parent.id)

    # The workspace check still bites, so this is not a blanket bypass.
    other_ws = await _make_workspace(db_session, "sp-null-other")
    other_project = await _make_project(db_session, other_ws, "sp-null-other-p")
    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).resolve_parent_task(
            parent_task_id=str(parent.id),
            workspace_id=str(other_ws.id),
            team_id=str(other_project.id),
        )
    assert exc.value.code == "parent_task_other_workspace"


async def _make_sprint(db: AsyncSession, ws: Workspace, project: Project, name: str) -> Sprint:
    sp = Sprint(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        team_id=project.id,
        name=name,
        status="active",
        start_date=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end_date=datetime(2026, 1, 14, tzinfo=timezone.utc),
    )
    db.add(sp)
    await db.commit()
    await db.refresh(sp)
    return sp


@pytest.mark.asyncio
async def test_add_task_refuses_a_bad_parent_even_with_no_sprint(
    db_session: AsyncSession,
):
    """`add_task` used to gate the whole guard on its sprint lookup, so the
    check vanished exactly where the automation callers land: both
    `workflow_actions._create_subtask` and its CRM twin pass
    `sprint_id=parent.sprint_id`, and a project-backlog parent has no sprint.
    An archived, missing or already-nested parent went straight onto the row.

    Without a sprint there is no board to compare against, so the board and
    workspace checks are skipped — but these three are not."""
    ws = await _make_workspace(db_session, "sp-nosprint")
    project = await _make_project(db_session, ws, "sp-nosprint-p")
    service = SprintTaskService(db_session)

    # Missing parent.
    with pytest.raises(TaskValidationError) as exc:
        await service.add_task(
            sprint_id=None, title="orphan child", parent_task_id=str(uuid.uuid4())
        )
    assert exc.value.code == "parent_task_not_found"

    # Archived parent.
    archived = await _make_task(
        db_session, ws, str(project.id), title="gone", is_archived=True
    )
    with pytest.raises(TaskValidationError) as exc:
        await service.add_task(
            sprint_id=None, title="child of archived", parent_task_id=str(archived.id)
        )
    assert exc.value.code == "parent_task_not_found"

    # Already a subtask — one level only.
    parent = await _make_task(db_session, ws, str(project.id))
    child = await _make_task(
        db_session, ws, str(project.id), title="child", parent_task_id=str(parent.id)
    )
    with pytest.raises(TaskValidationError) as exc:
        await service.add_task(
            sprint_id=None, title="grandchild", parent_task_id=str(child.id)
        )
    assert exc.value.code == "parent_task_is_subtask"


@pytest.mark.asyncio
async def test_add_task_accepts_a_good_parent_with_no_sprint(
    db_session: AsyncSession,
):
    """The guard must not break the case the automations actually rely on."""
    ws = await _make_workspace(db_session, "sp-nosprint-ok")
    project = await _make_project(db_session, ws, "sp-nosprint-ok-p")
    parent = await _make_task(db_session, ws, str(project.id))

    subtask = await SprintTaskService(db_session).add_task(
        sprint_id=None, title="legitimate subtask", parent_task_id=str(parent.id)
    )
    assert str(subtask.parent_task_id) == str(parent.id)


@pytest.mark.asyncio
async def test_add_task_refuses_a_parent_on_another_board(db_session: AsyncSession):
    """With a sprint the board is known, so the comparison does apply."""
    ws = await _make_workspace(db_session, "sp-sprint")
    here = await _make_project(db_session, ws, "sp-sprint-here")
    there = await _make_project(db_session, ws, "sp-sprint-there")
    sprint = await _make_sprint(db_session, ws, here, "S1")
    foreign_parent = await _make_task(db_session, ws, str(there.id))

    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).add_task(
            sprint_id=str(sprint.id),
            title="child of a foreign parent",
            parent_task_id=str(foreign_parent.id),
        )
    assert exc.value.code == "parent_task_other_project"

    # A parent on this board is fine.
    ok_parent = await _make_task(db_session, ws, str(here.id), title="local")
    subtask = await SprintTaskService(db_session).add_task(
        sprint_id=str(sprint.id), title="local child", parent_task_id=str(ok_parent.id)
    )
    assert str(subtask.parent_task_id) == str(ok_parent.id)


@pytest.mark.asyncio
async def test_add_workspace_task_refuses_a_foreign_parent(db_session: AsyncSession):
    """The guard has to be on the create path, not only callable from it."""
    ws = await _make_workspace(db_session, "sp-wt")
    here = await _make_project(db_session, ws, "sp-wt-here")
    there = await _make_project(db_session, ws, "sp-wt-there")
    foreign_parent = await _make_task(db_session, ws, str(there.id))

    with pytest.raises(TaskValidationError) as exc:
        await SprintTaskService(db_session).add_workspace_task(
            workspace_id=str(ws.id),
            project_id=str(here.id),
            title="child of a foreign parent",
            parent_task_id=str(foreign_parent.id),
        )
    # `project_has_no_team` would mean the fixture, not the guard, stopped it.
    assert exc.value.code == "parent_task_other_project"

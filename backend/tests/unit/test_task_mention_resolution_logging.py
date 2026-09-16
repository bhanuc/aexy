"""Why a `[workspace-slug:task-key]` mention did not link.

Resolution failure used to be a bare `continue`: the reference was parsed,
matched nothing, and nothing was written anywhere. From the outside — the
GitHub side and the task panel alike — a wrong slug, a wrong key and a
repository the workspace had simply never adopted all looked identical, and
all looked like "the feature does nothing". These pin that each miss now says
which one it was, and that the tenant guard still refuses the link.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.repository import Repository, WorkspaceRepository
from aexy.models.sprint import SprintTask
from aexy.models.team import Team
from aexy.models.workspace import Workspace
from aexy.services.github_task_sync_service import GitHubTaskSyncService

REPO = "acme/widgets"


async def _make_task(db: AsyncSession, slug: str, task_key: int) -> SprintTask:
    dev = Developer(name=f"Dev {slug}", email=f"{slug}@example.test")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.flush()
    team = Team(id=str(uuid.uuid4()), workspace_id=ws.id, name="T", slug=f"t-{slug}")
    db.add(team)
    await db.flush()
    task = SprintTask(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        team_id=team.id,
        sprint_id=None,
        title="Ship it",
        status="todo",
        source_type="manual",
        source_id=f"src-{slug}",
        priority="medium",
        task_key=task_key,
    )
    db.add(task)
    await db.flush()
    return task


async def _adopt(db: AsyncSession, workspace_id: str, full_name: str) -> None:
    repo = Repository(
        id=str(uuid.uuid4()),
        github_id=abs(hash(full_name)) % 10_000_000,
        full_name=full_name,
        name=full_name.split("/")[-1],
        owner_login=full_name.split("/")[0],
        owner_type="Organization",
        is_private=False,
        is_fork=False,
        is_archived=False,
        default_branch="main",
    )
    db.add(repo)
    await db.flush()
    db.add(
        WorkspaceRepository(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            repository_id=repo.id,
            is_active=True,
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_unadopted_repository_is_refused_and_says_so(
    db_session: AsyncSession, caplog
):
    """The task exists, but the mentioning repo is not the workspace's."""
    task = await _make_task(db_session, "acme-ws", 22)
    service = GitHubTaskSyncService(db_session)

    with caplog.at_level(logging.WARNING):
        found = await service._find_aexy_task("acme-ws", "22", repository=REPO)

    assert found is None, "tenant guard must still refuse the link"
    assert "has not adopted" in caplog.text
    assert "acme-ws" in caplog.text and REPO in caplog.text
    assert str(task.task_key) in caplog.text


@pytest.mark.asyncio
async def test_adopted_repository_resolves(db_session: AsyncSession):
    """Same mention, same repo — but adopted. The guard lets it through."""
    task = await _make_task(db_session, "beta-ws", 7)
    await _adopt(db_session, task.workspace_id, REPO)

    service = GitHubTaskSyncService(db_session)
    found = await service._find_aexy_task("beta-ws", "7", repository=REPO)

    assert found is not None
    assert found.id == task.id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "slug,key",
    [("no-such-workspace", "22"), ("gamma-ws", "99999")],
    ids=["unknown-slug", "unknown-task-key"],
)
async def test_no_match_says_no_match(
    db_session: AsyncSession, caplog, slug: str, key: str
):
    """A wrong slug and a wrong key are one reason, distinct from adoption."""
    await _make_task(db_session, "gamma-ws", 1)
    service = GitHubTaskSyncService(db_session)

    with caplog.at_level(logging.WARNING):
        found = await service._find_aexy_task(slug, key, repository=REPO)

    assert found is None
    assert "matched no task" in caplog.text
    assert "has not adopted" not in caplog.text

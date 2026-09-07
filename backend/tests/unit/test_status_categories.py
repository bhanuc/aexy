"""Unit tests for the status-categories table and its resolver.

Covers:
  1. ``seed_default_statuses`` also seeds the 6 canonical categories.
  2. Project-scoped categories override workspace defaults.
  3. ``create_status`` rejects an unknown category slug.
  4. ``create_status`` lazy-seeds categories for legacy workspaces.
  5. ``delete_category`` refuses to drop a category that's still in use.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.project import Project
from aexy.models.workspace import Workspace
from aexy.services.sprint_task_service import TaskValidationError
from aexy.services.task_config_service import (
    DEFAULT_CATEGORIES,
    TaskConfigService,
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
    await db.commit()
    await db.refresh(p)
    return p


@pytest.mark.asyncio
async def test_seed_default_statuses_also_seeds_six_canonical_categories(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-cats-seed")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    cats = await service.get_categories(ws.id)
    slugs = {c.slug for c in cats}
    assert slugs == {c["slug"] for c in DEFAULT_CATEGORIES}
    # `semantics` is what business logic depends on — make sure each canonical
    # category has the expected bucket.
    by_slug = {c.slug: c.semantics for c in cats}
    assert by_slug["backlog"] == "open"
    assert by_slug["todo"] == "open"
    assert by_slug["in_progress"] == "active"
    assert by_slug["in_review"] == "active"
    assert by_slug["done"] == "done"
    assert by_slug["cancelled"] == "cancelled"


@pytest.mark.asyncio
async def test_get_categories_for_project_falls_back_to_workspace(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-cats-fb")
    project = await _make_project(db_session, ws, "p-cats-fb")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    resolved = await service.get_categories_for_project(ws.id, project.id)
    # Project has no rows of its own; fall back to workspace defaults.
    assert all(c.project_id is None for c in resolved)
    assert len(resolved) == len(DEFAULT_CATEGORIES)


@pytest.mark.asyncio
async def test_project_category_override_takes_precedence(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-cats-ovr")
    project = await _make_project(db_session, ws, "p-cats-ovr")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await service.create_category(
        workspace_id=ws.id,
        slug="design",
        label="Design",
        color="#FF00AA",
        semantics="active",
        project_id=project.id,
    )
    await db_session.commit()

    resolved = await service.get_categories_for_project(ws.id, project.id)
    assert all(c.project_id == project.id for c in resolved)
    assert any(c.slug == "design" for c in resolved)


@pytest.mark.asyncio
async def test_create_status_rejects_unknown_category(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-cats-rej")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    with pytest.raises(TaskValidationError) as exc:
        await service.create_status(
            workspace_id=ws.id,
            name="Should Fail",
            category="nope-not-a-category",
        )
    assert exc.value.code == "unknown_category"


@pytest.mark.asyncio
async def test_create_status_lazy_seeds_categories_for_legacy_workspace(
    db_session: AsyncSession,
) -> None:
    """Workspaces created before the categories table existed can still
    create statuses — the service back-fills the canonical six on first
    write."""
    ws = await _make_workspace(db_session, "ws-cats-lazy")
    service = TaskConfigService(db_session)

    # Note: deliberately skip seed_default_statuses so no categories exist yet.
    # The category slug "todo" is canonical so the lazy-seed should make
    # it available.
    status = await service.create_status(
        workspace_id=ws.id,
        name="Triage",
        category="todo",
    )
    await db_session.commit()
    assert status.category == "todo"

    cats = await service.get_categories(ws.id)
    assert {c.slug for c in cats} == {c["slug"] for c in DEFAULT_CATEGORIES}


@pytest.mark.asyncio
async def test_delete_category_in_use_is_refused(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-cats-del")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    todo_cat = await service.get_category_by_slug(ws.id, "todo")
    assert todo_cat is not None

    with pytest.raises(TaskValidationError) as exc:
        await service.delete_category(todo_cat.id)
    assert exc.value.code == "category_in_use"


@pytest.mark.asyncio
async def test_update_status_rejects_unknown_category(
    db_session: AsyncSession,
) -> None:
    ws = await _make_workspace(db_session, "ws-cats-upd")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    todo_status = await service.get_status_by_slug(ws.id, "todo")
    assert todo_status is not None

    with pytest.raises(TaskValidationError) as exc:
        await service.update_status(
            status_id=todo_status.id,
            category="ghost-category",
        )
    assert exc.value.code == "unknown_category"


@pytest.mark.asyncio
async def test_create_status_rejects_duplicate_display_name(
    db_session: AsyncSession,
) -> None:
    """Two statuses with the same name in the same scope would render two
    identical kanban columns. Reject on the second create so the operator
    notices and picks a distinct name."""
    ws = await _make_workspace(db_session, "ws-dup-name")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    await service.create_status(workspace_id=ws.id, name="On Hold", category="todo")
    await db_session.commit()

    with pytest.raises(TaskValidationError) as exc:
        await service.create_status(workspace_id=ws.id, name="On Hold", category="todo")
    assert exc.value.code == "status_name_exists"

    with pytest.raises(TaskValidationError) as exc:
        # Case-insensitive — `on hold` would still collide with the existing row.
        await service.create_status(workspace_id=ws.id, name="on hold", category="todo")
    assert exc.value.code == "status_name_exists"


@pytest.mark.asyncio
async def test_project_scoped_create_preserves_inherited_categories(
    db_session: AsyncSession,
) -> None:
    """Regression: adding a project category used to look like a wipe.

    ``get_categories_for_project`` resolves project rows *or* workspace
    defaults — never a union. So the first project-scoped insert flipped the
    project from "6 inherited categories" to "1 category", and the status
    admin rendered exactly one bucket. Creating a project category must fork
    the workspace set first, the way ``create_status`` already does.
    """
    ws = await _make_workspace(db_session, "ws-cats-fork")
    project = await _make_project(db_session, ws, "p-cats-fork")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    await service.create_category(
        workspace_id=ws.id,
        slug="needs_revision",
        label="Needs Revision",
        semantics="open",
        project_id=project.id,
    )
    await db_session.commit()

    resolved = await service.get_categories_for_project(ws.id, project.id)
    slugs = {c.slug for c in resolved}
    # The new bucket plus every inherited one, now owned by the project.
    assert slugs == {c["slug"] for c in DEFAULT_CATEGORIES} | {"needs_revision"}
    assert all(c.project_id == project.id for c in resolved)

    # Workspace defaults are untouched — other projects keep inheriting them.
    ws_cats = await service.get_categories(ws.id, project_id=None)
    assert {c.slug for c in ws_cats} == {c["slug"] for c in DEFAULT_CATEGORIES}


@pytest.mark.asyncio
async def test_second_project_category_does_not_reclone(
    db_session: AsyncSession,
) -> None:
    """The fork happens once; later creates just append."""
    ws = await _make_workspace(db_session, "ws-cats-fork2")
    project = await _make_project(db_session, ws, "p-cats-fork2")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    await db_session.commit()

    for slug in ("needs_revision", "blocked"):
        await service.create_category(
            workspace_id=ws.id,
            slug=slug,
            label=slug,
            project_id=project.id,
        )
    await db_session.commit()

    rows = await service.get_categories(ws.id, project_id=project.id)
    assert len(rows) == len(DEFAULT_CATEGORIES) + 2
    # No duplicate slugs from a second clone pass.
    assert len({r.slug for r in rows}) == len(rows)


@pytest.mark.asyncio
async def test_delete_project_category_ignores_workspace_statuses(
    db_session: AsyncSession,
) -> None:
    """A cloned project category shares its slug with the workspace default.

    The in-use check has to stay inside the category's own scope, otherwise
    every forked bucket is permanently undeletable because some *other*
    project's (or the workspace's) status references the same slug.
    """
    ws = await _make_workspace(db_session, "ws-cats-delscope")
    project = await _make_project(db_session, ws, "p-cats-delscope")
    service = TaskConfigService(db_session)
    await service.seed_default_statuses(ws.id)
    # Forks both categories and statuses into the project.
    await service.create_category(
        workspace_id=ws.id,
        slug="needs_revision",
        label="Needs Revision",
        project_id=project.id,
    )
    await db_session.commit()

    project_cancelled = await service.get_category_by_slug(
        ws.id, "cancelled", project_id=project.id
    )
    assert project_cancelled is not None
    # Nothing in this project uses `cancelled` (default statuses stop at Done),
    # so the delete must go through despite workspace rows existing.
    assert await service.delete_category(project_cancelled.id) is True
    await db_session.commit()

    remaining = await service.get_categories(ws.id, project_id=project.id)
    assert "cancelled" not in {c.slug for c in remaining}
    # Workspace default survives.
    assert await service.get_category_by_slug(ws.id, "cancelled") is not None

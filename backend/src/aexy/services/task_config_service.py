"""Task Configuration Service for managing custom statuses and fields."""

import re
import unicodedata
from uuid import uuid4

from sqlalchemy import or_, select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.sprint import (
    SprintTask,
    WorkspaceCustomField,
    WorkspaceStatusCategory,
    WorkspaceTaskStatus,
)
from aexy.services.sprint_task_service import TaskValidationError


def slugify(text: str) -> str:
    r"""Convert text to a URL-friendly slug.

    Unicode-aware, and specifically mark-aware. The old ``[^\w\s-]`` filter
    dropped combining marks, because Python's ``\w`` covers no mark category —
    so a Devanagari name did not fail, it silently *corrupted*: "समीक्षा में"
    became "समकष_म", every vowel sign stripped. Scripts that carry their vowels
    as marks (Devanagari, Arabic, Thai, Hebrew) were all affected; CJK was
    fine, since those are word characters.

    Every mark category is kept, not just Mn: Devanagari's vowel signs are Mc
    (spacing marks), so filtering on Mn alone still lost "ी" and "ा" and turned
    the example above into "समक्ष_में". Matching on the category's first letter
    keeps Mn, Mc and Me together, and generalises to scripts nobody here
    thought about. ASCII input is unchanged.

    Returns "" for input with no letters or digits at all (an emoji-only name).
    Callers that need a slug must supply their own fallback — see
    ``_unique_slug``.
    """
    text = text.lower()
    text = "".join(
        c
        for c in text
        if c.isalnum()
        or c in "_-"
        or c.isspace()
        or unicodedata.category(c).startswith("M")
    )
    text = re.sub(r'[-\s]+', '_', text)
    return text.strip('_')


# Default statuses to seed for new workspaces
DEFAULT_STATUSES = [
    {"name": "Backlog", "slug": "backlog", "category": "backlog", "color": "#9CA3AF", "position": 0, "is_default": True},
    {"name": "To Do", "slug": "todo", "category": "todo", "color": "#3B82F6", "position": 1, "is_default": False},
    {"name": "In Progress", "slug": "in_progress", "category": "in_progress", "color": "#F59E0B", "position": 2, "is_default": False},
    {"name": "In Review", "slug": "in_review", "category": "in_review", "color": "#8B5CF6", "position": 3, "is_default": False},
    {"name": "Done", "slug": "done", "category": "done", "color": "#10B981", "position": 4, "is_default": False},
]

# Canonical workspace-default categories. Every new workspace starts with
# this set; admins can rename, recolor, or add more from the status admin.
# `semantics` is what burndown/velocity branches on — slugs are user-facing.
DEFAULT_CATEGORIES = [
    {"slug": "backlog",     "label": "Backlog",     "color": "#9CA3AF", "semantics": "open",      "position": 0, "is_default": True},
    {"slug": "todo",        "label": "To Do",       "color": "#3B82F6", "semantics": "open",      "position": 1, "is_default": False},
    {"slug": "in_progress", "label": "In Progress", "color": "#F59E0B", "semantics": "active",    "position": 2, "is_default": False},
    {"slug": "in_review",   "label": "In Review",   "color": "#8B5CF6", "semantics": "active",    "position": 3, "is_default": False},
    {"slug": "done",        "label": "Done",        "color": "#10B981", "semantics": "done",      "position": 4, "is_default": False},
    {"slug": "cancelled",   "label": "Cancelled",   "color": "#EF4444", "semantics": "cancelled", "position": 5, "is_default": False},
]


class TaskConfigService:
    """Service for managing custom task statuses and fields."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _scope_filter(project_id: str | None):
        """WHERE clause for the workspace-default vs. project-override scope."""
        if project_id is None:
            return WorkspaceTaskStatus.project_id.is_(None)
        return WorkspaceTaskStatus.project_id == project_id

    async def _assert_name_unique(
        self,
        workspace_id: str,
        project_id: str | None,
        name: str,
        excluding_id: str | None = None,
    ) -> None:
        """Raise ``status_name_exists`` if another active row in this scope
        already uses this display name (case-insensitive). Two columns titled
        the same on the kanban is the bug we're preventing — slug
        deduplication would silently let it through."""
        stmt = (
            select(WorkspaceTaskStatus.id)
            .where(WorkspaceTaskStatus.workspace_id == workspace_id)
            .where(self._scope_filter(project_id))
            .where(WorkspaceTaskStatus.is_active == True)  # noqa: E712
            .where(func.lower(WorkspaceTaskStatus.name) == name.strip().lower())
        )
        if excluding_id is not None:
            stmt = stmt.where(WorkspaceTaskStatus.id != excluding_id)
        if (await self.db.execute(stmt)).first() is not None:
            raise TaskValidationError("status_name_exists")

    # ==================== Status Management ====================

    async def get_statuses(
        self,
        workspace_id: str,
        include_inactive: bool = False,
        project_id: str | None = None,
    ) -> list[WorkspaceTaskStatus]:
        """Get task statuses scoped to a workspace and (optionally) a project.

        Pass ``project_id=None`` (default) to get workspace defaults only.
        Pass ``project_id="<uuid>"`` to get the rows that belong specifically
        to that project — use ``get_statuses_for_project`` instead if you want
        the fallback-to-workspace behavior, which is what most callers want.
        """
        stmt = (
            select(WorkspaceTaskStatus)
            .where(WorkspaceTaskStatus.workspace_id == workspace_id)
            .where(self._scope_filter(project_id))
        )
        if not include_inactive:
            stmt = stmt.where(WorkspaceTaskStatus.is_active == True)
        stmt = stmt.order_by(WorkspaceTaskStatus.position)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_statuses_for_project(
        self,
        workspace_id: str,
        project_id: str,
        include_inactive: bool = False,
    ) -> list[WorkspaceTaskStatus]:
        """Resolve the effective status set for a given project.

        Returns the project's own status rows when it has any; otherwise the
        workspace-default rows (``project_id IS NULL``). This is the helper to
        use almost everywhere — the UI columns and the validation on task
        create/update all depend on the same resolved set.
        """
        own = await self.get_statuses(workspace_id, include_inactive=include_inactive, project_id=project_id)
        if own:
            return own
        return await self.get_statuses(workspace_id, include_inactive=include_inactive)

    async def _project_has_own_statuses(
        self,
        workspace_id: str,
        project_id: str,
    ) -> bool:
        """Whether ``get_statuses_for_project`` resolves to this project's own
        rows rather than the workspace defaults.

        Matches that resolver exactly — active rows only, so a project whose
        only status rows are soft-deleted counts as still inheriting.
        """
        stmt = (
            select(WorkspaceTaskStatus.id)
            .where(WorkspaceTaskStatus.workspace_id == workspace_id)
            .where(WorkspaceTaskStatus.project_id == project_id)
            .where(WorkspaceTaskStatus.is_active == True)  # noqa: E712
            .limit(1)
        )
        return (await self.db.execute(stmt)).first() is not None

    async def get_status(self, status_id: str) -> WorkspaceTaskStatus | None:
        """Get a status by ID."""
        stmt = select(WorkspaceTaskStatus).where(WorkspaceTaskStatus.id == status_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_status_by_slug(
        self,
        workspace_id: str,
        slug: str,
        project_id: str | None = None,
    ) -> WorkspaceTaskStatus | None:
        """Get a status by slug within a workspace/project scope."""
        stmt = (
            select(WorkspaceTaskStatus)
            .where(WorkspaceTaskStatus.workspace_id == workspace_id)
            .where(WorkspaceTaskStatus.slug == slug)
            .where(self._scope_filter(project_id))
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_status(
        self,
        workspace_id: str,
        name: str,
        category: str = "todo",
        color: str = "#6B7280",
        icon: str | None = None,
        is_default: bool = False,
        project_id: str | None = None,
    ) -> WorkspaceTaskStatus:
        """Create a new task status (workspace default if project_id is None).

        For a project-scoped create on a project that's currently on fallback
        (zero project rows), clone the workspace defaults in first so the
        project doesn't suddenly drop from "N inherited statuses" down to
        "1 manually-added status" via the resolver.
        """
        if project_id is not None:
            # `clone_workspace_statuses_to_project` is a single-project
            # snapshot — `_snapshot_fallback_projects` would scan every
            # project in the workspace, which is wasteful here. The clone
            # helper is idempotent, so no pre-check needed.
            await self.clone_workspace_statuses_to_project(workspace_id, project_id)

        # Validate category against this workspace's category set (with
        # project fallback). Workspaces created before the categories table
        # was introduced may be missing rows — lazy-seed.
        if not await self._resolve_category_slug(workspace_id, category, project_id):
            await self.seed_default_categories(workspace_id)
            if not await self._resolve_category_slug(workspace_id, category, project_id):
                raise TaskValidationError("unknown_category")

        await self._assert_name_unique(workspace_id, project_id, name)

        # Generate unique slug within the (workspace, project) scope. A name
        # with no letters or digits at all ("🎉") slugifies to nothing, and an
        # empty slug fails the column's NOT NULL intent and matches nothing —
        # so fall back to a generic stem and let the dedup loop number it. The
        # display name is what anyone actually sees.
        base_slug = slugify(name) or "status"
        slug = base_slug
        counter = 1

        while await self.get_status_by_slug(workspace_id, slug, project_id=project_id):
            slug = f"{base_slug}_{counter}"
            counter += 1

        # Get next position within the scope.
        stmt = (
            select(func.coalesce(func.max(WorkspaceTaskStatus.position), -1) + 1)
            .where(WorkspaceTaskStatus.workspace_id == workspace_id)
            .where(self._scope_filter(project_id))
        )
        result = await self.db.execute(stmt)
        next_position = result.scalar() or 0

        status = WorkspaceTaskStatus(
            id=str(uuid4()),
            workspace_id=workspace_id,
            project_id=project_id,
            name=name,
            slug=slug,
            category=category,
            color=color,
            icon=icon,
            position=next_position,
            is_default=is_default,
            is_active=True,
        )
        self.db.add(status)
        await self.db.flush()
        await self.db.refresh(status)
        return status

    async def clone_workspace_statuses_to_project(
        self,
        workspace_id: str,
        project_id: str,
    ) -> list[WorkspaceTaskStatus]:
        """Copy workspace-default statuses into a project so it can diverge.

        Idempotent: skips if the project already has its own statuses.
        """
        existing = await self.get_statuses(workspace_id, project_id=project_id, include_inactive=True)
        if existing:
            return existing

        defaults = await self.get_statuses(workspace_id, include_inactive=True)
        cloned: list[WorkspaceTaskStatus] = []
        for src in defaults:
            row = WorkspaceTaskStatus(
                id=str(uuid4()),
                workspace_id=workspace_id,
                project_id=project_id,
                name=src.name,
                slug=src.slug,
                category=src.category,
                color=src.color,
                icon=src.icon,
                position=src.position,
                is_default=src.is_default,
                is_active=src.is_active,
            )
            self.db.add(row)
            cloned.append(row)
        await self.db.flush()
        return cloned

    async def _snapshot_fallback_projects(self, workspace_id: str) -> int:
        """Capture the current workspace defaults into every fallback project
        before a destructive workspace-default edit. Returns the number of
        projects snapshotted.

        This is the mechanism that makes "workspace edits don't affect project
        statuses" hold even for projects that haven't yet customized — they
        get an automatic clone the moment a workspace admin renames/deletes/
        reorders, capturing the pre-edit state. Projects that already
        customized are detected (any row with this project_id) and skipped.

        Additive edits (a new workspace status) are *not* destructive and
        should call sites bypass this helper; fallback projects will pick up
        the new status via the resolver and that's the intended behavior.
        """
        # Lazy import — Project lives in a sibling models package and would
        # create a circular import if imported at module top.
        from aexy.models.project import Project

        project_ids_stmt = select(Project.id).where(
            Project.workspace_id == workspace_id
        )
        all_project_ids = list(
            (await self.db.execute(project_ids_stmt)).scalars().all()
        )
        if not all_project_ids:
            return 0

        customized_stmt = (
            select(WorkspaceTaskStatus.project_id)
            .where(WorkspaceTaskStatus.workspace_id == workspace_id)
            .where(WorkspaceTaskStatus.project_id.is_not(None))
            .distinct()
        )
        customized_ids = {
            str(pid)
            for pid in (await self.db.execute(customized_stmt)).scalars().all()
        }

        fallback_ids = [
            str(pid) for pid in all_project_ids if str(pid) not in customized_ids
        ]
        if not fallback_ids:
            return 0

        for pid in fallback_ids:
            await self.clone_workspace_statuses_to_project(workspace_id, pid)

        return len(fallback_ids)

    async def update_status(
        self,
        status_id: str,
        name: str | None = None,
        category: str | None = None,
        color: str | None = None,
        icon: str | None = None,
        is_default: bool | None = None,
    ) -> WorkspaceTaskStatus | None:
        """Update a task status.

        If the row being edited is a workspace default, fallback projects are
        snapshotted first so they retain the pre-edit state. See
        ``_snapshot_fallback_projects`` for why.
        """
        status = await self.get_status(status_id)
        if not status:
            return None

        if status.project_id is None:
            await self._snapshot_fallback_projects(str(status.workspace_id))

        if name is not None:
            await self._assert_name_unique(
                str(status.workspace_id),
                status.project_id,
                name,
                excluding_id=status.id,
            )
            status.name = name
            # Update slug if name changes
            status.slug = slugify(name) or status.slug
        if category is not None:
            if not await self._resolve_category_slug(
                str(status.workspace_id),
                category,
                project_id=status.project_id,
            ):
                raise TaskValidationError("unknown_category")
            status.category = category
        if color is not None:
            status.color = color
        if icon is not None:
            status.icon = icon
        if is_default is not None:
            status.is_default = is_default

        await self.db.flush()
        await self.db.refresh(status)
        return status

    async def count_tasks_using_status(self, status_id: str) -> int:
        """How many active (non-archived) tasks currently point at this status row."""
        stmt = (
            select(func.count(SprintTask.id))
            .where(SprintTask.status_id == status_id)
            .where(SprintTask.is_archived == False)
        )
        return int((await self.db.execute(stmt)).scalar() or 0)

    async def delete_status(
        self,
        status_id: str,
        migrate_to_status_id: str | None = None,
    ) -> bool:
        """Soft delete a status (mark as inactive).

        For workspace defaults: snapshot fallback projects first so they keep
        the to-be-deleted status as a project override.

        ``migrate_to_status_id``: when provided, rewrites every task currently
        pointing at this status row to the target row's id (and legacy slug
        string) before the soft delete. The target must belong to the same
        workspace; for project-scoped sources the target must be either a
        workspace default or scoped to the same project — otherwise the
        migration is refused so tasks can't end up cross-project.
        """
        status = await self.get_status(status_id)
        if not status:
            return False

        if migrate_to_status_id:
            target = await self.get_status(migrate_to_status_id)
            if not target:
                raise TaskValidationError("migration_target_not_found")
            if str(target.workspace_id) != str(status.workspace_id):
                raise TaskValidationError("migration_target_other_workspace")
            if target.id == status.id:
                raise TaskValidationError("migration_target_same_as_source")
            # A workspace-default delete pulls tasks from every project that
            # used it — they can't all land on one project's column. The
            # target must be another workspace default.
            if status.project_id is None and target.project_id is not None:
                raise TaskValidationError("migration_target_other_project")
            # A project-scoped delete must land in the same project (or in
            # workspace-default scope, which is shared and safe).
            if (
                status.project_id is not None
                and target.project_id is not None
                and str(target.project_id) != str(status.project_id)
            ):
                raise TaskValidationError("migration_target_other_project")

            await self.db.execute(
                update(SprintTask)
                .where(SprintTask.status_id == status_id)
                .values(status_id=target.id, status=target.slug)
            )

        if status.project_id is None:
            await self._snapshot_fallback_projects(str(status.workspace_id))

        status.is_active = False
        await self.db.flush()
        return True

    async def reorder_statuses(
        self,
        workspace_id: str,
        status_ids: list[str],
    ) -> list[WorkspaceTaskStatus]:
        """Reorder statuses by providing new order of IDs.

        If any of the IDs are workspace defaults, fallback projects are
        snapshotted first — reordering changes a project's visual workflow
        and counts as destructive in the same sense as a rename.
        """
        if status_ids:
            scope_stmt = select(WorkspaceTaskStatus.project_id).where(
                WorkspaceTaskStatus.id.in_(status_ids),
                WorkspaceTaskStatus.workspace_id == workspace_id,
            )
            touches_workspace_defaults = any(
                pid is None
                for pid in (await self.db.execute(scope_stmt)).scalars().all()
            )
            if touches_workspace_defaults:
                await self._snapshot_fallback_projects(workspace_id)

        for position, status_id in enumerate(status_ids):
            await self.db.execute(
                update(WorkspaceTaskStatus)
                .where(WorkspaceTaskStatus.id == status_id)
                .where(WorkspaceTaskStatus.workspace_id == workspace_id)
                .values(position=position)
            )
        await self.db.flush()
        return await self.get_statuses(workspace_id)

    async def seed_default_statuses(self, workspace_id: str) -> list[WorkspaceTaskStatus]:
        """Seed default statuses (and categories) for a new workspace."""
        await self.seed_default_categories(workspace_id)

        statuses = []
        for status_data in DEFAULT_STATUSES:
            status = WorkspaceTaskStatus(
                id=str(uuid4()),
                workspace_id=workspace_id,
                **status_data,
                is_active=True,
            )
            self.db.add(status)
            statuses.append(status)

        await self.db.flush()
        return statuses

    # ==================== Status Category Management ====================

    @staticmethod
    def _category_scope_filter(project_id: str | None):
        """Same shape as ``_scope_filter`` but for the categories table."""
        if project_id is None:
            return WorkspaceStatusCategory.project_id.is_(None)
        return WorkspaceStatusCategory.project_id == project_id

    async def get_categories(
        self,
        workspace_id: str,
        project_id: str | None = None,
    ) -> list[WorkspaceStatusCategory]:
        """Return categories in a single scope (workspace defaults, or one project)."""
        stmt = (
            select(WorkspaceStatusCategory)
            .where(WorkspaceStatusCategory.workspace_id == workspace_id)
            .where(self._category_scope_filter(project_id))
            .order_by(WorkspaceStatusCategory.position)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_categories_for_project(
        self,
        workspace_id: str,
        project_id: str,
    ) -> list[WorkspaceStatusCategory]:
        """Resolve the effective category set for a project (project rows or workspace fallback)."""
        project_rows = await self.get_categories(workspace_id, project_id=project_id)
        if project_rows:
            return project_rows
        return await self.get_categories(workspace_id, project_id=None)

    async def get_category(self, category_id: str) -> WorkspaceStatusCategory | None:
        stmt = select(WorkspaceStatusCategory).where(WorkspaceStatusCategory.id == category_id)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_category_by_slug(
        self,
        workspace_id: str,
        slug: str,
        project_id: str | None = None,
    ) -> WorkspaceStatusCategory | None:
        stmt = (
            select(WorkspaceStatusCategory)
            .where(WorkspaceStatusCategory.workspace_id == workspace_id)
            .where(WorkspaceStatusCategory.slug == slug)
            .where(self._category_scope_filter(project_id))
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _resolve_category_slug(
        self,
        workspace_id: str,
        slug: str,
        project_id: str | None = None,
    ) -> WorkspaceStatusCategory | None:
        """Resolve a category slug against (project scope → workspace fallback)."""
        if project_id is not None:
            in_project = await self.get_category_by_slug(workspace_id, slug, project_id=project_id)
            if in_project is not None:
                return in_project
        return await self.get_category_by_slug(workspace_id, slug, project_id=None)

    async def clone_workspace_categories_to_project(
        self,
        workspace_id: str,
        project_id: str,
    ) -> list[WorkspaceStatusCategory]:
        """Copy workspace-default categories into a project so it can diverge.

        Mirror of ``clone_workspace_statuses_to_project``. Idempotent: skips
        if the project already has categories of its own. Lazy-seeds the
        workspace defaults for workspaces predating the categories table so
        the project never forks off an empty set.
        """
        existing = await self.get_categories(workspace_id, project_id=project_id)
        if existing:
            return existing

        defaults = await self.get_categories(workspace_id, project_id=None)
        if not defaults:
            await self.seed_default_categories(workspace_id)
            defaults = await self.get_categories(workspace_id, project_id=None)

        cloned: list[WorkspaceStatusCategory] = []
        for src in defaults:
            row = WorkspaceStatusCategory(
                id=str(uuid4()),
                workspace_id=workspace_id,
                project_id=project_id,
                slug=src.slug,
                label=src.label,
                color=src.color,
                semantics=src.semantics,
                position=src.position,
                is_default=src.is_default,
            )
            self.db.add(row)
            cloned.append(row)
        await self.db.flush()
        return cloned

    async def create_category(
        self,
        workspace_id: str,
        slug: str,
        label: str,
        color: str = "#6B7280",
        semantics: str = "open",
        is_default: bool = False,
        project_id: str | None = None,
    ) -> WorkspaceStatusCategory:
        """Create a category in a workspace (or project) scope.

        For a project-scoped create on a project that's currently on fallback
        (zero project rows), clone the workspace categories in first — the
        same guard ``create_status`` applies. Without it the resolver in
        ``get_categories_for_project`` flips from "N inherited categories" to
        "1 manually-added category" the moment the first project row lands,
        which reads to the operator as "adding a category deleted all the
        others".
        """
        if project_id is not None:
            await self.clone_workspace_categories_to_project(workspace_id, project_id)

        existing = await self.get_category_by_slug(workspace_id, slug, project_id=project_id)
        if existing is not None:
            raise TaskValidationError("category_slug_exists")

        stmt = (
            select(func.coalesce(func.max(WorkspaceStatusCategory.position), -1) + 1)
            .where(WorkspaceStatusCategory.workspace_id == workspace_id)
            .where(self._category_scope_filter(project_id))
        )
        next_position = (await self.db.execute(stmt)).scalar() or 0

        category = WorkspaceStatusCategory(
            id=str(uuid4()),
            workspace_id=workspace_id,
            project_id=project_id,
            slug=slug,
            label=label,
            color=color,
            semantics=semantics,
            position=next_position,
            is_default=is_default,
        )
        self.db.add(category)
        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def update_category(
        self,
        category_id: str,
        label: str | None = None,
        color: str | None = None,
        semantics: str | None = None,
        is_default: bool | None = None,
    ) -> WorkspaceStatusCategory | None:
        category = await self.get_category(category_id)
        if not category:
            return None
        if label is not None:
            category.label = label
        if color is not None:
            category.color = color
        if semantics is not None:
            category.semantics = semantics
        if is_default is not None:
            category.is_default = is_default
        await self.db.flush()
        await self.db.refresh(category)
        return category

    async def delete_category(self, category_id: str) -> bool:
        """Delete a category. Refuses if any status row still references it.

        We don't migrate statuses automatically — admins should reassign the
        affected statuses to another category first. The error code carries
        enough context for the UI to render a "reassign N statuses" prompt.
        """
        category = await self.get_category(category_id)
        if not category:
            return False

        in_use_stmt = (
            select(func.count(WorkspaceTaskStatus.id))
            .where(WorkspaceTaskStatus.workspace_id == category.workspace_id)
            .where(WorkspaceTaskStatus.category == category.slug)
            .where(WorkspaceTaskStatus.is_active.is_(True))
        )
        if category.project_id is not None:
            # Only the statuses this project actually renders can reference
            # this row: statuses in another scope resolve the slug against
            # their own scope, never this one. Without a scope filter a
            # cloned project category (`done`, `todo`, …) looks permanently
            # in-use because the workspace defaults share its slug.
            #
            # Which rows those are depends on where the project's statuses
            # come from — a project can fork its categories without forking
            # its statuses (`create_category` clones categories only), and
            # then its board is still drawn from the workspace defaults.
            # Filtering on `project_id == this project` in that state finds
            # nothing and lets the project delete a bucket its own board is
            # using, which is what leaves a status with no column.
            if await self._project_has_own_statuses(
                str(category.workspace_id), str(category.project_id)
            ):
                in_use_stmt = in_use_stmt.where(
                    WorkspaceTaskStatus.project_id == category.project_id
                )
            else:
                in_use_stmt = in_use_stmt.where(
                    WorkspaceTaskStatus.project_id.is_(None)
                )
        else:
            # A workspace default is referenced by the workspace's own
            # statuses plus the statuses of every project whose category
            # scope doesn't define this slug — those resolve it by falling
            # back here. A project holding its own copy of the slug points at
            # that copy instead, so counting it would make an unused
            # workspace category permanently undeletable the moment any
            # project forks its categories.
            shadowing_projects = (
                select(WorkspaceStatusCategory.project_id)
                .where(
                    WorkspaceStatusCategory.workspace_id == category.workspace_id
                )
                .where(WorkspaceStatusCategory.project_id.is_not(None))
                .where(WorkspaceStatusCategory.slug == category.slug)
            )
            in_use_stmt = in_use_stmt.where(
                or_(
                    WorkspaceTaskStatus.project_id.is_(None),
                    WorkspaceTaskStatus.project_id.not_in(shadowing_projects),
                )
            )
        if (await self.db.execute(in_use_stmt)).scalar():
            raise TaskValidationError("category_in_use")

        await self.db.delete(category)
        await self.db.flush()
        return True

    async def reorder_categories(
        self,
        workspace_id: str,
        category_ids: list[str],
        project_id: str | None = None,
    ) -> list[WorkspaceStatusCategory]:
        for position, cat_id in enumerate(category_ids):
            await self.db.execute(
                update(WorkspaceStatusCategory)
                .where(WorkspaceStatusCategory.id == cat_id)
                .where(WorkspaceStatusCategory.workspace_id == workspace_id)
                .values(position=position)
            )
        await self.db.flush()
        return await self.get_categories(workspace_id, project_id=project_id)

    async def seed_default_categories(
        self,
        workspace_id: str,
    ) -> list[WorkspaceStatusCategory]:
        """Seed the 6 canonical workspace-default categories. Idempotent."""
        existing = await self.get_categories(workspace_id, project_id=None)
        existing_slugs = {c.slug for c in existing}

        created: list[WorkspaceStatusCategory] = []
        for cat in DEFAULT_CATEGORIES:
            if cat["slug"] in existing_slugs:
                continue
            row = WorkspaceStatusCategory(
                id=str(uuid4()),
                workspace_id=workspace_id,
                project_id=None,
                **cat,
            )
            self.db.add(row)
            created.append(row)
        if created:
            await self.db.flush()
        return created + existing

    # ==================== Custom Field Management ====================

    async def get_custom_fields(
        self,
        workspace_id: str,
        include_inactive: bool = False,
    ) -> list[WorkspaceCustomField]:
        """Get all custom fields for a workspace."""
        stmt = (
            select(WorkspaceCustomField)
            .where(WorkspaceCustomField.workspace_id == workspace_id)
        )
        if not include_inactive:
            stmt = stmt.where(WorkspaceCustomField.is_active == True)
        stmt = stmt.order_by(WorkspaceCustomField.position)

        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_custom_field(self, field_id: str) -> WorkspaceCustomField | None:
        """Get a custom field by ID."""
        stmt = select(WorkspaceCustomField).where(WorkspaceCustomField.id == field_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_custom_field_by_slug(
        self,
        workspace_id: str,
        slug: str,
    ) -> WorkspaceCustomField | None:
        """Get a custom field by slug within a workspace."""
        stmt = (
            select(WorkspaceCustomField)
            .where(WorkspaceCustomField.workspace_id == workspace_id)
            .where(WorkspaceCustomField.slug == slug)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_custom_field(
        self,
        workspace_id: str,
        name: str,
        field_type: str,
        options: list[dict] | None = None,
        is_required: bool = False,
        default_value: str | None = None,
    ) -> WorkspaceCustomField:
        """Create a new custom field."""
        # Generate unique slug. See `create_status` for why an empty slug gets
        # a generic stem rather than being written as "".
        base_slug = slugify(name) or "field"
        slug = base_slug
        counter = 1

        while await self.get_custom_field_by_slug(workspace_id, slug):
            slug = f"{base_slug}_{counter}"
            counter += 1

        # Get next position
        stmt = (
            select(func.coalesce(func.max(WorkspaceCustomField.position), -1) + 1)
            .where(WorkspaceCustomField.workspace_id == workspace_id)
        )
        result = await self.db.execute(stmt)
        next_position = result.scalar() or 0

        field = WorkspaceCustomField(
            id=str(uuid4()),
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            field_type=field_type,
            options=options,
            is_required=is_required,
            default_value=default_value,
            position=next_position,
            is_active=True,
        )
        self.db.add(field)
        await self.db.flush()
        await self.db.refresh(field)
        return field

    async def update_custom_field(
        self,
        field_id: str,
        name: str | None = None,
        options: list[dict] | None = None,
        is_required: bool | None = None,
        default_value: str | None = None,
    ) -> WorkspaceCustomField | None:
        """Update a custom field."""
        field = await self.get_custom_field(field_id)
        if not field:
            return None

        if name is not None:
            field.name = name
            field.slug = slugify(name) or field.slug
        if options is not None:
            field.options = options
        if is_required is not None:
            field.is_required = is_required
        if default_value is not None:
            field.default_value = default_value

        await self.db.flush()
        await self.db.refresh(field)
        return field

    async def delete_custom_field(self, field_id: str) -> bool:
        """Soft delete a custom field (mark as inactive)."""
        field = await self.get_custom_field(field_id)
        if not field:
            return False

        field.is_active = False
        await self.db.flush()
        return True

    async def reorder_custom_fields(
        self,
        workspace_id: str,
        field_ids: list[str],
    ) -> list[WorkspaceCustomField]:
        """Reorder custom fields by providing new order of IDs."""
        for position, field_id in enumerate(field_ids):
            await self.db.execute(
                update(WorkspaceCustomField)
                .where(WorkspaceCustomField.id == field_id)
                .where(WorkspaceCustomField.workspace_id == workspace_id)
                .values(position=position)
            )
        await self.db.flush()
        return await self.get_custom_fields(workspace_id)

"""Project management service."""

import re
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from aexy.models.project import Project, ProjectMember, ProjectTeam
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.models.developer import Developer
from aexy.models.organization import Department
from aexy.models.service_desk import ServiceDeskStakeholder
from aexy.models.team import Team, TeamMember, TeamMemberRole

#: How much of a workspace's project list a plain member sees.
#:
#: "workspace" is what every workspace did before membership scoping existed:
#: everyone who could view projects saw all of them. "members" narrows the list
#: to the projects a person actually belongs to.
#:
#: Existing workspaces are stamped "workspace" by the migration so nothing
#: disappears on deploy; the absence of the key means "members", so workspaces
#: created from here on start scoped.
PROJECT_VISIBILITY_WORKSPACE = "workspace"
PROJECT_VISIBILITY_MEMBERS = "members"
PROJECT_VISIBILITY_MODES = (PROJECT_VISIBILITY_WORKSPACE, PROJECT_VISIBILITY_MEMBERS)

#: "Not mentioned in this request", as distinct from "set this to nothing".
#: The other update fields use None for both, which is fine while none of
#: them are nullable — these two are, and clearing a board's department has
#: to be expressible.
_UNSET = object()


def generate_slug(name: str) -> str:
    """Generate a URL-safe slug from a name."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[-\s]+", "-", slug)
    return slug[:100]


async def can_see_project(
    db: AsyncSession, workspace_id: str, project_id: str, developer_id: str
) -> bool:
    """May this developer know that this project exists?

    True for a workspace still set to `project_visibility="workspace"`, for
    anyone holding `can_view_all_projects` (owners, admins and managers by
    default), and for anyone attached to the project itself.
    """
    # Imported here rather than at module scope: PermissionService imports the
    # project models, and a top-level import in both directions is a cycle.
    from aexy.services.permission_service import PermissionService

    service = ProjectService(db)
    if await service.get_visibility_mode(workspace_id) == PROJECT_VISIBILITY_WORKSPACE:
        return True
    if await PermissionService(db).check_permission(
        workspace_id, developer_id, "can_view_all_projects"
    ):
        return True
    return await service.is_member_of(project_id, developer_id)


async def assert_project_visible(
    db: AsyncSession, workspace_id: str, project_id: str, developer_id: str
) -> None:
    """Raise 404 if `project_id` names a project this developer may not see.

    Silent when the id names no project at all, so callers holding a team id
    that merely *might* be a board can use it unconditionally.

    404 rather than 403: a 403 confirms that a project with that id exists,
    which is the one thing scoped visibility is meant to withhold.
    """
    service = ProjectService(db)
    # Cheapest question first: this runs on every board read, and a workspace
    # that has not switched over needs neither of the queries below.
    if await service.get_visibility_mode(workspace_id) == PROJECT_VISIBILITY_WORKSPACE:
        return

    project = await service.get_project(project_id)
    if project is None or project.workspace_id != workspace_id:
        return
    if not await can_see_project(db, workspace_id, project_id, developer_id):
        raise HTTPException(status_code=404, detail="Project not found")


class ProjectService:
    """Service for managing projects."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_project(
        self,
        workspace_id: str,
        name: str,
        description: str | None = None,
        color: str = "#3b82f6",
        icon: str = "FolderGit2",
        settings: dict | None = None,
        created_by_id: str | None = None,
        department_id: str | None = None,
    ) -> Project:
        """Create a new project with an associated team for sprint planning."""
        # Generate slug
        slug = generate_slug(name)

        # Check for duplicate slug
        existing = await self.get_project_by_slug(workspace_id, slug)
        if existing:
            counter = 1
            while await self.get_project_by_slug(workspace_id, f"{slug}-{counter}"):
                counter += 1
            slug = f"{slug}-{counter}"

        project_id = str(uuid4())

        project = Project(
            id=project_id,
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            description=description,
            color=color,
            icon=icon,
            settings=settings or {},
        )

        self.db.add(project)

        # Create a corresponding team for sprint planning (using same ID for easy correlation)
        # Asked for at creation, because a board created without a department is
        # a board the Service Desk cannot hand anything to — and nobody comes
        # back to settings to fix a field they never saw.
        if department_id:
            owner = (
                await self.db.execute(
                    select(Department.id).where(
                        Department.id == department_id,
                        Department.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
            if owner is None:
                raise HTTPException(
                    status_code=404, detail="Department not found in this workspace"
                )

        team = Team(
            id=project_id,  # Use same ID as project for easy correlation
            workspace_id=workspace_id,
            name=name,
            slug=slug,
            type="internal",
            auto_sync_enabled=False,
            department_id=department_id or None,
            settings={},
            is_active=True,
        )
        self.db.add(team)

        # Link project and team
        project_team = ProjectTeam(
            id=str(uuid4()),
            project_id=project_id,
            team_id=project_id,
        )
        self.db.add(project_team)

        # Automatically add creator as a member if provided
        if created_by_id:
            await self.db.flush()  # Get IDs

            # Add as project member
            await self.add_member(
                project_id=project.id,
                developer_id=created_by_id,
                invited_by_id=created_by_id,
            )

            # Add as team member for sprint access, as the team's *lead*.
            #
            # This wrote "admin" — a value the vocabulary never declared (see
            # TeamMemberRole) and that only half the code understands.
            # `tracking_tasks` escalates blockers to lead/manager/admin alike, so
            # that part worked; but `review_service` and `leave_request_service`
            # both look for exactly `role == "lead"`, so the person who created
            # the project was skipped when either needed someone accountable and
            # they fell through to "any workspace manager". The creator of a
            # project's team is its lead, and saying so makes them findable.
            team_member = TeamMember(
                id=str(uuid4()),
                team_id=project_id,
                developer_id=created_by_id,
                role=TeamMemberRole.LEAD.value,
                source="manual",
            )
            self.db.add(team_member)

        return project

    async def get_project(self, project_id: str) -> Project | None:
        """Get a project by ID."""
        stmt = select(Project).where(Project.id == project_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_project_by_slug(
        self, workspace_id: str, slug: str
    ) -> Project | None:
        """Get a project by workspace and slug."""
        stmt = select(Project).where(
            and_(
                Project.workspace_id == workspace_id,
                Project.slug == slug,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _membership_clause(developer_id: str):
        """Is this developer attached to the project, by either route?

        Two routes, and both are needed. `project_members` is the explicit one,
        but projects only auto-enrol their *creator* there — in practice people
        are added to the project's board, which is a `Team` linked through
        `project_teams`. Checking only the first would hide projects from the
        very people doing the work in them.
        """
        return or_(
            select(ProjectMember.id)
            .where(
                ProjectMember.project_id == Project.id,
                ProjectMember.developer_id == developer_id,
                ProjectMember.status == "active",
            )
            .exists(),
            select(TeamMember.id)
            .join(ProjectTeam, ProjectTeam.team_id == TeamMember.team_id)
            .where(
                ProjectTeam.project_id == Project.id,
                TeamMember.developer_id == developer_id,
            )
            .exists(),
        )

    async def list_projects(
        self,
        workspace_id: str,
        include_archived: bool = False,
        visible_to_developer_id: str | None = None,
    ) -> list[Project]:
        """List projects in a workspace.

        `visible_to_developer_id` narrows the list to the projects that
        developer belongs to. Callers who may see everything — the workspace
        owner, anyone holding `can_view_all_projects`, and every caller in a
        workspace still set to `project_visibility="workspace"` — pass None.
        """
        conditions = [
            Project.workspace_id == workspace_id,
            Project.is_active == True,
        ]

        if not include_archived:
            conditions.append(Project.status != "archived")

        if visible_to_developer_id is not None:
            conditions.append(self._membership_clause(visible_to_developer_id))

        stmt = (
            select(Project)
            .where(and_(*conditions))
            .order_by(Project.name)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def is_member_of(self, project_id: str, developer_id: str) -> bool:
        """Whether this developer is attached to this project.

        Same two routes as the listing clause, asked of one project — so a
        listing and a direct fetch can never disagree about who belongs.
        """
        stmt = select(Project.id).where(
            Project.id == project_id,
            self._membership_clause(developer_id),
        )
        return (await self.db.execute(stmt)).scalar_one_or_none() is not None

    async def get_visibility_mode(self, workspace_id: str) -> str:
        """Whether this workspace scopes its project list to membership."""
        settings = (
            await self.db.execute(
                select(Workspace.settings).where(Workspace.id == workspace_id)
            )
        ).scalar_one_or_none()
        mode = (settings or {}).get("project_visibility")
        return mode if mode in PROJECT_VISIBILITY_MODES else PROJECT_VISIBILITY_MEMBERS

    async def set_visibility_mode(self, workspace_id: str, mode: str) -> str:
        """Set the workspace's project visibility mode."""
        if mode not in PROJECT_VISIBILITY_MODES:
            raise HTTPException(
                status_code=422,
                detail=f"project_visibility must be one of {list(PROJECT_VISIBILITY_MODES)}",
            )

        workspace = (
            await self.db.execute(select(Workspace).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()
        if workspace is None:
            raise HTTPException(status_code=404, detail="Workspace not found")

        # JSONB columns are replaced, not mutated in place — assigning a new dict
        # is what makes SQLAlchemy notice the change.
        workspace.settings = {**(workspace.settings or {}), "project_visibility": mode}
        return mode

    async def update_project(
        self,
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
        icon: str | None = None,
        settings: dict | None = None,
        status: str | None = None,
        department_id: str | None | object = _UNSET,
        desk_stakeholder_slug: str | None | object = _UNSET,
    ) -> Project | None:
        """Update a project."""
        project = await self.get_project(project_id)
        if not project:
            return None

        # Both routing fields live on the board (`Team`), not the project. The
        # two rows deliberately share an id (see `create_project`), and the
        # board is what a task's `team_id` points at — so putting a second
        # department field on `Project` would give the same board two answers.
        if department_id is not _UNSET or desk_stakeholder_slug is not _UNSET:
            await self._update_board_routing(
                project, department_id=department_id, desk_stakeholder_slug=desk_stakeholder_slug
            )

        if name is not None:
            project.name = name
            # Regenerate slug if name changed
            new_slug = generate_slug(name)
            if new_slug != project.slug:
                existing = await self.get_project_by_slug(
                    project.workspace_id, new_slug
                )
                if existing and existing.id != project_id:
                    counter = 1
                    while await self.get_project_by_slug(
                        project.workspace_id, f"{new_slug}-{counter}"
                    ):
                        counter += 1
                    new_slug = f"{new_slug}-{counter}"
                project.slug = new_slug

        if description is not None:
            project.description = description

        if color is not None:
            project.color = color

        if icon is not None:
            project.icon = icon

        if settings is not None:
            project.settings = settings

        if status is not None:
            project.status = status

        return project

    async def _update_board_routing(
        self,
        project: Project,
        *,
        department_id: str | None | object = _UNSET,
        desk_stakeholder_slug: str | None | object = _UNSET,
    ) -> None:
        """Set which department owns this board, and any Service Desk override.

        Validated against the project's own workspace: both values arrive from a
        request body, and an unchecked id here would let a caller roll a board up
        to another workspace's department — which then decides who can see the
        tickets that board handles.
        """
        team = (
            await self.db.execute(select(Team).where(Team.id == project.id))
        ).scalar_one_or_none()
        if team is None:
            # A project whose board was never created (or was hard-deleted) has
            # nothing to route. Silence here would look like the save worked.
            raise HTTPException(
                status_code=409,
                detail="This project has no board, so it cannot be routed to a department",
            )

        if department_id is not _UNSET:
            if department_id:
                exists = (
                    await self.db.execute(
                        select(Department.id).where(
                            Department.id == department_id,
                            Department.workspace_id == project.workspace_id,
                        )
                    )
                ).scalar_one_or_none()
                if exists is None:
                    raise HTTPException(
                        status_code=404, detail="Department not found in this workspace"
                    )
            team.department_id = department_id or None

        if desk_stakeholder_slug is not _UNSET:
            if desk_stakeholder_slug:
                bucket = (
                    await self.db.execute(
                        select(ServiceDeskStakeholder.semantics).where(
                            ServiceDeskStakeholder.workspace_id == project.workspace_id,
                            ServiceDeskStakeholder.slug == desk_stakeholder_slug,
                            ServiceDeskStakeholder.is_active.is_(True),
                        )
                    )
                ).scalar_one_or_none()
                if bucket is None:
                    raise HTTPException(
                        status_code=404,
                        detail="No active pending-with bucket with that slug in this workspace",
                    )
                # A board is somewhere work is *done*, so it can only ever be an
                # internal party. Pointing one at "Partner" would move tickets
                # out of the desk's own queue the moment work started on them.
                if bucket != "internal":
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            "A board can only route to an internal bucket — an "
                            "external one means a counterparty owes the action."
                        ),
                    )
            team.desk_stakeholder_slug = desk_stakeholder_slug or None

    async def _set_board_active(self, project_id: str, is_active: bool) -> None:
        """Mirror a project's availability onto the board that shares its id.

        A project whose board stays active is still offered by every team
        picker, sprint board and assignment dropdown in the product, which is
        the opposite of what archiving it is for.
        """
        team = (
            await self.db.execute(select(Team).where(Team.id == project_id))
        ).scalar_one_or_none()
        if team:
            team.is_active = is_active

    async def archive_project(self, project_id: str) -> Project | None:
        """Archive a project: hidden by default, and reversible.

        Distinct from ``delete_project`` on purpose. Deleting used to write
        ``status = "archived"`` as well as ``is_active = False``, while
        ``list_projects`` filters on ``is_active`` unconditionally — so
        ``include_archived=True`` could never return anything, and the one
        parameter offered for seeing archived projects had no effect for the
        whole life of the endpoint. Archiving now owns ``status`` and deleting
        owns ``is_active``, so each is legible on its own.
        """
        project = await self.get_project(project_id)
        if not project:
            return None

        project.status = "archived"
        await self._set_board_active(project_id, False)
        return project

    async def unarchive_project(self, project_id: str) -> Project | None:
        """Bring an archived project back as active."""
        project = await self.get_project(project_id)
        if not project:
            return None

        project.status = "active"
        await self._set_board_active(project_id, True)
        return project

    async def delete_project(self, project_id: str) -> bool:
        """Soft delete a project and its associated team.

        Leaves ``status`` alone: a deleted project is gone from every listing
        regardless of it, and overwriting it would lose what the project was
        when it was deleted.
        """
        project = await self.get_project(project_id)
        if not project:
            return False

        project.is_active = False
        await self._set_board_active(project_id, False)

        return True

    async def hard_delete_project(self, project_id: str) -> bool:
        """Permanently delete a project, its associated team, and all data."""
        project = await self.get_project(project_id)
        if not project:
            return False

        # Delete the associated team first (if using same ID)
        # Note: Team deletion will cascade to sprints, tasks, etc.
        stmt = select(Team).where(Team.id == project_id)
        result = await self.db.execute(stmt)
        team = result.scalar_one_or_none()
        if team:
            await self.db.delete(team)

        await self.db.delete(project)
        return True

    # Member management
    async def add_member(
        self,
        project_id: str,
        developer_id: str,
        role_id: str | None = None,
        permission_overrides: dict | None = None,
        invited_by_id: str | None = None,
    ) -> ProjectMember:
        """Add a member to a project."""
        # Check if already a member
        existing = await self.get_member(project_id, developer_id)
        if existing:
            # Reactivate if removed
            if existing.status == "removed":
                existing.status = "active"
                existing.role_id = role_id
                existing.permission_overrides = permission_overrides
                existing.joined_at = datetime.now(timezone.utc)
                return existing
            return existing

        member = ProjectMember(
            id=str(uuid4()),
            project_id=project_id,
            developer_id=developer_id,
            role_id=role_id,
            permission_overrides=permission_overrides,
            status="active",
            invited_by_id=invited_by_id,
            invited_at=datetime.now(timezone.utc),
            joined_at=datetime.now(timezone.utc),
        )

        self.db.add(member)
        return member

    async def get_member(
        self, project_id: str, developer_id: str
    ) -> ProjectMember | None:
        """Get a project member."""
        stmt = select(ProjectMember).where(
            and_(
                ProjectMember.project_id == project_id,
                ProjectMember.developer_id == developer_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_members(
        self,
        project_id: str,
        include_removed: bool = False,
    ) -> list[ProjectMember]:
        """List all members of a project."""
        conditions = [ProjectMember.project_id == project_id]

        if not include_removed:
            conditions.append(ProjectMember.status != "removed")

        stmt = select(ProjectMember).where(and_(*conditions))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_member(
        self,
        project_id: str,
        developer_id: str,
        role_id: str | None = None,
        permission_overrides: dict | None = None,
        status: str | None = None,
    ) -> ProjectMember | None:
        """Update a project member."""
        member = await self.get_member(project_id, developer_id)
        if not member:
            return None

        if role_id is not None:
            member.role_id = role_id

        if permission_overrides is not None:
            member.permission_overrides = permission_overrides

        if status is not None:
            member.status = status
            if status == "active" and not member.joined_at:
                member.joined_at = datetime.now(timezone.utc)

        return member

    async def remove_member(
        self, project_id: str, developer_id: str
    ) -> bool:
        """Remove a member from a project (soft delete)."""
        member = await self.get_member(project_id, developer_id)
        if not member:
            return False

        member.status = "removed"
        return True

    # Team management
    async def add_team(
        self, project_id: str, team_id: str
    ) -> ProjectTeam:
        """Add a team to a project."""
        # Check if already added
        existing = await self.get_project_team(project_id, team_id)
        if existing:
            return existing

        project_team = ProjectTeam(
            id=str(uuid4()),
            project_id=project_id,
            team_id=team_id,
        )

        self.db.add(project_team)
        return project_team

    async def get_project_team(
        self, project_id: str, team_id: str
    ) -> ProjectTeam | None:
        """Get a project-team association."""
        stmt = select(ProjectTeam).where(
            and_(
                ProjectTeam.project_id == project_id,
                ProjectTeam.team_id == team_id,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_project_teams(self, project_id: str) -> list[ProjectTeam]:
        """List all teams in a project."""
        stmt = select(ProjectTeam).where(ProjectTeam.project_id == project_id)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def remove_team(self, project_id: str, team_id: str) -> bool:
        """Remove a team from a project."""
        project_team = await self.get_project_team(project_id, team_id)
        if not project_team:
            return False

        await self.db.delete(project_team)
        return True

    # Email invite
    async def invite_by_email(
        self,
        project_id: str,
        workspace_id: str,
        email: str,
        role_id: str | None = None,
        invited_by_id: str | None = None,
    ) -> tuple[ProjectMember | None, str]:
        """
        Invite a user to a project by email.

        Returns:
            Tuple of (ProjectMember or None, status_string)
            status can be: 'added', 'already_member', 'pending', 'user_not_found'
        """
        # Look up developer by email
        stmt = select(Developer).where(Developer.email == email.lower().strip())
        result = await self.db.execute(stmt)
        developer = result.scalar_one_or_none()

        if not developer:
            # User doesn't exist in our system yet - they need to sign up first
            # TODO: Could create a pending invite table for email invites
            return None, "user_not_found"

        # Check if already a project member
        existing_member = await self.get_member(project_id, str(developer.id))
        if existing_member and existing_member.status != "removed":
            return existing_member, "already_member"

        # Check if they're a workspace member
        ws_stmt = select(WorkspaceMember).where(
            and_(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.developer_id == str(developer.id),
            )
        )
        ws_result = await self.db.execute(ws_stmt)
        workspace_member = ws_result.scalar_one_or_none()

        # If not a workspace member, add them as a guest
        if not workspace_member:
            workspace_member = WorkspaceMember(
                id=str(uuid4()),
                workspace_id=workspace_id,
                developer_id=str(developer.id),
                role="member",  # Guest/member role
                status="active",
                is_billable=False,  # Guests might not be billable
                joined_at=datetime.now(timezone.utc),
            )
            self.db.add(workspace_member)
        elif workspace_member.status != "active":
            workspace_member.status = "active"

        # Add to project
        member = await self.add_member(
            project_id=project_id,
            developer_id=str(developer.id),
            role_id=role_id,
            invited_by_id=invited_by_id,
        )

        return member, "added"

    # Bulk operations
    async def add_workspace_members_to_project(
        self,
        project_id: str,
        workspace_id: str,
        invited_by_id: str | None = None,
    ) -> list[ProjectMember]:
        """Add all active workspace members to a project."""
        # Get all active workspace members
        stmt = select(WorkspaceMember).where(
            and_(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.status == "active",
            )
        )
        result = await self.db.execute(stmt)
        workspace_members = result.scalars().all()

        added = []
        for wm in workspace_members:
            member = await self.add_member(
                project_id=project_id,
                developer_id=wm.developer_id,
                invited_by_id=invited_by_id,
            )
            added.append(member)

        return added

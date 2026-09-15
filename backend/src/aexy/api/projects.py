"""Project management API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from aexy.core.database import get_db
from aexy.api.developers import get_current_developer
from aexy.models.developer import Developer
from aexy.models.roadmap_voting import RoadmapRequest
from aexy.models.project import Project
from aexy.services.desk_board_routing import (
    REASON_NO_BOARD,
    BoardRouting,
    resolve_board_routing,
    resolve_board_routings,
)
from aexy.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    ProjectsListWrapper,
    ProjectMemberAdd,
    ProjectMemberUpdate,
    ProjectMemberResponse,
    ProjectMemberListResponse,
    ProjectMembersListWrapper,
    ProjectTeamAdd,
    ProjectTeamResponse,
    ProjectTeamsListWrapper,
    ProjectInviteRequest,
    ProjectInviteResult,
    MyProjectPermissionsResponse,
    AccessibleWidgetsResponse,
    ProjectVisibilityConfig,
    PublicTabsConfig,
    PublicTabsUpdate,
    RoadmapRequestResponse,
    RoadmapRequestUpdate,
    RoadmapRequestAuthor,
)
from aexy.schemas.role import RoleSummary
from aexy.services.project_service import (
    PROJECT_VISIBILITY_WORKSPACE,
    ProjectService,
    can_see_project,
)
from aexy.services.permission_service import PermissionService
from aexy.services.role_service import RoleService
from aexy.services.activity_logger import log_activity

router = APIRouter(prefix="/workspaces/{workspace_id}/projects", tags=["Projects"])


async def _with_routing(
    db: AsyncSession, workspace_id: str, project: Project
) -> ProjectResponse:
    """A project plus the department and Service Desk bucket its board resolves to.

    Read here rather than joined into the query because the fields live on the
    board (`Team`) that shares this project's id, and the resolution itself is
    two more hops past that. Kept in one helper so create, read and update
    cannot drift into reporting different routing for the same board.
    """
    routing = await resolve_board_routing(db, workspace_id, str(project.id))
    return ProjectResponse.model_validate(project).model_copy(
        update=routing.as_response_fields()
    )


async def _assert_visible(
    db: AsyncSession, workspace_id: str, project_id: str, developer_id: str
) -> Project:
    """The project, if this developer is allowed to know it exists.

    404 rather than 403 on purpose: a 403 tells the caller that a project with
    that id is there, which is the thing scoped visibility is meant to withhold.
    Callers who may see everything — the workspace owner, anyone holding
    `can_view_all_projects`, and everyone in a workspace still set to
    `project_visibility="workspace"` — pass the membership check trivially.
    """
    project = await ProjectService(db).get_project(project_id)
    if not project or project.workspace_id != workspace_id or not project.is_active:
        raise HTTPException(status_code=404, detail="Project not found")

    if not await can_see_project(db, workspace_id, project_id, developer_id):
        raise HTTPException(status_code=404, detail="Project not found")

    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    workspace_id: str,
    data: ProjectCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_create_projects"
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    project = await project_service.create_project(
        workspace_id=workspace_id,
        name=data.name,
        description=data.description,
        color=data.color,
        icon=data.icon,
        settings=data.settings,
        created_by_id=str(current_user.id),
        department_id=data.department_id,
    )
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=str(project.id),
        activity_type="created",
        actor_id=str(current_user.id),
        title=f"Created project '{data.name}'",
    )
    await db.commit()
    await db.refresh(project)
    return await _with_routing(db, workspace_id, project)


@router.get("", response_model=ProjectsListWrapper)
async def list_projects(
    workspace_id: str,
    include_archived: bool = False,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List all projects in workspace."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_view_projects"
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    # Who sees everything: a workspace still on the pre-scoping setting, and
    # anyone holding `can_view_all_projects` (owners, admins and managers by
    # default). Everyone else sees the projects they are attached to.
    mode = await project_service.get_visibility_mode(workspace_id)
    sees_all = mode == PROJECT_VISIBILITY_WORKSPACE or await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_view_all_projects"
    )
    projects = await project_service.list_projects(
        workspace_id,
        include_archived=include_archived,
        visible_to_developer_id=None if sees_all else str(current_user.id),
    )

    # One batched resolution for the whole page rather than per row: the settings
    # list renders the resolved bucket on every board.
    routings = await resolve_board_routings(
        db, workspace_id, [str(p.id) for p in projects]
    )
    fallback = BoardRouting(board_id="", stakeholder_slug=None, reason=REASON_NO_BOARD)

    return ProjectsListWrapper(
        projects=[
            ProjectListResponse(
                **routings.get(str(p.id), fallback).as_response_fields(),
                id=p.id,
                workspace_id=p.workspace_id,
                name=p.name,
                slug=p.slug,
                description=p.description,
                color=p.color,
                icon=p.icon,
                status=p.status,
                is_active=p.is_active,
                member_count=p.member_count,
                team_count=p.team_count,
                is_public=p.is_public,
                public_slug=p.public_slug,
            )
            for p in projects
        ]
    )


# Declared before the `/{project_id}` routes below: a path parameter would
# otherwise swallow "visibility" and try to load a project by that id.
@router.get("/visibility", response_model=ProjectVisibilityConfig)
async def get_project_visibility(
    workspace_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Whether this workspace scopes its project list to membership."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_view_projects"
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    mode = await ProjectService(db).get_visibility_mode(workspace_id)
    return ProjectVisibilityConfig(mode=mode)


@router.put("/visibility", response_model=ProjectVisibilityConfig)
async def set_project_visibility(
    workspace_id: str,
    data: ProjectVisibilityConfig,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Switch the workspace between workspace-wide and member-scoped projects.

    This decides what everybody else can see, so it sits behind
    `can_manage_workspace_settings` rather than the project permissions.
    """
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_manage_workspace_settings"
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    mode = await ProjectService(db).set_visibility_mode(workspace_id, data.mode)
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="workspace",
        entity_id=workspace_id,
        activity_type="updated",
        actor_id=str(current_user.id),
        title=f"Set project visibility to '{mode}'",
    )
    await db.commit()
    return ProjectVisibilityConfig(mode=mode)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_view_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project = await _assert_visible(db, workspace_id, project_id, str(current_user.id))
    return await _with_routing(db, workspace_id, project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    workspace_id: str,
    project_id: str,
    data: ProjectUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update a project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    project = await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    project = await project_service.update_project(
        project_id, **data.model_dump(exclude_unset=True)
    )
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=str(project.id),
        activity_type="updated",
        actor_id=str(current_user.id),
        title=f"Updated project '{project.name}'",
    )
    await db.commit()
    await db.refresh(project)
    return await _with_routing(db, workspace_id, project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Soft delete a project.

    Distinct from archiving: this one is not offered back in any listing. Use
    ``POST /{project_id}/archive`` to merely hide a project that is finished or
    dormant.
    """
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_delete_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    project = await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    project_name = project.name
    await project_service.delete_project(project_id)
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=project_id,
        activity_type="deleted",
        actor_id=str(current_user.id),
        title=f"Deleted project '{project_name}'",
    )
    await db.commit()


@router.post("/{project_id}/archive", response_model=ProjectResponse)
async def archive_project(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Archive a project so it stops appearing in project lists and pickers.

    Gated on ``can_edit_projects`` rather than ``can_delete_projects``: this is
    reversible and loses nothing, so it should not need the owner-only
    permission that deleting does.
    """
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    project = await project_service.archive_project(project_id)
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=project_id,
        activity_type="archived",
        actor_id=str(current_user.id),
        title=f"Archived project '{project.name}'",
    )
    await db.commit()
    await db.refresh(project)
    return await _with_routing(db, workspace_id, project)


@router.post("/{project_id}/unarchive", response_model=ProjectResponse)
async def unarchive_project(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Bring an archived project back."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    project = await project_service.unarchive_project(project_id)
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=project_id,
        activity_type="unarchived",
        actor_id=str(current_user.id),
        title=f"Unarchived project '{project.name}'",
    )
    await db.commit()
    await db.refresh(project)
    return await _with_routing(db, workspace_id, project)


@router.post("/{project_id}/toggle-visibility", response_model=ProjectResponse)
async def toggle_project_visibility(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Toggle project visibility between public and private."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project = await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    # Toggle visibility using model methods
    if project.is_public:
        project.make_private()
    else:
        project.make_public()

    await db.commit()
    await db.refresh(project)
    return project


# Valid public tabs
VALID_PUBLIC_TABS = ["overview", "backlog", "board", "bugs", "goals", "releases", "roadmap", "stories", "sprints", "timeline"]


@router.get("/{project_id}/public-tabs", response_model=PublicTabsConfig)
async def get_public_tabs_config(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get public tabs configuration for a project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_view_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project = await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    settings = project.settings or {}
    public_tabs = settings.get("public_tabs", {})
    enabled_tabs = public_tabs.get("enabled_tabs", ["overview"])

    return PublicTabsConfig(enabled_tabs=enabled_tabs)


@router.put("/{project_id}/public-tabs", response_model=PublicTabsConfig)
async def update_public_tabs_config(
    workspace_id: str,
    project_id: str,
    data: PublicTabsUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update public tabs configuration for a project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project = await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    # Validate tabs - filter out invalid ones
    enabled_tabs = [tab for tab in data.enabled_tabs if tab in VALID_PUBLIC_TABS]

    # Ensure "overview" is always included
    if "overview" not in enabled_tabs:
        enabled_tabs.insert(0, "overview")

    # Update project settings
    settings = project.settings or {}
    settings["public_tabs"] = {"enabled_tabs": enabled_tabs}
    project.settings = settings

    # Flag the JSONB field as modified to ensure SQLAlchemy detects the change
    flag_modified(project, "settings")

    await db.commit()
    await db.refresh(project)

    return PublicTabsConfig(enabled_tabs=enabled_tabs)


# Member management endpoints
@router.get("/{project_id}/members", response_model=ProjectMembersListWrapper)
async def list_project_members(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List all members of a project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_view_members", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    members = await project_service.list_members(project_id)

    return ProjectMembersListWrapper(
        members=[
            ProjectMemberListResponse(
                id=m.id,
                project_id=m.project_id,
                developer_id=m.developer_id,
                developer_name=m.developer.name if m.developer else None,
                developer_email=m.developer.email if m.developer else None,
                developer_avatar_url=m.developer.avatar_url if m.developer else None,
                role_id=str(m.role.id) if m.role else None,
                role_name=m.role.name if m.role else None,
                status=m.status,
                joined_at=m.joined_at,
            )
            for m in members
        ]
    )


@router.post("/{project_id}/members", response_model=ProjectMemberResponse)
async def add_project_member(
    workspace_id: str,
    project_id: str,
    data: ProjectMemberAdd,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Add a member to a project with a specific role."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_invite_members", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    # Validate role if provided
    if data.role_id:
        role_service = RoleService(db)
        role = await role_service.get_role(data.role_id)
        if not role or role.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Invalid role")

    member = await project_service.add_member(
        project_id=project_id,
        developer_id=data.developer_id,
        role_id=data.role_id,
        permission_overrides=data.permission_overrides,
        invited_by_id=str(current_user.id),
    )
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=project_id,
        activity_type="linked",
        actor_id=str(current_user.id),
        title="Added member to project",
    )
    await db.commit()
    await db.refresh(member)

    return ProjectMemberResponse(
        id=member.id,
        project_id=member.project_id,
        developer_id=member.developer_id,
        developer_name=member.developer.name if member.developer else None,
        developer_email=member.developer.email if member.developer else None,
        developer_avatar_url=member.developer.avatar_url if member.developer else None,
        role_id=member.role_id,
        role=RoleSummary(
            id=member.role.id,
            name=member.role.name,
            slug=member.role.slug,
            color=member.role.color,
            icon=member.role.icon,
            is_system=member.role.is_system,
        ) if member.role else None,
        permission_overrides=member.permission_overrides,
        status=member.status,
        invited_by_id=member.invited_by_id,
        invited_by_name=member.invited_by.name if member.invited_by else None,
        invited_at=member.invited_at,
        joined_at=member.joined_at,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


@router.post("/{project_id}/invite", response_model=ProjectInviteResult)
async def invite_to_project(
    workspace_id: str,
    project_id: str,
    data: ProjectInviteRequest,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Invite users to a project by email. Users don't need to be workspace members."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_invite_members", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    # Validate role if provided
    if data.role_id:
        role_service = RoleService(db)
        role = await role_service.get_role(data.role_id)
        if not role or role.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Invalid role")

    invited = []
    already_members = []
    pending_invites = []
    failed = []

    for email in data.emails:
        member, status = await project_service.invite_by_email(
            project_id=project_id,
            workspace_id=workspace_id,
            email=email.strip(),
            role_id=data.role_id,
            invited_by_id=str(current_user.id),
        )

        if status == "added":
            invited.append(email)
        elif status == "already_member":
            already_members.append(email)
        elif status == "pending":
            pending_invites.append(email)
        elif status == "user_not_found":
            failed.append({"email": email, "reason": "User not found. They need to sign up first."})

    if invited:
        await log_activity(
            db,
            workspace_id=workspace_id,
            entity_type="project",
            entity_id=project_id,
            activity_type="linked",
            actor_id=str(current_user.id),
            title="Added member to project",
        )
    await db.commit()

    return ProjectInviteResult(
        invited=invited,
        already_members=already_members,
        pending_invites=pending_invites,
        failed=failed,
    )


@router.patch("/{project_id}/members/{developer_id}", response_model=ProjectMemberResponse)
async def update_project_member(
    workspace_id: str,
    project_id: str,
    developer_id: str,
    data: ProjectMemberUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update a project member's role or permissions."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_assign_roles", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    # Validate role if provided
    if data.role_id:
        role_service = RoleService(db)
        role = await role_service.get_role(data.role_id)
        if not role or role.workspace_id != workspace_id:
            raise HTTPException(status_code=400, detail="Invalid role")

    member = await project_service.update_member(
        project_id=project_id,
        developer_id=developer_id,
        role_id=data.role_id,
        permission_overrides=data.permission_overrides,
        status=data.status,
    )

    if not member:
        raise HTTPException(status_code=404, detail="Member not found")

    await db.commit()
    await db.refresh(member)

    return ProjectMemberResponse(
        id=member.id,
        project_id=member.project_id,
        developer_id=member.developer_id,
        developer_name=member.developer.name if member.developer else None,
        developer_email=member.developer.email if member.developer else None,
        developer_avatar_url=member.developer.avatar_url if member.developer else None,
        role_id=member.role_id,
        role=RoleSummary(
            id=member.role.id,
            name=member.role.name,
            slug=member.role.slug,
            color=member.role.color,
            icon=member.role.icon,
            is_system=member.role.is_system,
        ) if member.role else None,
        permission_overrides=member.permission_overrides,
        status=member.status,
        invited_by_id=member.invited_by_id,
        invited_by_name=member.invited_by.name if member.invited_by else None,
        invited_at=member.invited_at,
        joined_at=member.joined_at,
        created_at=member.created_at,
        updated_at=member.updated_at,
    )


@router.delete("/{project_id}/members/{developer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_project_member(
    workspace_id: str,
    project_id: str,
    developer_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Remove a member from a project."""
    permission_service = PermissionService(db)

    # Allow removing self or must have permission
    is_self = str(current_user.id) == developer_id
    if not is_self and not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_remove_members", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    success = await project_service.remove_member(project_id, developer_id)
    if not success:
        raise HTTPException(status_code=404, detail="Member not found")

    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=project_id,
        activity_type="unlinked",
        actor_id=str(current_user.id),
        title="Removed member from project",
    )
    await db.commit()


# Team management endpoints
@router.get("/{project_id}/teams", response_model=ProjectTeamsListWrapper)
async def list_project_teams(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List all teams in a project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_view_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    project_teams = await project_service.list_project_teams(project_id)

    return ProjectTeamsListWrapper(
        teams=[
            ProjectTeamResponse(
                id=pt.id,
                project_id=pt.project_id,
                team_id=pt.team_id,
                team_name=pt.team.name if pt.team else "Unknown",
                team_slug=pt.team.slug if pt.team else "unknown",
                created_at=pt.created_at,
            )
            for pt in project_teams
        ]
    )


@router.post("/{project_id}/teams", response_model=ProjectTeamResponse)
async def add_team_to_project(
    workspace_id: str,
    project_id: str,
    data: ProjectTeamAdd,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Add a team to a project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    project_team = await project_service.add_team(project_id, data.team_id)
    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=project_id,
        activity_type="linked",
        actor_id=str(current_user.id),
        title="Added team to project",
    )
    await db.commit()
    await db.refresh(project_team)

    return ProjectTeamResponse(
        id=project_team.id,
        project_id=project_team.project_id,
        team_id=project_team.team_id,
        team_name=project_team.team.name if project_team.team else "Unknown",
        team_slug=project_team.team.slug if project_team.team else "unknown",
        created_at=project_team.created_at,
    )


@router.delete("/{project_id}/teams/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_team_from_project(
    workspace_id: str,
    project_id: str,
    team_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Remove a team from a project."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    project_service = ProjectService(db)
    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    success = await project_service.remove_team(project_id, team_id)
    if not success:
        raise HTTPException(status_code=404, detail="Team not found in project")

    await log_activity(
        db,
        workspace_id=workspace_id,
        entity_type="project",
        entity_id=project_id,
        activity_type="unlinked",
        actor_id=str(current_user.id),
        title="Removed team from project",
    )
    await db.commit()


# Permission and widget access endpoints
@router.get("/{project_id}/my-permissions", response_model=MyProjectPermissionsResponse)
async def get_my_permissions(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get current user's effective permissions for this project."""
    permission_service = PermissionService(db)
    permissions = await permission_service.get_effective_permissions(
        workspace_id, str(current_user.id), project_id
    )
    role_info = await permission_service.get_user_role_info(
        workspace_id, str(current_user.id), project_id
    )

    return MyProjectPermissionsResponse(
        permissions=list(permissions),
        workspace_id=workspace_id,
        project_id=project_id,
        role_id=role_info.get("role_id"),
        role_name=role_info.get("role_name"),
        has_project_override=role_info.get("has_project_override", False),
    )


@router.get("/{project_id}/accessible-widgets", response_model=AccessibleWidgetsResponse)
async def get_accessible_widgets(
    workspace_id: str,
    project_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Get widgets the user can access based on permissions."""
    permission_service = PermissionService(db)
    widgets = await permission_service.get_accessible_widgets(
        workspace_id, str(current_user.id), project_id
    )
    return AccessibleWidgetsResponse(
        widgets=widgets,
        workspace_id=workspace_id,
        project_id=project_id,
    )


# Roadmap Request Admin Endpoints
@router.patch("/{project_id}/roadmap-requests/{request_id}", response_model=RoadmapRequestResponse)
async def update_roadmap_request(
    workspace_id: str,
    project_id: str,
    request_id: str,
    data: RoadmapRequestUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update a roadmap request (admin only - status, admin response)."""
    permission_service = PermissionService(db)
    if not await permission_service.check_permission(
        workspace_id, str(current_user.id), "can_edit_projects", project_id
    ):
        raise HTTPException(status_code=403, detail="Permission denied")

    await _assert_visible(db, workspace_id, project_id, str(current_user.id))

    # Get the roadmap request
    result = await db.execute(
        select(RoadmapRequest).where(
            RoadmapRequest.id == request_id,
            RoadmapRequest.project_id == project_id,
        )
    )
    request_obj = result.scalar_one_or_none()
    if not request_obj:
        raise HTTPException(status_code=404, detail="Roadmap request not found")

    # Update fields
    if data.status is not None:
        request_obj.status = data.status
    if data.admin_response is not None:
        request_obj.admin_response = data.admin_response
        request_obj.responded_by_id = str(current_user.id)
        from datetime import datetime, timezone
        request_obj.responded_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(request_obj)

    return RoadmapRequestResponse(
        id=request_obj.id,
        title=request_obj.title,
        description=request_obj.description,
        category=request_obj.category,
        status=request_obj.status,
        vote_count=request_obj.vote_count,
        comment_count=request_obj.comment_count,
        submitted_by=RoadmapRequestAuthor(
            id=request_obj.submitted_by.id,
            name=request_obj.submitted_by.name or "Anonymous",
            avatar_url=request_obj.submitted_by.avatar_url,
        ),
        admin_response=request_obj.admin_response,
        responded_at=request_obj.responded_at,
        created_at=request_obj.created_at,
        updated_at=request_obj.updated_at,
        has_voted=False,
    )

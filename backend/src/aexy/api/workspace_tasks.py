"""Workspace-level Tasks API — aggregates tasks across every team/sprint in a workspace."""

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.api.developers import get_current_developer
from aexy.api.sprint_tasks import task_to_response
from aexy.models.developer import Developer
from aexy.schemas.sprint import (
    SprintTaskResponse,
    SprintTaskStatusUpdate,
    WorkspaceTaskCreate,
)
from aexy.services.project_service import (
    assert_team_filter_visible,
    hidden_project_ids,
)
from aexy.services.sprint_task_service import SprintTaskService, TaskValidationError
from aexy.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/workspaces/{workspace_id}/tasks", tags=["Workspace Tasks"])


@router.get("", response_model=list[SprintTaskResponse])
async def list_workspace_tasks(
    workspace_id: str,
    status: list[str] | None = Query(None, description="Filter by status slug(s)"),
    status_id: list[str] | None = Query(None, description="Filter by custom status id(s)"),
    assignee_id: list[str] | None = Query(None, description="Filter by assignee developer id(s)"),
    priority: list[str] | None = Query(None, description="Filter by priority"),
    team_id: list[str] | None = Query(None, description="Filter by team/project id(s)"),
    sprint_id: list[str] | None = Query(None, description="Filter by sprint id(s)"),
    epic_id: list[str] | None = Query(None, description="Filter by epic id(s)"),
    labels: list[str] | None = Query(None, description="Filter by label(s) — match if task has any"),
    search: str | None = Query(None, description="Case-insensitive substring match on title/description"),
    include_archived: bool = Query(False),
    archived_only: bool = Query(False),
    limit: int = Query(500, le=1000, ge=1),
    offset: int = Query(0, ge=0),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """List every task in a workspace (across all teams, sprints, and backlogs)."""
    ws_service = WorkspaceService(db)
    if not await ws_service.check_permission(workspace_id, str(current_user.id), "viewer"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Not a member of this workspace",
        )

    # Two halves of the same rule. A board named in the filter has to be one
    # this caller may see, and — filter or no filter — a listing across every
    # team must not hand over the tasks of a project they were never shown.
    # Same shape as the cross-team sprint list.
    for one in team_id or []:
        await assert_team_filter_visible(db, one, str(current_user.id), workspace_id)

    hidden = await hidden_project_ids(db, workspace_id, str(current_user.id))

    task_service = SprintTaskService(db)
    tasks = await task_service.get_workspace_tasks(
        workspace_id,
        status=status,
        status_id=status_id,
        assignee_ids=assignee_id,
        priorities=priority,
        team_ids=team_id,
        sprint_ids=sprint_id,
        epic_ids=epic_id,
        labels=labels,
        search=search,
        include_archived=include_archived,
        archived_only=archived_only,
        limit=limit,
        offset=offset,
    )
    if hidden:
        tasks = [t for t in tasks if str(t.team_id) not in hidden]
    return [task_to_response(t) for t in tasks]


@router.post("", response_model=SprintTaskResponse, status_code=http_status.HTTP_201_CREATED)
async def create_workspace_task(
    workspace_id: str,
    data: WorkspaceTaskCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Create a task from the workspace All-Tasks view.

    The caller supplies `project_id` directly (and optionally a `sprint_id`)
    so the modal/inline quick-add on `/sprints?tab=tasks` can create work
    without first navigating into a project. Returns the same SprintTaskResponse
    shape the project board uses so the cache can be patched optimistically.
    """
    ws_service = WorkspaceService(db)
    if not await ws_service.check_permission(workspace_id, str(current_user.id), "member"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Not a member of this workspace",
        )

    task_service = SprintTaskService(db)
    try:
        created = await task_service.add_workspace_task(
            workspace_id=workspace_id,
            project_id=data.project_id,
            title=data.title,
            sprint_id=data.sprint_id,
            description=data.description,
            description_json=data.description_json,
            story_points=data.story_points,
            priority=data.priority,
            labels=data.labels,
            assignee_id=data.assignee_id,
            status=data.status,
            status_id=data.status_id,
            epic_id=data.epic_id,
            parent_task_id=data.parent_task_id,
            mentioned_user_ids=data.mentioned_user_ids,
            mentioned_file_paths=data.mentioned_file_paths,
            start_date=data.start_date,
            end_date=data.end_date,
            estimated_hours=data.estimated_hours,
            actor_id=str(current_user.id),
        )
    except TaskValidationError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail=exc.code,
        )

    await db.commit()
    return task_to_response(created)


@router.patch("/{task_id}/status", response_model=SprintTaskResponse)
async def update_workspace_task_status(
    workspace_id: str,
    task_id: str,
    data: SprintTaskStatusUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
):
    """Update a task's status from the workspace-level Kanban (drag-drop).

    Verifies the task belongs to the given workspace so that a user can't
    mutate a task outside their workspace scope.
    """
    ws_service = WorkspaceService(db)
    if not await ws_service.check_permission(workspace_id, str(current_user.id), "member"):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="Not a member of this workspace",
        )

    task_service = SprintTaskService(db)
    existing = await task_service.get_task(task_id)
    if not existing or str(existing.workspace_id) != workspace_id:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    # Use update_task_status (not update_task) so the unified activity log
    # gets a `status_changed`/`resolved` entry — matches the sprint-scoped
    # PATCH endpoint's behavior.
    updated = await task_service.update_task_status(task_id, data.status)
    if not updated:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Task not found",
        )

    await db.commit()
    return task_to_response(updated)

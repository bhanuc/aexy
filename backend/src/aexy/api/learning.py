"""Learning path API endpoints."""

import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession


def is_valid_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    uuid_pattern = re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        re.IGNORECASE
    )
    return bool(uuid_pattern.match(value))

from sqlalchemy import select

from aexy.api.developers import get_current_developer
from aexy.core.database import get_db
from aexy.llm.gateway import get_llm_gateway
from aexy.models.developer import Developer
from aexy.models.workspace import WorkspaceMember
from aexy.schemas.career import (
    LearningActivity,
    LearningMilestoneResponse,
    LearningPathGenerate,
    LearningPathResponse,
    MilestoneStatus,
    PathProgressUpdate,
    StretchAssignment,
    TrajectoryStatus,
)
from aexy.services.developer_service import DeveloperService
from aexy.services.learning_path import LearningPathService
from aexy.services.project_service import assert_project_visible
from aexy.services.workspace_service import WorkspaceService

router = APIRouter(prefix="/learning")


async def _require_developer_visibility(
    db: AsyncSession,
    caller_id: str,
    target_developer_id: str,
    required_role: str = "admin",
) -> None:
    """Self always allowed; otherwise caller must hold `required_role` in a
    workspace the target is an active member of."""
    if str(caller_id) == str(target_developer_id):
        return
    target_workspaces = (
        await db.execute(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.developer_id == target_developer_id,
                WorkspaceMember.status == "active",
            )
        )
    ).scalars().all()
    if not target_workspaces:
        raise HTTPException(status_code=404, detail="Developer not found")
    service = WorkspaceService(db)
    for ws_id in target_workspaces:
        if await service.check_permission(str(ws_id), str(caller_id), required_role):
            return
    raise HTTPException(status_code=403, detail="Insufficient permissions")


async def _require_path_access(
    db: AsyncSession,
    path_id: str,
    caller_id: str,
    owner_only: bool = False,
):
    """Load path, return it, and require the caller to be the path's developer
    (or, when `owner_only` is False, an admin in a workspace the developer is
    in). 404 on miss to avoid id-existence oracle."""
    from aexy.models.career import LearningPath
    path = (
        await db.execute(select(LearningPath).where(LearningPath.id == path_id))
    ).scalar_one_or_none()
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )
    if str(path.developer_id) == str(caller_id):
        return path
    if owner_only:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )
    try:
        await _require_developer_visibility(
            db, caller_id, str(path.developer_id), "admin"
        )
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )
    return path


async def _require_team_workspace_member(
    db: AsyncSession, team_id: str, caller_id: str, role: str = "viewer"
):
    """Load Team and require active membership in its workspace.

    A project's board is a Team carrying the project's own id, so this can be
    handed a project id — and a team learning overview names the team's people
    and what they are weak at. In a workspace that scopes its projects to
    membership, that is not a project the caller may ask about.
    """
    from aexy.models.team import Team
    team = (
        await db.execute(select(Team).where(Team.id == team_id))
    ).scalar_one_or_none()
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    if not await WorkspaceService(db).check_permission(
        str(team.workspace_id), caller_id, role
    ):
        raise HTTPException(status_code=403, detail="Not a member of team's workspace")
    await assert_project_visible(db, str(team.workspace_id), team_id, caller_id)
    return team


@router.get("/paths", response_model=list[LearningPathResponse])
async def list_learning_paths(
    developer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """List all learning paths for a developer. Self or admin-in-shared-workspace."""
    await _require_developer_visibility(db, str(current_user.id), developer_id)
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)
    paths = await service.get_developer_paths(developer_id)

    return [
        LearningPathResponse(
            id=str(p.id),
            developer_id=str(p.developer_id),
            target_role_id=str(p.target_role_id) if p.target_role_id else None,
            target_role_name=p.target_role.name if p.target_role else None,
            skill_gaps=p.skill_gaps or {},
            phases=p.phases or [],
            milestones=[],  # Loaded separately
            status=p.status,
            progress_percentage=p.progress_percentage,
            trajectory_status=p.trajectory_status,
            estimated_success_probability=p.estimated_success_probability,
            risk_factors=p.risk_factors or [],
            recommendations=p.recommendations or [],
            started_at=p.started_at,
            target_completion=p.target_completion,
            actual_completion=p.actual_completion,
            generated_by_model=p.generated_by_model,
            last_regenerated_at=p.last_regenerated_at,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in paths
    ]


@router.post("/paths", response_model=LearningPathResponse, status_code=status.HTTP_201_CREATED)
async def generate_learning_path(
    data: LearningPathGenerate,
    developer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Generate a new learning path for a developer. Self or admin-in-shared-workspace."""
    await _require_developer_visibility(db, str(current_user.id), developer_id)
    dev_service = DeveloperService(db)
    developer = await dev_service.get_by_id(developer_id)

    if not developer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Developer not found",
        )

    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)

    # Determine if target_role_id is a UUID or a role name
    if is_valid_uuid(data.target_role_id):
        target_role_id = data.target_role_id
        target_role_name = None
    else:
        target_role_id = None
        target_role_name = data.target_role_id

    try:
        path = await service.generate_learning_path(
            developer=developer,
            target_role_id=target_role_id,
            target_role_name=target_role_name,
            timeline_months=data.timeline_months,
            include_external_resources=data.include_external_resources,
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return LearningPathResponse(
        id=str(path.id),
        developer_id=str(path.developer_id),
        target_role_id=str(path.target_role_id) if path.target_role_id else None,
        target_role_name=target_role_name,
        skill_gaps=path.skill_gaps or {},
        phases=path.phases or [],
        milestones=[],
        status=path.status,
        progress_percentage=path.progress_percentage,
        trajectory_status=path.trajectory_status,
        estimated_success_probability=path.estimated_success_probability,
        risk_factors=path.risk_factors or [],
        recommendations=path.recommendations or [],
        started_at=path.started_at,
        target_completion=path.target_completion,
        actual_completion=path.actual_completion,
        generated_by_model=path.generated_by_model,
        last_regenerated_at=path.last_regenerated_at,
        created_at=path.created_at,
        updated_at=path.updated_at,
    )


@router.get("/paths/{path_id}", response_model=LearningPathResponse)
async def get_learning_path(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get a learning path by ID. Owner or admin-in-shared-workspace."""
    await _require_path_access(db, path_id, str(current_user.id))
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)
    path = await service.get_learning_path(path_id)

    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    # Get milestones
    milestones = await service.get_milestones(path_id)
    milestone_responses = [
        LearningMilestoneResponse(
            id=str(m.id),
            learning_path_id=str(m.learning_path_id),
            skill_name=m.skill_name,
            target_score=m.target_score,
            current_score=m.current_score,
            status=MilestoneStatus(m.status),
            target_date=m.target_date,
            completed_date=m.completed_date,
            recommended_activities=m.recommended_activities or [],
            completed_activities=m.completed_activities or [],
            sequence=m.sequence,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in milestones
    ]

    return LearningPathResponse(
        id=str(path.id),
        developer_id=str(path.developer_id),
        target_role_id=str(path.target_role_id) if path.target_role_id else None,
        target_role_name=path.target_role.name if path.target_role else None,
        skill_gaps=path.skill_gaps or {},
        phases=path.phases or [],
        milestones=milestone_responses,
        status=path.status,
        progress_percentage=path.progress_percentage,
        trajectory_status=path.trajectory_status,
        estimated_success_probability=path.estimated_success_probability,
        risk_factors=path.risk_factors or [],
        recommendations=path.recommendations or [],
        started_at=path.started_at,
        target_completion=path.target_completion,
        actual_completion=path.actual_completion,
        generated_by_model=path.generated_by_model,
        last_regenerated_at=path.last_regenerated_at,
        created_at=path.created_at,
        updated_at=path.updated_at,
    )


@router.post("/paths/{path_id}/regenerate", response_model=LearningPathResponse)
async def regenerate_learning_path(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Regenerate a learning path with updated data. Owner or admin-in-shared-workspace."""
    await _require_path_access(db, path_id, str(current_user.id))
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)

    # Get the path first
    path = await service.get_learning_path(path_id)
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    # Get the developer
    dev_service = DeveloperService(db)
    developer = await dev_service.get_by_id(str(path.developer_id))

    if not developer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Developer not found",
        )

    # Regenerate
    updated_path = await service.regenerate_path(path_id, developer)

    if not updated_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to regenerate path",
        )

    return LearningPathResponse(
        id=str(updated_path.id),
        developer_id=str(updated_path.developer_id),
        target_role_id=str(updated_path.target_role_id) if updated_path.target_role_id else None,
        target_role_name=updated_path.target_role.name if updated_path.target_role else None,
        skill_gaps=updated_path.skill_gaps or {},
        phases=updated_path.phases or [],
        milestones=[],
        status=updated_path.status,
        progress_percentage=updated_path.progress_percentage,
        trajectory_status=updated_path.trajectory_status,
        estimated_success_probability=updated_path.estimated_success_probability,
        risk_factors=updated_path.risk_factors or [],
        recommendations=updated_path.recommendations or [],
        started_at=updated_path.started_at,
        target_completion=updated_path.target_completion,
        actual_completion=updated_path.actual_completion,
        generated_by_model=updated_path.generated_by_model,
        last_regenerated_at=updated_path.last_regenerated_at,
        created_at=updated_path.created_at,
        updated_at=updated_path.updated_at,
    )


@router.get("/paths/{path_id}/progress", response_model=PathProgressUpdate)
async def get_path_progress(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get progress summary for a learning path. Owner or admin-in-shared-workspace."""
    await _require_path_access(db, path_id, str(current_user.id))
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)

    # Get the path
    path = await service.get_learning_path(path_id)
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    # Get the developer and update progress
    dev_service = DeveloperService(db)
    developer = await dev_service.get_by_id(str(path.developer_id))

    if not developer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Developer not found",
        )

    update = await service.update_progress(path_id, developer)

    if not update:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update progress",
        )

    return PathProgressUpdate(
        path_id=update.path_id,
        previous_progress=update.previous_progress,
        new_progress=update.new_progress,
        milestones_completed=update.milestones_completed,
        skills_improved=update.skills_improved,
        trajectory_status=TrajectoryStatus(update.trajectory_status),
    )


@router.get("/paths/{path_id}/milestones", response_model=list[LearningMilestoneResponse])
async def get_path_milestones(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get milestones for a learning path. Owner or admin-in-shared-workspace."""
    await _require_path_access(db, path_id, str(current_user.id))
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)

    # Verify path exists
    path = await service.get_learning_path(path_id)
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    milestones = await service.get_milestones(path_id)

    return [
        LearningMilestoneResponse(
            id=str(m.id),
            learning_path_id=str(m.learning_path_id),
            skill_name=m.skill_name,
            target_score=m.target_score,
            current_score=m.current_score,
            status=MilestoneStatus(m.status),
            target_date=m.target_date,
            completed_date=m.completed_date,
            recommended_activities=m.recommended_activities or [],
            completed_activities=m.completed_activities or [],
            sequence=m.sequence,
            created_at=m.created_at,
            updated_at=m.updated_at,
        )
        for m in milestones
    ]


@router.get("/paths/{path_id}/activities", response_model=list[LearningActivity])
async def get_recommended_activities(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get recommended activities for a learning path. Owner or admin-in-shared-workspace."""
    await _require_path_access(db, path_id, str(current_user.id))
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)

    # Verify path exists
    path = await service.get_learning_path(path_id)
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    activities = await service.get_recommended_activities(path_id)

    return [
        LearningActivity(
            type=a.type,
            description=a.description,
            source=a.source,
            url=a.url,
            estimated_hours=a.estimated_hours,
        )
        for a in activities
    ]


@router.get("/developers/{developer_id}/stretch-tasks", response_model=list[StretchAssignment])
async def get_stretch_assignments(
    developer_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get stretch assignment recommendations for a developer. Self or admin-in-shared-workspace."""
    await _require_developer_visibility(db, str(current_user.id), developer_id)
    dev_service = DeveloperService(db)
    developer = await dev_service.get_by_id(developer_id)

    if not developer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Developer not found",
        )

    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)

    # TODO: Get actual available tasks from task sources
    # For now, return empty list if no active path
    active_path = await service.get_active_path(developer_id)
    if not active_path:
        return []

    # In a real implementation, we'd fetch tasks from Jira/Linear/GitHub
    available_tasks: list[dict[str, Any]] = []
    assignments = await service.get_stretch_assignments(developer, available_tasks)

    return [
        StretchAssignment(
            task_id=a.task_id,
            task_title=a.task_title,
            source=a.source,
            skill_growth=a.skill_growth,
            alignment_score=a.alignment_score,
            challenge_level=a.challenge_level,
        )
        for a in assignments
    ]


@router.post("/paths/{path_id}/pause")
async def pause_learning_path(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Pause a learning path. Owner only."""
    await _require_path_access(db, path_id, str(current_user.id), owner_only=True)
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)
    success = await service.pause_path(path_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    return {"status": "paused", "path_id": path_id}


@router.post("/paths/{path_id}/resume")
async def resume_learning_path(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Resume a paused learning path. Owner only."""
    await _require_path_access(db, path_id, str(current_user.id), owner_only=True)
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)
    success = await service.resume_path(path_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    return {"status": "active", "path_id": path_id}


@router.post("/paths/{path_id}/abandon")
async def abandon_learning_path(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Abandon a learning path. Owner only."""
    await _require_path_access(db, path_id, str(current_user.id), owner_only=True)
    llm_gateway = get_llm_gateway()
    service = LearningPathService(db, llm_gateway)
    success = await service.abandon_path(path_id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    return {"status": "abandoned", "path_id": path_id}


# Course Search Endpoints
from aexy.schemas.external_course import (
    CourseSearchResponse,
    CourseImportRequest,
)
from aexy.services.course_provider_service import CourseProviderService
from aexy.services.learning_activity_service import LearningActivityService
from aexy.schemas.learning_activity import ActivityLogCreate, ActivityType, ActivitySource


@router.get("/courses/search", response_model=CourseSearchResponse)
async def search_courses(
    skill: str,
    providers: str = "youtube",
    max_results: int = 10,
    current_user: Developer = Depends(get_current_developer),
):
    """Search for external courses by skill.

    Args:
        skill: Skill or topic to search for.
        providers: Comma-separated list of providers (e.g., "youtube,coursera").
        max_results: Maximum number of results per provider.

    Returns:
        List of matching courses.
    """
    provider_list = [p.strip() for p in providers.split(",")]

    service = CourseProviderService()
    courses = await service.search_courses(
        skill_name=skill,
        providers=provider_list,
        max_results=max_results,
    )

    return CourseSearchResponse(
        courses=courses,
        total_results=len(courses),
        providers_searched=provider_list,
    )


@router.post("/courses/import", status_code=status.HTTP_201_CREATED)
async def import_course_as_activity(
    data: CourseImportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Import an external course as a learning activity. For the current user only."""
    developer_id = str(current_user.id)
    course = data.course

    # Map provider to activity source
    source_map = {
        "youtube": ActivitySource.YOUTUBE,
        "coursera": ActivitySource.COURSERA,
        "udemy": ActivitySource.UDEMY,
        "pluralsight": ActivitySource.PLURALSIGHT,
    }
    activity_source = source_map.get(course.provider, ActivitySource.MANUAL)

    # Determine activity type based on provider
    activity_type = ActivityType.VIDEO if course.provider == "youtube" else ActivityType.COURSE

    activity_data = ActivityLogCreate(
        activity_type=activity_type,
        title=course.title,
        description=course.description,
        source=activity_source,
        external_id=course.external_id,
        external_url=course.url,
        thumbnail_url=course.thumbnail_url,
        estimated_duration_minutes=course.duration_minutes,
        learning_path_id=data.learning_path_id,
        milestone_id=data.milestone_id,
        tags=[],
        skill_tags=course.skill_tags,
        extra_data={
            "provider": course.provider,
            "instructor": course.instructor,
            "is_free": course.is_free,
            "difficulty": course.difficulty,
        },
    )

    service = LearningActivityService(db)
    activity = await service.create_activity(developer_id, activity_data)

    return {
        "message": "Course imported as activity",
        "activity_id": str(activity.id),
        "title": activity.title,
    }


@router.get("/courses/recommended")
async def get_recommended_courses(
    path_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get recommended courses based on learning path skill gaps. Owner or admin."""
    await _require_path_access(db, path_id, str(current_user.id))
    llm_gateway = get_llm_gateway()
    path_service = LearningPathService(db, llm_gateway)

    path = await path_service.get_learning_path(path_id)
    if not path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Learning path not found",
        )

    # Get courses for each skill gap
    course_service = CourseProviderService()
    recommendations = {}

    for skill_name in path.skill_gaps.keys():
        courses = await course_service.search_courses(
            skill_name=skill_name,
            providers=["youtube"],
            max_results=3,
        )
        recommendations[skill_name] = [c.model_dump() for c in courses]

    return {
        "path_id": path_id,
        "recommendations": recommendations,
    }


# ============================================================================
# Team Learning Endpoints
# ============================================================================
from sqlalchemy import select
from pydantic import BaseModel
from aexy.models.team import TeamMember, Team
from aexy.models.developer import Developer
from aexy.models.career import LearningPath


class TeamMemberLearningStatus(BaseModel):
    """Learning status for a team member."""
    developer_id: str
    developer_name: str | None
    developer_avatar_url: str | None
    has_active_path: bool
    active_path_id: str | None
    active_path_target_role: str | None
    progress_percentage: float
    trajectory_status: str | None
    skills_in_progress: list[str]


class TeamLearningOverview(BaseModel):
    """Overview of learning for a team."""
    team_id: str
    team_name: str
    total_members: int
    members_with_paths: int
    average_progress: float
    members: list[TeamMemberLearningStatus]


class TeamSkillRecommendation(BaseModel):
    """Skill recommendation for a team."""
    skill: str
    priority: str  # "critical", "high", "medium", "low"
    coverage_percentage: float
    average_proficiency: float
    members_lacking: int
    reason: str


class TeamLearningRecommendations(BaseModel):
    """Learning recommendations for a team."""
    team_id: str
    team_name: str
    recommended_skills: list[TeamSkillRecommendation]


@router.get("/teams/{team_id}/overview", response_model=TeamLearningOverview)
async def get_team_learning_overview(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get learning status for all team members. Team-workspace member required."""
    if not is_valid_uuid(team_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid team ID",
        )

    team = await _require_team_workspace_member(db, team_id, str(current_user.id))

    # Get team members with developer info
    members_result = await db.execute(
        select(TeamMember, Developer)
        .join(Developer, TeamMember.developer_id == Developer.id)
        .where(TeamMember.team_id == team_id)
    )
    team_members = list(members_result.all())

    if not team_members:
        return TeamLearningOverview(
            team_id=team_id,
            team_name=team.name,
            total_members=0,
            members_with_paths=0,
            average_progress=0.0,
            members=[],
        )

    # Get learning paths for all team members
    developer_ids = [str(tm.developer_id) for tm, _ in team_members]
    paths_result = await db.execute(
        select(LearningPath)
        .where(LearningPath.developer_id.in_(developer_ids))
        .where(LearningPath.status.in_(["active", "paused"]))
    )
    paths = list(paths_result.scalars().all())

    # Create a map of developer_id -> active path
    developer_paths: dict[str, LearningPath] = {}
    for path in paths:
        dev_id = str(path.developer_id)
        # Prefer active paths over paused
        if dev_id not in developer_paths or path.status == "active":
            developer_paths[dev_id] = path

    # Build member statuses
    member_statuses: list[TeamMemberLearningStatus] = []
    total_progress = 0.0
    members_with_paths = 0

    for team_member, developer in team_members:
        dev_id = str(developer.id)
        path = developer_paths.get(dev_id)

        if path:
            members_with_paths += 1
            total_progress += path.progress_percentage or 0.0

            # Get skills in progress from milestones or skill_gaps
            skills_in_progress = []
            if path.skill_gaps:
                skills_in_progress = list(path.skill_gaps.keys())[:5]

            member_statuses.append(TeamMemberLearningStatus(
                developer_id=dev_id,
                developer_name=developer.name,
                developer_avatar_url=developer.avatar_url,
                has_active_path=True,
                active_path_id=str(path.id),
                active_path_target_role=path.target_role.name if path.target_role else None,
                progress_percentage=path.progress_percentage or 0.0,
                trajectory_status=path.trajectory_status,
                skills_in_progress=skills_in_progress,
            ))
        else:
            member_statuses.append(TeamMemberLearningStatus(
                developer_id=dev_id,
                developer_name=developer.name,
                developer_avatar_url=developer.avatar_url,
                has_active_path=False,
                active_path_id=None,
                active_path_target_role=None,
                progress_percentage=0.0,
                trajectory_status=None,
                skills_in_progress=[],
            ))

    average_progress = total_progress / members_with_paths if members_with_paths > 0 else 0.0

    return TeamLearningOverview(
        team_id=team_id,
        team_name=team.name,
        total_members=len(team_members),
        members_with_paths=members_with_paths,
        average_progress=round(average_progress, 1),
        members=member_statuses,
    )


@router.get("/teams/{team_id}/recommendations", response_model=TeamLearningRecommendations)
async def get_team_learning_recommendations(
    team_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get recommended skills for team to develop. Team-workspace member required."""
    if not is_valid_uuid(team_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid team ID",
        )

    team = await _require_team_workspace_member(db, team_id, str(current_user.id))

    # Get team members with developer info
    members_result = await db.execute(
        select(Developer)
        .join(TeamMember, TeamMember.developer_id == Developer.id)
        .where(TeamMember.team_id == team_id)
    )
    developers = list(members_result.scalars().all())

    if not developers:
        return TeamLearningRecommendations(
            team_id=team_id,
            team_name=team.name,
            recommended_skills=[],
        )

    # Analyze team skills
    all_skills: dict[str, list[tuple[str, float]]] = {}  # skill -> [(dev_id, score)]
    team_size = len(developers)

    for dev in developers:
        fingerprint = dev.skill_fingerprint or {}

        # Languages
        for lang in fingerprint.get("languages") or []:
            skill_name = lang.get("name", "")
            score = lang.get("proficiency_score", 0)
            if skill_name:
                if skill_name not in all_skills:
                    all_skills[skill_name] = []
                all_skills[skill_name].append((str(dev.id), score))

        # Frameworks
        for fw in fingerprint.get("frameworks") or []:
            skill_name = fw.get("name", "")
            score = fw.get("proficiency_score", 0)
            if skill_name:
                if skill_name not in all_skills:
                    all_skills[skill_name] = []
                all_skills[skill_name].append((str(dev.id), score))

        # Domains
        for domain in fingerprint.get("domains") or []:
            skill_name = domain.get("name", "")
            score = domain.get("confidence_score", 0)
            if skill_name:
                if skill_name not in all_skills:
                    all_skills[skill_name] = []
                all_skills[skill_name].append((str(dev.id), score))

    # Identify skill gaps and create recommendations
    recommendations: list[TeamSkillRecommendation] = []

    for skill_name, dev_scores in all_skills.items():
        # Filter to meaningful scores (> 30)
        meaningful_scores = [s for _, s in dev_scores if s > 30]
        coverage = len(meaningful_scores) / team_size if team_size > 0 else 0
        avg_proficiency = sum(s for _, s in dev_scores) / len(dev_scores) if dev_scores else 0

        # Identify skills where team has low coverage or proficiency
        members_lacking = team_size - len(meaningful_scores)

        # Determine priority based on coverage and proficiency
        if coverage < 0.2 or avg_proficiency < 30:
            priority = "critical"
            reason = f"Only {int(coverage * 100)}% of team has this skill"
        elif coverage < 0.4 or avg_proficiency < 50:
            priority = "high"
            reason = f"Low team coverage ({int(coverage * 100)}%) and proficiency ({int(avg_proficiency)}%)"
        elif coverage < 0.6:
            priority = "medium"
            reason = f"Could improve team coverage from {int(coverage * 100)}%"
        else:
            continue  # Skip well-covered skills

        recommendations.append(TeamSkillRecommendation(
            skill=skill_name,
            priority=priority,
            coverage_percentage=round(coverage * 100, 1),
            average_proficiency=round(avg_proficiency, 1),
            members_lacking=members_lacking,
            reason=reason,
        ))

    # Sort by priority
    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    recommendations.sort(key=lambda x: priority_order.get(x.priority, 3))

    # Limit to top 10 recommendations
    recommendations = recommendations[:10]

    return TeamLearningRecommendations(
        team_id=team_id,
        team_name=team.name,
        recommended_skills=recommendations,
    )

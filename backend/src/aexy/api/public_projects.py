"""Public Projects API endpoints - No authentication required."""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.models.project import Project
from aexy.models.sprint import Sprint, SprintTask
from aexy.models.story import UserStory
from aexy.models.bug import Bug
from aexy.models.goal import Goal as OKRGoal
from aexy.models.release import Release
from aexy.models.epic import Epic
from aexy.schemas.project import (
    PublicProjectResponse,
    PublicTaskItem,
    PublicStoryItem,
    PublicBugItem,
    PublicGoalItem,
    PublicReleaseItem,
    PublicRoadmapItem,
    PublicSprintItem,
)


router = APIRouter(
    prefix="/public/projects",
    tags=["Public Projects"],
)

# Valid public tabs
VALID_TABS = ["overview", "backlog", "board", "bugs", "goals", "releases", "roadmap", "stories", "sprints"]


def get_public_tabs(project: Project) -> list[str]:
    """Extract enabled public tabs from project settings."""
    settings = project.settings or {}
    public_tabs = settings.get("public_tabs", {})
    enabled = public_tabs.get("enabled_tabs", ["overview"])
    # Filter to only valid tabs
    return [tab for tab in enabled if tab in VALID_TABS]


async def get_public_project_or_404(
    public_slug: str,
    db: AsyncSession,
    required_tab: str | None = None,
) -> Project:
    """Get a public project by slug, optionally checking if a tab is enabled."""
    result = await db.execute(
        select(Project).where(
            Project.public_slug == public_slug,
            Project.is_public == True,
            Project.is_active == True,
        )
    )
    project = result.scalar_one_or_none()

    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found or is not public",
        )

    # Check if the required tab is enabled
    if required_tab:
        enabled_tabs = get_public_tabs(project)
        if required_tab not in enabled_tabs:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"The '{required_tab}' tab is not publicly accessible for this project",
            )

    return project


@router.get("/{public_slug}", response_model=PublicProjectResponse)
async def get_public_project(
    public_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a public project by its public slug.

    This endpoint is publicly accessible without authentication.
    Only returns project data if the project is marked as public.
    """
    project = await get_public_project_or_404(public_slug, db)

    return PublicProjectResponse(
        id=str(project.id),
        name=project.name,
        slug=project.slug,
        public_slug=project.public_slug,
        description=project.description,
        color=project.color,
        icon=project.icon,
        status=project.status,
        member_count=project.member_count,
        team_count=project.team_count,
        public_tabs=get_public_tabs(project),
        created_at=project.created_at,
    )


@router.get("/{public_slug}/backlog", response_model=list[PublicTaskItem])
async def get_public_backlog(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public backlog tasks for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="backlog")

    result = await db.execute(
        select(SprintTask)
        .where(
            SprintTask.workspace_id == project.workspace_id,
            SprintTask.status == 'backlog',  # Backlog items have no sprint
        )
        .order_by(SprintTask.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    tasks = result.scalars().all()

    return [
        PublicTaskItem(
            id=str(t.id),
            title=t.title,
            description=t.description,
            priority=t.priority,
            status=t.status,
            labels=t.labels or [],
            story_points=t.story_points,
            created_at=t.created_at,
        )
        for t in tasks
    ]


@router.get("/{public_slug}/board", response_model=dict)
async def get_public_board(
    public_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Get public board data (tasks grouped by status) for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="board")

    result = await db.execute(
        select(SprintTask)
        .where(
            SprintTask.workspace_id == project.workspace_id,
            SprintTask.sprint_id != None,  # Only tasks assigned to sprints, not backlog
        )
        .order_by(SprintTask.created_at.desc())
        .limit(200)
    )
    tasks = result.scalars().all()

    # Group by status
    board = {
        "todo": [],
        "in_progress": [],
        "review": [],
        "done": [],
        "backlog":[],
    }

    status_mapping = {
        "todo": "todo",
        "in_progress": "in_progress",
        "review": "review",
        "done": "done",
        "blocked": "in_progress",
        "backlog":"backlog",
    }

    for t in tasks:
        task_item = PublicTaskItem(
            id=str(t.id),
            title=t.title,
            description=t.description,
            priority=t.priority,
            status=t.status,
            labels=t.labels or [],
            story_points=t.story_points,
            created_at=t.created_at,
        )
        column = status_mapping.get(t.status, "todo")
        board[column].append(task_item.model_dump())

    return board


@router.get("/{public_slug}/stories", response_model=list[PublicStoryItem])
async def get_public_stories(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public user stories for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="stories")

    result = await db.execute(
        select(UserStory)
        .where(
            UserStory.workspace_id == project.workspace_id,
        )
        .order_by(UserStory.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    stories = result.scalars().all()

    return [
        PublicStoryItem(
            id=str(s.id),
            key=s.key,
            title=s.title,
            as_a=s.as_a,
            i_want=s.i_want,
            so_that=s.so_that,
            priority=s.priority,
            status=s.status,
            story_points=s.story_points,
            labels=s.labels or [],
            created_at=s.created_at,
        )
        for s in stories
    ]


@router.get("/{public_slug}/bugs", response_model=list[PublicBugItem])
async def get_public_bugs(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public bugs for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="bugs")

    result = await db.execute(
        select(Bug)
        .where(
            Bug.workspace_id == project.workspace_id,
            Bug.project_id == project.id,
        )
        .order_by(Bug.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    bugs = result.scalars().all()

    return [
        PublicBugItem(
            id=str(b.id),
            key=b.key,
            title=b.title,
            severity=b.severity,
            priority=b.priority,
            bug_type=b.bug_type,
            status=b.status,
            is_regression=b.is_regression,
            labels=b.labels or [],
            created_at=b.created_at,
        )
        for b in bugs
    ]


@router.get("/{public_slug}/goals", response_model=list[PublicGoalItem])
async def get_public_goals(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public OKR goals for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="goals")

    result = await db.execute(
        select(OKRGoal)
        .where(
            OKRGoal.workspace_id == project.workspace_id,
        )
        .order_by(OKRGoal.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    goals = result.scalars().all()

    return [
        PublicGoalItem(
            id=str(g.id),
            key=g.key,
            title=g.title,
            description=g.description,
            goal_type=g.goal_type,
            status=g.status,
            progress_percentage=g.progress_percentage,
            target_value=g.target_value,
            current_value=g.current_value,
            start_date=g.start_date,
            end_date=g.end_date,
        )
        for g in goals
    ]


@router.get("/{public_slug}/releases", response_model=list[PublicReleaseItem])
async def get_public_releases(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public releases for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="releases")

    result = await db.execute(
        select(Release)
        .where(
            Release.workspace_id == project.workspace_id,
            Release.project_id == project.id,
        )
        .order_by(Release.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    releases = result.scalars().all()

    return [
        PublicReleaseItem(
            id=str(r.id),
            name=r.name,
            version=r.version,
            description=r.description,
            status=r.status,
            risk_level=r.risk_level,
            target_date=r.target_date,
            actual_release_date=r.actual_release_date,
            created_at=r.created_at,
        )
        for r in releases
    ]


@router.get("/{public_slug}/roadmap", response_model=list[PublicRoadmapItem])
async def get_public_roadmap(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public roadmap (sprints) for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="roadmap")

    result = await db.execute(
        select(Sprint)
        .where(
            Sprint.workspace_id == project.workspace_id,
        )
        .order_by(Sprint.start_date.desc())
        .limit(limit)
        .offset(offset)
    )
    sprints = result.scalars().all()

    # Get task counts for each sprint
    roadmap_items = []
    for sprint in sprints:
        # Count tasks for this sprint
        tasks_result = await db.execute(
            select(SprintTask)
            .where(SprintTask.sprint_id == sprint.id)
        )
        tasks = tasks_result.scalars().all()
        tasks_count = len(tasks)
        completed_count = len([t for t in tasks if t.status == "done"])
        total_points = sum(t.story_points or 0 for t in tasks)
        completed_points = sum(t.story_points or 0 for t in tasks if t.status == "done")

        roadmap_items.append(
            PublicRoadmapItem(
                id=str(sprint.id),
                name=sprint.name,
                goal=sprint.goal,
                status=sprint.status,
                start_date=sprint.start_date,
                end_date=sprint.end_date,
                tasks_count=tasks_count,
                completed_count=completed_count,
                total_points=total_points,
                completed_points=completed_points,
            )
        )

    return roadmap_items


@router.get("/{public_slug}/sprints", response_model=list[PublicSprintItem])
async def get_public_sprints(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public sprints for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="sprints")

    result = await db.execute(
        select(Sprint)
        .where(
            Sprint.workspace_id == project.workspace_id,
        )
        .order_by(Sprint.start_date.desc())
        .limit(limit)
        .offset(offset)
    )
    sprints = result.scalars().all()

    # Get task counts for each sprint
    sprint_items = []
    for sprint in sprints:
        # Count tasks for this sprint
        tasks_result = await db.execute(
            select(SprintTask)
            .where(SprintTask.sprint_id == sprint.id)
        )
        tasks = tasks_result.scalars().all()
        tasks_count = len(tasks)
        completed_count = len([t for t in tasks if t.status == "done"])
        total_points = sum(t.story_points or 0 for t in tasks)
        completed_points = sum(t.story_points or 0 for t in tasks if t.status == "done")

        sprint_items.append(
            PublicSprintItem(
                id=str(sprint.id),
                name=sprint.name,
                goal=sprint.goal,
                status=sprint.status,
                start_date=sprint.start_date,
                end_date=sprint.end_date,
                tasks_count=tasks_count,
                completed_count=completed_count,
                total_points=total_points,
                completed_points=completed_points,
            )
        )

    return sprint_items

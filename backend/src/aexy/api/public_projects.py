"""Public Projects API endpoints - No authentication required."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select, func, case, update
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from aexy.core.database import get_db
from aexy.core.sanitize import sanitize_title, sanitize_description, sanitize_comment
from aexy.api.developers import get_current_developer, get_optional_current_developer
from aexy.models.developer import Developer
from aexy.models.project import Project
from aexy.models.sprint import Sprint, SprintTask
from aexy.models.story import UserStory
from aexy.models.bug import Bug
from aexy.models.goal import Goal as OKRGoal
from aexy.models.release import Release
from aexy.models.epic import Epic
from aexy.models.roadmap_voting import RoadmapRequest, RoadmapVote, RoadmapComment
from aexy.models.workspace import WorkspaceMember
from aexy.schemas.project import (
    PublicProjectResponse,
    PublicTaskItem,
    PublicStoryItem,
    PublicBugItem,
    PublicGoalItem,
    PublicReleaseItem,
    PublicRoadmapItem,
    PublicSprintItem,
    RoadmapRequestResponse,
    RoadmapRequestCreate,
    RoadmapRequestUpdate,
    RoadmapCommentResponse,
    RoadmapCommentCreate,
    RoadmapVoteResponse,
    RoadmapRequestAuthor,
    PaginatedRoadmapRequestsResponse,
)


router = APIRouter(
    prefix="/public/projects",
    tags=["Public Projects"],
)

# Valid public tabs
VALID_TABS = ["overview", "backlog", "board", "bugs", "goals", "releases", "roadmap", "stories", "sprints", "timeline"]


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


async def get_sprint_task_stats(
    db: AsyncSession,
    sprint_ids: list[UUID],
) -> dict[str, dict]:
    """
    Fetch task statistics for multiple sprints in a single query.

    Returns a dict mapping sprint_id to stats:
    {
        "sprint_id": {
            "tasks_count": int,
            "completed_count": int,
            "total_points": int,
            "completed_points": int,
        }
    }
    """
    if not sprint_ids:
        return {}

    # Use SQL aggregation to compute stats in a single query
    result = await db.execute(
        select(
            SprintTask.sprint_id,
            func.count(SprintTask.id).label("tasks_count"),
            func.sum(case((SprintTask.status == "done", 1), else_=0)).label("completed_count"),
            func.coalesce(func.sum(SprintTask.story_points), 0).label("total_points"),
            func.coalesce(
                func.sum(case((SprintTask.status == "done", SprintTask.story_points), else_=0)),
                0
            ).label("completed_points"),
        )
        .where(SprintTask.sprint_id.in_(sprint_ids))
        .group_by(SprintTask.sprint_id)
    )
    rows = result.all()

    # Build stats dict
    stats = {}
    for row in rows:
        stats[str(row.sprint_id)] = {
            "tasks_count": row.tasks_count or 0,
            "completed_count": row.completed_count or 0,
            "total_points": row.total_points or 0,
            "completed_points": row.completed_points or 0,
        }

    # Ensure all sprint_ids have an entry (even if no tasks)
    default_stats = {
        "tasks_count": 0,
        "completed_count": 0,
        "total_points": 0,
        "completed_points": 0,
    }
    for sprint_id in sprint_ids:
        if str(sprint_id) not in stats:
            stats[str(sprint_id)] = default_stats.copy()

    return stats


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


async def _fetch_sprints_with_stats(
    db: AsyncSession,
    workspace_id: UUID,
    limit: int,
    offset: int,
    order_ascending: bool = False,
) -> list[dict]:
    """
    Fetch sprints with task statistics for a workspace.

    This is a shared helper used by roadmap, sprints, and timeline endpoints
    to avoid code duplication.

    Args:
        db: Database session.
        workspace_id: Workspace ID to filter sprints.
        limit: Maximum number of sprints to return.
        offset: Number of sprints to skip.
        order_ascending: If True, order by start_date ascending; otherwise descending.

    Returns:
        List of sprint data dicts with task statistics.
    """
    order = Sprint.start_date.asc() if order_ascending else Sprint.start_date.desc()

    result = await db.execute(
        select(Sprint)
        .where(Sprint.workspace_id == workspace_id)
        .order_by(order)
        .limit(limit)
        .offset(offset)
    )
    sprints = result.scalars().all()

    # Get task stats for all sprints in a single query (avoids N+1)
    sprint_ids = [sprint.id for sprint in sprints]
    stats = await get_sprint_task_stats(db, sprint_ids)

    return [
        {
            "id": str(sprint.id),
            "name": sprint.name,
            "goal": sprint.goal,
            "status": sprint.status,
            "start_date": sprint.start_date,
            "end_date": sprint.end_date,
            "tasks_count": stats[str(sprint.id)]["tasks_count"],
            "completed_count": stats[str(sprint.id)]["completed_count"],
            "total_points": stats[str(sprint.id)]["total_points"],
            "completed_points": stats[str(sprint.id)]["completed_points"],
        }
        for sprint in sprints
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
    sprint_data = await _fetch_sprints_with_stats(
        db, project.workspace_id, limit, offset, order_ascending=False
    )
    return [PublicRoadmapItem(**data) for data in sprint_data]


@router.get("/{public_slug}/sprints", response_model=list[PublicSprintItem])
async def get_public_sprints(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public sprints for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="sprints")
    sprint_data = await _fetch_sprints_with_stats(
        db, project.workspace_id, limit, offset, order_ascending=False
    )
    return [PublicSprintItem(**data) for data in sprint_data]


@router.get("/{public_slug}/timeline", response_model=list[PublicSprintItem])
async def get_public_timeline(
    public_slug: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get public timeline (sprints for timeline view) for a project."""
    project = await get_public_project_or_404(public_slug, db, required_tab="timeline")
    sprint_data = await _fetch_sprints_with_stats(
        db, project.workspace_id, limit, offset, order_ascending=True
    )
    return [PublicSprintItem(**data) for data in sprint_data]


# ============================================================================
# Roadmap Voting Endpoints
# ============================================================================

def _build_request_response(
    request: RoadmapRequest,
    current_user_id: str | None = None,
    user_voted_ids: set[str] | None = None,
) -> RoadmapRequestResponse:
    """Build a RoadmapRequestResponse from a RoadmapRequest model."""
    has_voted = False
    if current_user_id and user_voted_ids:
        has_voted = request.id in user_voted_ids

    return RoadmapRequestResponse(
        id=str(request.id),
        title=request.title,
        description=request.description,
        category=request.category,
        status=request.status,
        vote_count=request.vote_count,
        comment_count=request.comment_count,
        submitted_by=RoadmapRequestAuthor(
            id=str(request.submitted_by.id),
            name=request.submitted_by.name,
            avatar_url=request.submitted_by.avatar_url,
        ),
        admin_response=request.admin_response,
        responded_at=request.responded_at,
        created_at=request.created_at,
        updated_at=request.updated_at,
        has_voted=has_voted,
    )


@router.get("/{public_slug}/roadmap-requests", response_model=PaginatedRoadmapRequestsResponse)
async def get_roadmap_requests(
    public_slug: str,
    status_filter: str | None = Query(default=None, alias="status"),
    category: str | None = Query(default=None),
    sort_by: str = Query(default="votes"),  # "votes" | "newest" | "oldest"
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: Developer | None = Depends(get_optional_current_developer),
):
    """Get roadmap requests for a project (public, but shows vote status if logged in)."""
    project = await get_public_project_or_404(public_slug, db, required_tab="roadmap")

    # Build base filter condition
    base_filter = RoadmapRequest.project_id == project.id
    filters = [base_filter]

    if status_filter:
        filters.append(RoadmapRequest.status == status_filter)
    if category:
        filters.append(RoadmapRequest.category == category)

    # Get total count
    count_query = select(func.count(RoadmapRequest.id)).where(*filters)
    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    # Build query for items
    query = select(RoadmapRequest).where(*filters)

    # Sort
    if sort_by == "newest":
        query = query.order_by(RoadmapRequest.created_at.desc())
    elif sort_by == "oldest":
        query = query.order_by(RoadmapRequest.created_at.asc())
    else:  # votes (default)
        query = query.order_by(RoadmapRequest.vote_count.desc(), RoadmapRequest.created_at.desc())

    # Pagination
    offset = (page - 1) * page_size
    query = query.limit(page_size).offset(offset)

    result = await db.execute(query)
    requests = result.scalars().all()

    # Get user's votes if logged in
    user_voted_ids: set[str] = set()
    if current_user and requests:
        votes_result = await db.execute(
            select(RoadmapVote.request_id)
            .where(
                RoadmapVote.voter_id == str(current_user.id),
                RoadmapVote.request_id.in_([r.id for r in requests]),
            )
        )
        user_voted_ids = {str(v) for v in votes_result.scalars().all()}

    items = [
        _build_request_response(r, str(current_user.id) if current_user else None, user_voted_ids)
        for r in requests
    ]

    total_pages = (total + page_size - 1) // page_size if total > 0 else 1

    return PaginatedRoadmapRequestsResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


@router.get("/{public_slug}/roadmap-requests/{request_id}", response_model=RoadmapRequestResponse)
async def get_roadmap_request(
    public_slug: str,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer | None = Depends(get_optional_current_developer),
):
    """Get a single roadmap request."""
    project = await get_public_project_or_404(public_slug, db, required_tab="roadmap")

    result = await db.execute(
        select(RoadmapRequest)
        .where(
            RoadmapRequest.id == request_id,
            RoadmapRequest.project_id == project.id,
        )
    )
    request = result.scalar_one_or_none()

    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Check if user has voted
    user_voted_ids: set[str] = set()
    if current_user:
        vote_result = await db.execute(
            select(RoadmapVote)
            .where(
                RoadmapVote.request_id == request_id,
                RoadmapVote.voter_id == str(current_user.id),
            )
        )
        if vote_result.scalar_one_or_none():
            user_voted_ids.add(request_id)

    return _build_request_response(request, str(current_user.id) if current_user else None, user_voted_ids)


@router.post("/{public_slug}/roadmap-requests", response_model=RoadmapRequestResponse)
async def create_roadmap_request(
    public_slug: str,
    data: RoadmapRequestCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Create a new roadmap request (requires authentication)."""
    project = await get_public_project_or_404(public_slug, db, required_tab="roadmap")

    # Validate category
    valid_categories = ["feature", "improvement", "integration", "bug_fix", "other"]
    if data.category not in valid_categories:
        raise HTTPException(status_code=400, detail=f"Invalid category. Must be one of: {valid_categories}")

    # Sanitize user input
    sanitized_title = sanitize_title(data.title)
    sanitized_description = sanitize_description(data.description)

    if not sanitized_title:
        raise HTTPException(status_code=400, detail="Title is required")

    # Create request
    request = RoadmapRequest(
        workspace_id=project.workspace_id,
        project_id=project.id,
        title=sanitized_title,
        description=sanitized_description,
        category=data.category,
        submitted_by_id=str(current_user.id),
    )

    db.add(request)
    await db.commit()
    await db.refresh(request)

    return _build_request_response(request, str(current_user.id), set())


@router.post("/{public_slug}/roadmap-requests/{request_id}/vote", response_model=RoadmapVoteResponse)
async def vote_roadmap_request(
    public_slug: str,
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Vote for a roadmap request (requires authentication). Toggle vote on/off."""
    project = await get_public_project_or_404(public_slug, db, required_tab="roadmap")

    # Get the request
    result = await db.execute(
        select(RoadmapRequest)
        .where(
            RoadmapRequest.id == request_id,
            RoadmapRequest.project_id == project.id,
        )
    )
    request = result.scalar_one_or_none()

    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Check if user already voted
    vote_result = await db.execute(
        select(RoadmapVote)
        .where(
            RoadmapVote.request_id == request_id,
            RoadmapVote.voter_id == str(current_user.id),
        )
    )
    existing_vote = vote_result.scalar_one_or_none()

    if existing_vote:
        # Remove vote (toggle off)
        await db.delete(existing_vote)

        await db.execute(
            update(RoadmapRequest)
            .where(RoadmapRequest.id == request_id)
            .values(vote_count=RoadmapRequest.vote_count - 1)
        )

        has_voted = False

    else:
        # Add vote
        db.add(
            RoadmapVote(
                request_id=request_id,
                voter_id=str(current_user.id),
            )
        )

        await db.execute(
            update(RoadmapRequest)
            .where(RoadmapRequest.id == request_id)
            .values(vote_count=RoadmapRequest.vote_count + 1)
        )

        has_voted = True

    await db.commit()
    count_result = await db.execute(
        select(RoadmapRequest.vote_count)
        .where(RoadmapRequest.id == request_id)
    )
    vote_count = count_result.scalar_one()

    return RoadmapVoteResponse(
        success=True,
        vote_count=vote_count,
        has_voted=has_voted,
    )


@router.get("/{public_slug}/roadmap-requests/{request_id}/comments", response_model=list[RoadmapCommentResponse])
async def get_roadmap_comments(
    public_slug: str,
    request_id: str,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Get comments for a roadmap request (public)."""
    project = await get_public_project_or_404(public_slug, db, required_tab="roadmap")

    # Verify request exists
    request_result = await db.execute(
        select(RoadmapRequest)
        .where(
            RoadmapRequest.id == request_id,
            RoadmapRequest.project_id == project.id,
        )
    )
    if not request_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Request not found")

    # Get comments
    result = await db.execute(
        select(RoadmapComment)
        .where(RoadmapComment.request_id == request_id)
        .order_by(RoadmapComment.created_at.asc())
        .limit(limit)
        .offset(offset)
    )
    comments = result.scalars().all()

    return [
        RoadmapCommentResponse(
            id=str(c.id),
            content=c.content,
            author=RoadmapRequestAuthor(
                id=str(c.author.id),
                name=c.author.name,
                avatar_url=c.author.avatar_url,
            ),
            is_admin_response=c.is_admin_response,
            created_at=c.created_at,
        )
        for c in comments
    ]


@router.post("/{public_slug}/roadmap-requests/{request_id}/comments", response_model=RoadmapCommentResponse)
async def create_roadmap_comment(
    public_slug: str,
    request_id: str,
    data: RoadmapCommentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Create a comment on a roadmap request (requires authentication)."""
    project = await get_public_project_or_404(public_slug, db, required_tab="roadmap")

    # Verify request exists
    request_result = await db.execute(
        select(RoadmapRequest)
        .where(
            RoadmapRequest.id == request_id,
            RoadmapRequest.project_id == project.id,
        )
    )
    request = request_result.scalar_one_or_none()
    if not request:
        raise HTTPException(status_code=404, detail="Request not found")

    # Sanitize user input
    sanitized_content = sanitize_comment(data.content)
    if not sanitized_content:
        raise HTTPException(status_code=400, detail="Comment content is required")

    # Check if user is workspace admin/owner
    member_result = await db.execute(
        select(WorkspaceMember)
        .where(
            WorkspaceMember.workspace_id == project.workspace_id,
            WorkspaceMember.developer_id == str(current_user.id),
        )
    )
    member = member_result.scalar_one_or_none()
    is_admin = member is not None and member.role in ("owner", "admin")

    # Create comment
    comment = RoadmapComment(
        request_id=request_id,
        content=sanitized_content,
        author_id=str(current_user.id),
        is_admin_response=is_admin,
    )

    db.add(comment)
    request.comment_count += 1
    await db.commit()
    await db.refresh(comment)

    return RoadmapCommentResponse(
        id=str(comment.id),
        content=comment.content,
        author=RoadmapRequestAuthor(
            id=str(current_user.id),
            name=current_user.name,
            avatar_url=current_user.avatar_url,
        ),
        is_admin_response=comment.is_admin_response,
        created_at=comment.created_at,
    )

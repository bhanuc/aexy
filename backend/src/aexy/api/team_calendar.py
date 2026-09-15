"""Team calendar API endpoints for unified calendar view."""

from datetime import date
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException
from sqlalchemy import select

from aexy.core.database import get_db
from aexy.api.developers import get_current_developer
from aexy.models.developer import Developer
from aexy.models.team import Team
from aexy.schemas.team_calendar import (
    TeamCalendarResponse,
    WhoIsOutResponse,
    AvailabilitySummary,
)
from aexy.services.project_service import assert_team_filter_visible
from aexy.services.team_calendar_service import TeamCalendarService
from aexy.services.workspace_service import WorkspaceService


router = APIRouter(
    prefix="/workspaces/{workspace_id}/calendar",
    tags=["Team Calendar"],
)


async def _require_workspace_and_team(
    db: AsyncSession,
    workspace_id: str,
    developer_id: str,
    team_id: str | None,
) -> None:
    if not await WorkspaceService(db).check_permission(workspace_id, developer_id, "viewer"):
        raise HTTPException(status_code=403, detail="Not a member of this workspace")
    if team_id:
        team_check = await db.execute(
            select(Team.id).where(
                Team.id == team_id,
                Team.workspace_id == workspace_id,
            )
        )
        if team_check.scalar_one_or_none() is None:
            raise HTTPException(status_code=404, detail="Team not found")
    # And, if the team is a project's board, one this caller may see: asking
    # who is out on a team is asking about that team.
    await assert_team_filter_visible(db, team_id, developer_id, workspace_id)


@router.get("/team", response_model=TeamCalendarResponse)
async def get_team_calendar(
    workspace_id: str,
    start_date: date = Query(...),
    end_date: date = Query(...),
    team_id: str | None = Query(None),
    event_types: list[str] | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get unified team calendar events (leaves + bookings + holidays)."""
    if (end_date - start_date).days > 366:
        raise HTTPException(
            status_code=400, detail="Date range cannot exceed 366 days"
        )
    await _require_workspace_and_team(db, workspace_id, str(current_developer.id), team_id)
    service = TeamCalendarService(db)
    events = await service.get_team_calendar_events(
        workspace_id=workspace_id,
        start_date=start_date,
        end_date=end_date,
        team_id=team_id,
        event_types=event_types,
    )
    return TeamCalendarResponse(events=events, total=len(events))


@router.get("/who-is-out", response_model=WhoIsOutResponse)
async def get_who_is_out(
    workspace_id: str,
    query_date: date = Query(None, alias="date"),
    team_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get who's out today (or on a specific date)."""
    from datetime import date as dt_date

    await _require_workspace_and_team(db, workspace_id, str(current_developer.id), team_id)
    effective_date = query_date or dt_date.today()
    service = TeamCalendarService(db)
    entries = await service.get_who_is_out(
        workspace_id=workspace_id,
        target_date=effective_date,
        team_id=team_id,
    )
    return WhoIsOutResponse(
        date=effective_date,
        entries=entries,
        total_out=len(entries),
    )


@router.get("/availability-summary", response_model=AvailabilitySummary)
async def get_availability_summary(
    workspace_id: str,
    query_date: date = Query(None, alias="date"),
    team_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get availability summary (available/on-leave/on-holiday counts)."""
    from datetime import date as dt_date

    await _require_workspace_and_team(db, workspace_id, str(current_developer.id), team_id)
    effective_date = query_date or dt_date.today()
    service = TeamCalendarService(db)
    summary = await service.get_availability_summary(
        workspace_id=workspace_id,
        target_date=effective_date,
        team_id=team_id,
    )
    return summary

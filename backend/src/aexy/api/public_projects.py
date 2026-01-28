"""Public Projects API endpoints - No authentication required."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.models.project import Project
from aexy.schemas.project import PublicProjectResponse


router = APIRouter(
    prefix="/public/projects",
    tags=["Public Projects"],
)


@router.get("/{public_slug}", response_model=PublicProjectResponse)
async def get_public_project(
    public_slug: str,
    db: AsyncSession = Depends(get_db),
):
    """Get a public project by its public slug.

    This endpoint is publicly accessible without authentication.
    Only returns project data if the project is marked as public.
    """
    # Query project by public_slug and ensure it's public
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
        created_at=project.created_at,
    )

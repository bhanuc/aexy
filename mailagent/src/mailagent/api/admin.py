"""Admin API endpoints for provider management."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from mailagent.database import get_db
from mailagent.schemas import (
    AdminDashboardResponse,
    ProviderCreate,
    ProviderResponse,
    ProviderStatus,
    ProviderUpdate,
)
from mailagent.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin"])


def get_admin_service(db: AsyncSession = Depends(get_db)) -> AdminService:
    """Dependency to get admin service."""
    return AdminService(db)


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(
    service: AdminService = Depends(get_admin_service),
) -> AdminDashboardResponse:
    """Get admin dashboard statistics."""
    return await service.get_dashboard_stats()


@router.post("/providers", response_model=ProviderResponse, status_code=status.HTTP_201_CREATED)
async def create_provider(
    data: ProviderCreate,
    service: AdminService = Depends(get_admin_service),
) -> ProviderResponse:
    """Create a new email provider."""
    return await service.create_provider(data)


@router.get("/providers", response_model=list[ProviderResponse])
async def list_providers(
    status_filter: ProviderStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    service: AdminService = Depends(get_admin_service),
) -> list[ProviderResponse]:
    """List all email providers."""
    return await service.list_providers(status=status_filter, limit=limit, offset=offset)


@router.get("/providers/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: UUID,
    service: AdminService = Depends(get_admin_service),
) -> ProviderResponse:
    """Get a specific email provider."""
    provider = await service.get_provider(provider_id)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    return provider


@router.patch("/providers/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: UUID,
    data: ProviderUpdate,
    service: AdminService = Depends(get_admin_service),
) -> ProviderResponse:
    """Update an email provider."""
    provider = await service.update_provider(provider_id, data)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    return provider


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: UUID,
    service: AdminService = Depends(get_admin_service),
) -> None:
    """Delete an email provider."""
    deleted = await service.delete_provider(provider_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )


@router.post("/providers/{provider_id}/test")
async def test_provider(
    provider_id: UUID,
    service: AdminService = Depends(get_admin_service),
) -> dict:
    """Test provider connection."""
    result = await service.test_provider_connection(provider_id)
    if not result.get("success") and result.get("error") == "Provider not found":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found",
        )
    return result

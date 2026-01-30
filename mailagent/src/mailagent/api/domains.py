"""Domain setup and verification API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from mailagent.database import get_db
from mailagent.schemas import (
    DomainCreate,
    DomainResponse,
    DomainStatus,
    DomainUpdate,
    DomainVerificationResponse,
)
from mailagent.services.domain_service import DomainService

router = APIRouter(prefix="/domains", tags=["Domains"])


def get_domain_service(db: AsyncSession = Depends(get_db)) -> DomainService:
    """Dependency to get domain service."""
    return DomainService(db)


@router.post("/", response_model=DomainResponse, status_code=status.HTTP_201_CREATED)
async def create_domain(
    data: DomainCreate,
    service: DomainService = Depends(get_domain_service),
) -> DomainResponse:
    """Create a new sending domain."""
    return await service.create_domain(data)


@router.get("/", response_model=list[DomainResponse])
async def list_domains(
    status_filter: DomainStatus | None = None,
    limit: int = 50,
    offset: int = 0,
    service: DomainService = Depends(get_domain_service),
) -> list[DomainResponse]:
    """List all sending domains."""
    return await service.list_domains(status=status_filter, limit=limit, offset=offset)


@router.get("/{domain_id}", response_model=DomainResponse)
async def get_domain(
    domain_id: UUID,
    service: DomainService = Depends(get_domain_service),
) -> DomainResponse:
    """Get a specific sending domain."""
    domain = await service.get_domain(domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )
    return domain


@router.get("/by-name/{domain_name}", response_model=DomainResponse)
async def get_domain_by_name(
    domain_name: str,
    service: DomainService = Depends(get_domain_service),
) -> DomainResponse:
    """Get a domain by its domain name."""
    domain = await service.get_domain_by_name(domain_name)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )
    return domain


@router.patch("/{domain_id}", response_model=DomainResponse)
async def update_domain(
    domain_id: UUID,
    data: DomainUpdate,
    service: DomainService = Depends(get_domain_service),
) -> DomainResponse:
    """Update a sending domain."""
    domain = await service.update_domain(domain_id, data)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )
    return domain


@router.delete("/{domain_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_domain(
    domain_id: UUID,
    service: DomainService = Depends(get_domain_service),
) -> None:
    """Delete a sending domain."""
    deleted = await service.delete_domain(domain_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )


@router.post("/{domain_id}/verify", response_model=DomainVerificationResponse)
async def verify_domain(
    domain_id: UUID,
    service: DomainService = Depends(get_domain_service),
) -> DomainVerificationResponse:
    """Verify domain DNS records."""
    try:
        return await service.verify_domain(domain_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        )


@router.post("/{domain_id}/start-warming", response_model=DomainResponse)
async def start_warming(
    domain_id: UUID,
    service: DomainService = Depends(get_domain_service),
) -> DomainResponse:
    """Start domain warming process."""
    try:
        domain = await service.start_warming(domain_id)
        if domain is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Domain not found",
            )
        return domain
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/{domain_id}/advance-warming", response_model=DomainResponse)
async def advance_warming(
    domain_id: UUID,
    service: DomainService = Depends(get_domain_service),
) -> DomainResponse:
    """Advance to next warming day (for testing/manual advancement)."""
    domain = await service.advance_warming_day(domain_id)
    if domain is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Domain not found",
        )
    return domain

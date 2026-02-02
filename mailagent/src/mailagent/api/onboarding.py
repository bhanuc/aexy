"""Email onboarding API endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from mailagent.database import get_db
from mailagent.schemas import (
    InboxCreate,
    InboxResponse,
    OnboardingRequest,
    OnboardingResponse,
)
from mailagent.services.onboarding_service import OnboardingService

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


def get_onboarding_service(db: AsyncSession = Depends(get_db)) -> OnboardingService:
    """Dependency to get onboarding service."""
    return OnboardingService(db)


@router.post("/start", response_model=OnboardingResponse)
async def start_onboarding(
    data: OnboardingRequest,
    service: OnboardingService = Depends(get_onboarding_service),
) -> OnboardingResponse:
    """Start the email onboarding process."""
    try:
        return await service.start_onboarding(data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.post("/inboxes", response_model=InboxResponse, status_code=status.HTTP_201_CREATED)
async def create_inbox(
    data: InboxCreate,
    service: OnboardingService = Depends(get_onboarding_service),
) -> InboxResponse:
    """Create a new inbox."""
    try:
        return await service.create_inbox(data)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )


@router.get("/inboxes", response_model=list[InboxResponse])
async def list_inboxes(
    domain_id: UUID | None = None,
    verified_only: bool = False,
    limit: int = 50,
    offset: int = 0,
    service: OnboardingService = Depends(get_onboarding_service),
) -> list[InboxResponse]:
    """List all inboxes."""
    return await service.list_inboxes(
        domain_id=domain_id,
        verified_only=verified_only,
        limit=limit,
        offset=offset,
    )


@router.get("/inboxes/{inbox_id}", response_model=InboxResponse)
async def get_inbox(
    inbox_id: UUID,
    service: OnboardingService = Depends(get_onboarding_service),
) -> InboxResponse:
    """Get a specific inbox."""
    inbox = await service.get_inbox(inbox_id)
    if inbox is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found",
        )
    return inbox


@router.get("/inboxes/by-email/{email}", response_model=InboxResponse)
async def get_inbox_by_email(
    email: str,
    service: OnboardingService = Depends(get_onboarding_service),
) -> InboxResponse:
    """Get an inbox by email address."""
    inbox = await service.get_inbox_by_email(email)
    if inbox is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found",
        )
    return inbox


@router.delete("/inboxes/{inbox_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inbox(
    inbox_id: UUID,
    service: OnboardingService = Depends(get_onboarding_service),
) -> None:
    """Delete an inbox."""
    deleted = await service.delete_inbox(inbox_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Inbox not found",
        )


@router.post("/inboxes/{inbox_id}/verify")
async def verify_inbox(
    inbox_id: UUID,
    token: str,
    service: OnboardingService = Depends(get_onboarding_service),
) -> dict:
    """Verify an inbox using verification token."""
    verified = await service.verify_inbox(inbox_id, token)
    if not verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification token",
        )
    return {"verified": True}


@router.post("/inboxes/{inbox_id}/resend-verification")
async def resend_verification(
    inbox_id: UUID,
    service: OnboardingService = Depends(get_onboarding_service),
) -> dict:
    """Resend verification email."""
    sent = await service.resend_verification(inbox_id)
    if not sent:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not send verification email",
        )
    return {"sent": True}

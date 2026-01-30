"""Email onboarding service for inbox creation and verification."""

import secrets
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mailagent.schemas import (
    InboxCreate,
    InboxResponse,
    OnboardingRequest,
    OnboardingResponse,
)


class OnboardingService:
    """Service for email onboarding and inbox management."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_inbox(self, data: InboxCreate) -> InboxResponse:
        """Create a new inbox/sending identity."""
        from mailagent.models import Inbox

        # Extract domain from email
        email_domain = data.email.split("@")[1].lower()

        # Check if domain exists if domain_id provided
        if data.domain_id:
            from mailagent.models import SendingDomain

            domain_result = await self.db.execute(
                select(SendingDomain).where(SendingDomain.id == data.domain_id)
            )
            domain = domain_result.scalar_one_or_none()
            if domain is None:
                raise ValueError("Domain not found")
            if domain.domain != email_domain:
                raise ValueError("Email domain does not match specified domain")

        inbox = Inbox(
            email=data.email.lower(),
            display_name=data.display_name,
            domain_id=data.domain_id,
            is_verified=False,
            verification_token=secrets.token_urlsafe(32),
        )

        self.db.add(inbox)
        await self.db.flush()
        await self.db.refresh(inbox)

        return InboxResponse.model_validate(inbox)

    async def get_inbox(self, inbox_id: UUID) -> InboxResponse | None:
        """Get an inbox by ID."""
        from mailagent.models import Inbox

        result = await self.db.execute(select(Inbox).where(Inbox.id == inbox_id))
        inbox = result.scalar_one_or_none()

        if inbox is None:
            return None

        return InboxResponse.model_validate(inbox)

    async def get_inbox_by_email(self, email: str) -> InboxResponse | None:
        """Get an inbox by email address."""
        from mailagent.models import Inbox

        result = await self.db.execute(
            select(Inbox).where(Inbox.email == email.lower())
        )
        inbox = result.scalar_one_or_none()

        if inbox is None:
            return None

        return InboxResponse.model_validate(inbox)

    async def list_inboxes(
        self,
        domain_id: UUID | None = None,
        verified_only: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InboxResponse]:
        """List all inboxes with optional filtering."""
        from mailagent.models import Inbox

        query = select(Inbox).order_by(Inbox.created_at.desc())

        if domain_id is not None:
            query = query.where(Inbox.domain_id == domain_id)

        if verified_only:
            query = query.where(Inbox.is_verified == True)

        query = query.limit(limit).offset(offset)
        result = await self.db.execute(query)
        inboxes = result.scalars().all()

        return [InboxResponse.model_validate(i) for i in inboxes]

    async def delete_inbox(self, inbox_id: UUID) -> bool:
        """Delete an inbox."""
        from mailagent.models import Inbox

        result = await self.db.execute(select(Inbox).where(Inbox.id == inbox_id))
        inbox = result.scalar_one_or_none()

        if inbox is None:
            return False

        await self.db.delete(inbox)
        return True

    async def verify_inbox(self, inbox_id: UUID, token: str) -> bool:
        """Verify an inbox using verification token."""
        from mailagent.models import Inbox

        result = await self.db.execute(select(Inbox).where(Inbox.id == inbox_id))
        inbox = result.scalar_one_or_none()

        if inbox is None:
            return False

        if inbox.verification_token != token:
            return False

        inbox.is_verified = True
        inbox.verification_token = None
        inbox.verified_at = datetime.now(timezone.utc)
        inbox.updated_at = datetime.now(timezone.utc)

        await self.db.flush()
        return True

    async def start_onboarding(self, data: OnboardingRequest) -> OnboardingResponse:
        """Start the email onboarding process."""
        # Create inbox
        inbox_data = InboxCreate(
            email=data.email,
            display_name=data.display_name,
        )
        inbox = await self.create_inbox(inbox_data)

        verification_sent = False
        welcome_sent = False
        next_steps = []

        # Send verification email
        verification_sent = await self._send_verification_email(inbox.id)
        if verification_sent:
            next_steps.append("Check your email to verify your inbox")
        else:
            next_steps.append("Verification email failed - please try again")

        # Send welcome email if requested
        if data.send_welcome_email and inbox.is_verified:
            welcome_sent = await self._send_welcome_email(inbox.id)

        if not inbox.is_verified:
            next_steps.append("Verify your email to start sending")

        next_steps.append("Configure your sending domain for better deliverability")
        next_steps.append("Set up SPF, DKIM, and DMARC records")

        return OnboardingResponse(
            inbox_id=inbox.id,
            email=inbox.email,
            verification_sent=verification_sent,
            welcome_email_sent=welcome_sent,
            next_steps=next_steps,
        )

    async def resend_verification(self, inbox_id: UUID) -> bool:
        """Resend verification email."""
        from mailagent.models import Inbox

        result = await self.db.execute(select(Inbox).where(Inbox.id == inbox_id))
        inbox = result.scalar_one_or_none()

        if inbox is None:
            return False

        if inbox.is_verified:
            return False  # Already verified

        # Generate new token
        inbox.verification_token = secrets.token_urlsafe(32)
        inbox.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        return await self._send_verification_email(inbox_id)

    async def _send_verification_email(self, inbox_id: UUID) -> bool:
        """Send verification email to inbox."""
        # TODO: Implement actual email sending via provider
        # For now, return True as placeholder
        return True

    async def _send_welcome_email(self, inbox_id: UUID) -> bool:
        """Send welcome email to inbox."""
        # TODO: Implement actual email sending via provider
        # For now, return True as placeholder
        return True

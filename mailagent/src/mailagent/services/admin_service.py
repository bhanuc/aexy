"""Admin service for email provider management."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from mailagent.schemas import (
    AdminDashboardResponse,
    ProviderCreate,
    ProviderResponse,
    ProviderStatus,
    ProviderUpdate,
)


class AdminService:
    """Service for managing email providers and admin operations."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_provider(self, data: ProviderCreate) -> ProviderResponse:
        """Create a new email provider."""
        # Import here to avoid circular dependency with models
        from mailagent.models import EmailProvider

        provider = EmailProvider(
            name=data.name,
            provider_type=data.provider_type.value,
            credentials=data.credentials.model_dump(exclude_none=True),
            status=ProviderStatus.SETUP.value,
            is_default=data.is_default,
            priority=data.priority,
            rate_limit_per_minute=data.rate_limit_per_minute,
            rate_limit_per_day=data.rate_limit_per_day,
        )

        # If this is default, unset other defaults
        if data.is_default:
            await self._unset_default_providers()

        self.db.add(provider)
        await self.db.flush()
        await self.db.refresh(provider)

        return ProviderResponse.model_validate(provider)

    async def get_provider(self, provider_id: UUID) -> ProviderResponse | None:
        """Get a provider by ID."""
        from mailagent.models import EmailProvider

        result = await self.db.execute(
            select(EmailProvider).where(EmailProvider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if provider is None:
            return None

        return ProviderResponse.model_validate(provider)

    async def list_providers(
        self,
        status: ProviderStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ProviderResponse]:
        """List all providers with optional filtering."""
        from mailagent.models import EmailProvider

        query = select(EmailProvider).order_by(EmailProvider.priority)

        if status is not None:
            query = query.where(EmailProvider.status == status.value)

        query = query.limit(limit).offset(offset)
        result = await self.db.execute(query)
        providers = result.scalars().all()

        return [ProviderResponse.model_validate(p) for p in providers]

    async def update_provider(
        self,
        provider_id: UUID,
        data: ProviderUpdate,
    ) -> ProviderResponse | None:
        """Update a provider."""
        from mailagent.models import EmailProvider

        result = await self.db.execute(
            select(EmailProvider).where(EmailProvider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if provider is None:
            return None

        update_data = data.model_dump(exclude_none=True)

        if "credentials" in update_data:
            update_data["credentials"] = data.credentials.model_dump(exclude_none=True)

        if "status" in update_data:
            update_data["status"] = data.status.value

        # Handle default flag
        if update_data.get("is_default"):
            await self._unset_default_providers()

        for key, value in update_data.items():
            setattr(provider, key, value)

        provider.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(provider)

        return ProviderResponse.model_validate(provider)

    async def delete_provider(self, provider_id: UUID) -> bool:
        """Delete a provider."""
        from mailagent.models import EmailProvider

        result = await self.db.execute(
            select(EmailProvider).where(EmailProvider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if provider is None:
            return False

        await self.db.delete(provider)
        return True

    async def test_provider_connection(self, provider_id: UUID) -> dict:
        """Test provider connection and update health status."""
        from mailagent.models import EmailProvider

        result = await self.db.execute(
            select(EmailProvider).where(EmailProvider.id == provider_id)
        )
        provider = result.scalar_one_or_none()

        if provider is None:
            return {"success": False, "error": "Provider not found"}

        # Test connection based on provider type
        success = await self._test_provider(provider)

        provider.last_health_check = datetime.now(timezone.utc)
        if success:
            provider.status = ProviderStatus.ACTIVE.value
            provider.error_count = 0
        else:
            provider.error_count += 1
            if provider.error_count >= 3:
                provider.status = ProviderStatus.ERROR.value

        await self.db.flush()

        return {
            "success": success,
            "status": provider.status,
            "error_count": provider.error_count,
        }

    async def get_dashboard_stats(self) -> AdminDashboardResponse:
        """Get admin dashboard statistics."""
        from mailagent.models import EmailProvider, SendingDomain, Inbox

        # Provider stats
        providers_result = await self.db.execute(
            select(
                func.count(EmailProvider.id).label("total"),
                func.count(EmailProvider.id)
                .filter(EmailProvider.status == ProviderStatus.ACTIVE.value)
                .label("active"),
            )
        )
        provider_stats = providers_result.one()

        # Domain stats
        domains_result = await self.db.execute(
            select(
                func.count(SendingDomain.id).label("total"),
                func.count(SendingDomain.id)
                .filter(SendingDomain.status.in_(["verified", "active"]))
                .label("verified"),
            )
        )
        domain_stats = domains_result.one()

        # Inbox stats
        inbox_result = await self.db.execute(select(func.count(Inbox.id)))
        total_inboxes = inbox_result.scalar() or 0

        return AdminDashboardResponse(
            total_providers=provider_stats.total or 0,
            active_providers=provider_stats.active or 0,
            total_domains=domain_stats.total or 0,
            verified_domains=domain_stats.verified or 0,
            total_inboxes=total_inboxes,
            emails_sent_today=0,  # TODO: Implement with email tracking
            emails_sent_this_month=0,
            error_rate_percent=0.0,
            avg_delivery_time_ms=None,
        )

    async def _unset_default_providers(self) -> None:
        """Unset default flag on all providers."""
        from mailagent.models import EmailProvider

        result = await self.db.execute(
            select(EmailProvider).where(EmailProvider.is_default == True)
        )
        for provider in result.scalars().all():
            provider.is_default = False

    async def _test_provider(self, provider) -> bool:
        """Test provider connection."""
        # Implementation depends on provider type
        # For now, return True as placeholder
        # TODO: Implement actual connection tests
        return True

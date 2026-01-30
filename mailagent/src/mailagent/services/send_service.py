"""Unified email sending service with failover and rate limiting."""

import asyncio
from datetime import datetime, timedelta
from typing import Optional
from uuid import UUID, uuid4

from mailagent.providers.base import EmailMessage, SendResult, ProviderConfig
from mailagent.providers.factory import get_email_provider
from mailagent.database import async_session_factory
from sqlalchemy import text


class SendService:
    """Unified service for sending emails with provider failover and rate limiting."""

    def __init__(self):
        self._providers: dict[UUID, any] = {}
        self._rate_limits: dict[UUID, dict] = {}

    async def load_providers(self) -> None:
        """Load all active providers from database."""
        async with async_session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT id, name, provider_type, credentials, is_default,
                           priority, rate_limit_per_minute, rate_limit_per_day
                    FROM mailagent_providers
                    WHERE is_active = true
                    ORDER BY priority
                """)
            )
            rows = result.fetchall()

            for row in rows:
                config = ProviderConfig(
                    id=row.id,
                    name=row.name,
                    provider_type=row.provider_type,
                    credentials=row.credentials,
                    is_default=row.is_default,
                    priority=row.priority,
                    rate_limit_per_minute=row.rate_limit_per_minute,
                    rate_limit_per_day=row.rate_limit_per_day,
                )
                self._providers[row.id] = get_email_provider(config)
                self._rate_limits[row.id] = {
                    "minute_count": 0,
                    "minute_reset": datetime.utcnow() + timedelta(minutes=1),
                    "day_count": 0,
                    "day_reset": datetime.utcnow() + timedelta(days=1),
                    "per_minute": row.rate_limit_per_minute,
                    "per_day": row.rate_limit_per_day,
                }

    async def send(
        self,
        message: EmailMessage,
        provider_id: Optional[UUID] = None,
        domain_id: Optional[UUID] = None,
    ) -> SendResult:
        """Send an email with automatic failover.

        Args:
            message: The email to send
            provider_id: Specific provider to use (optional)
            domain_id: Domain to use for warming tracking (optional)

        Returns:
            SendResult with success status
        """
        # Get ordered list of providers to try
        providers_to_try = self._get_providers_to_try(provider_id)

        last_error = None
        for pid, provider in providers_to_try:
            # Check rate limits
            if not self._check_rate_limit(pid):
                continue

            try:
                result = await provider.send(message)

                if result.success:
                    # Update rate limit counters
                    self._increment_rate_limit(pid)

                    # Record the send in database
                    await self._record_send(message, result, pid, domain_id)

                    return result

                last_error = result.error

            except Exception as e:
                last_error = str(e)
                continue

        # All providers failed
        return SendResult(
            success=False,
            provider="none",
            error=f"All providers failed. Last error: {last_error}",
        )

    async def send_batch(
        self,
        messages: list[EmailMessage],
        provider_id: Optional[UUID] = None,
        concurrency: int = 10,
    ) -> list[SendResult]:
        """Send multiple emails with concurrency control.

        Args:
            messages: List of emails to send
            provider_id: Specific provider to use (optional)
            concurrency: Maximum concurrent sends

        Returns:
            List of SendResults
        """
        semaphore = asyncio.Semaphore(concurrency)

        async def send_with_semaphore(msg: EmailMessage) -> SendResult:
            async with semaphore:
                return await self.send(msg, provider_id)

        tasks = [send_with_semaphore(msg) for msg in messages]
        return await asyncio.gather(*tasks)

    def _get_providers_to_try(
        self, provider_id: Optional[UUID]
    ) -> list[tuple[UUID, any]]:
        """Get ordered list of providers to try."""
        if provider_id and provider_id in self._providers:
            return [(provider_id, self._providers[provider_id])]

        # Return all providers sorted by priority (already loaded in order)
        return list(self._providers.items())

    def _check_rate_limit(self, provider_id: UUID) -> bool:
        """Check if provider is within rate limits."""
        limits = self._rate_limits.get(provider_id)
        if not limits:
            return True

        now = datetime.utcnow()

        # Reset minute counter if needed
        if now >= limits["minute_reset"]:
            limits["minute_count"] = 0
            limits["minute_reset"] = now + timedelta(minutes=1)

        # Reset day counter if needed
        if now >= limits["day_reset"]:
            limits["day_count"] = 0
            limits["day_reset"] = now + timedelta(days=1)

        # Check minute limit
        if limits["per_minute"] and limits["minute_count"] >= limits["per_minute"]:
            return False

        # Check day limit
        if limits["per_day"] and limits["day_count"] >= limits["per_day"]:
            return False

        return True

    def _increment_rate_limit(self, provider_id: UUID) -> None:
        """Increment rate limit counters."""
        limits = self._rate_limits.get(provider_id)
        if limits:
            limits["minute_count"] += 1
            limits["day_count"] += 1

    async def _record_send(
        self,
        message: EmailMessage,
        result: SendResult,
        provider_id: UUID,
        domain_id: Optional[UUID],
    ) -> None:
        """Record send in database for tracking."""
        async with async_session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO mailagent_messages (
                        id, provider_id, domain_id, message_id,
                        from_address, to_addresses, subject,
                        status, provider_message_id, sent_at
                    ) VALUES (
                        :id, :provider_id, :domain_id, :message_id,
                        :from_address, :to_addresses, :subject,
                        'sent', :provider_message_id, NOW()
                    )
                """),
                {
                    "id": uuid4(),
                    "provider_id": provider_id,
                    "domain_id": domain_id,
                    "message_id": result.message_id,
                    "from_address": message.from_address.address,
                    "to_addresses": [a.address for a in message.to_addresses],
                    "subject": message.subject,
                    "provider_message_id": result.provider_message_id,
                },
            )
            await session.commit()


# Global instance
_send_service: Optional[SendService] = None


async def get_send_service() -> SendService:
    """Get or create the send service singleton."""
    global _send_service
    if _send_service is None:
        _send_service = SendService()
        await _send_service.load_providers()
    return _send_service

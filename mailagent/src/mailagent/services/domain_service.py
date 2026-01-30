"""Domain setup and verification service."""

import asyncio
from datetime import datetime, timezone
from uuid import UUID

import dns.resolver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from mailagent.schemas import (
    DNSRecord,
    DomainCreate,
    DomainResponse,
    DomainStatus,
    DomainUpdate,
    DomainVerificationResponse,
    WarmingScheduleType,
)


class DomainService:
    """Service for managing sending domains and DNS verification."""

    # Warming schedules: days -> daily volume
    WARMING_SCHEDULES = {
        WarmingScheduleType.CONSERVATIVE: {
            1: 50, 2: 100, 3: 200, 4: 400, 5: 600,
            6: 800, 7: 1000, 8: 1500, 9: 2000, 10: 3000,
            11: 4000, 12: 5000, 13: 6000, 14: 8000, 15: 10000,
            16: 12000, 17: 15000, 18: 20000, 19: 25000, 20: 30000,
            21: 50000,
        },
        WarmingScheduleType.MODERATE: {
            1: 100, 2: 250, 3: 500, 4: 1000, 5: 2000,
            6: 3000, 7: 5000, 8: 7500, 9: 10000, 10: 15000,
            11: 20000, 12: 30000, 13: 40000, 14: 50000,
        },
        WarmingScheduleType.AGGRESSIVE: {
            1: 500, 2: 1000, 3: 2500, 4: 5000, 5: 10000,
            6: 25000, 7: 50000,
        },
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_domain(self, data: DomainCreate) -> DomainResponse:
        """Create a new sending domain."""
        from mailagent.models import SendingDomain

        # Generate DNS records for verification
        dns_records = self._generate_dns_records(data.domain)

        domain = SendingDomain(
            domain=data.domain.lower(),
            status=DomainStatus.PENDING.value,
            dns_records=[r.model_dump() for r in dns_records],
            warming_schedule=data.warming_schedule.value,
            health_score=0,
        )

        self.db.add(domain)
        await self.db.flush()
        await self.db.refresh(domain)

        return self._to_response(domain)

    async def get_domain(self, domain_id: UUID) -> DomainResponse | None:
        """Get a domain by ID."""
        from mailagent.models import SendingDomain

        result = await self.db.execute(
            select(SendingDomain).where(SendingDomain.id == domain_id)
        )
        domain = result.scalar_one_or_none()

        if domain is None:
            return None

        return self._to_response(domain)

    async def get_domain_by_name(self, domain_name: str) -> DomainResponse | None:
        """Get a domain by domain name."""
        from mailagent.models import SendingDomain

        result = await self.db.execute(
            select(SendingDomain).where(SendingDomain.domain == domain_name.lower())
        )
        domain = result.scalar_one_or_none()

        if domain is None:
            return None

        return self._to_response(domain)

    async def list_domains(
        self,
        status: DomainStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DomainResponse]:
        """List all domains with optional filtering."""
        from mailagent.models import SendingDomain

        query = select(SendingDomain).order_by(SendingDomain.created_at.desc())

        if status is not None:
            query = query.where(SendingDomain.status == status.value)

        query = query.limit(limit).offset(offset)
        result = await self.db.execute(query)
        domains = result.scalars().all()

        return [self._to_response(d) for d in domains]

    async def update_domain(
        self,
        domain_id: UUID,
        data: DomainUpdate,
    ) -> DomainResponse | None:
        """Update a domain."""
        from mailagent.models import SendingDomain

        result = await self.db.execute(
            select(SendingDomain).where(SendingDomain.id == domain_id)
        )
        domain = result.scalar_one_or_none()

        if domain is None:
            return None

        if data.status is not None:
            domain.status = data.status.value
        if data.warming_schedule is not None:
            domain.warming_schedule = data.warming_schedule.value
        if data.daily_limit is not None:
            domain.daily_limit = data.daily_limit

        domain.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(domain)

        return self._to_response(domain)

    async def delete_domain(self, domain_id: UUID) -> bool:
        """Delete a domain."""
        from mailagent.models import SendingDomain

        result = await self.db.execute(
            select(SendingDomain).where(SendingDomain.id == domain_id)
        )
        domain = result.scalar_one_or_none()

        if domain is None:
            return False

        await self.db.delete(domain)
        return True

    async def verify_domain(self, domain_id: UUID) -> DomainVerificationResponse:
        """Verify domain DNS records."""
        from mailagent.models import SendingDomain

        result = await self.db.execute(
            select(SendingDomain).where(SendingDomain.id == domain_id)
        )
        domain = result.scalar_one_or_none()

        if domain is None:
            raise ValueError("Domain not found")

        domain.status = DomainStatus.VERIFYING.value

        # Verify each DNS record
        dns_records = []
        spf_verified = False
        dkim_verified = False
        dmarc_verified = False

        for record_data in domain.dns_records:
            record = DNSRecord(**record_data)
            verified = await self._verify_dns_record(domain.domain, record)
            record.verified = verified

            if "spf" in record.name.lower() or record.value.startswith("v=spf1"):
                spf_verified = verified
            elif "dkim" in record.name.lower() or "_domainkey" in record.name:
                dkim_verified = verified
            elif "dmarc" in record.name.lower() or record.name.startswith("_dmarc"):
                dmarc_verified = verified

            dns_records.append(record)

        all_verified = spf_verified and dkim_verified and dmarc_verified

        # Update domain status
        if all_verified:
            domain.status = DomainStatus.VERIFIED.value
            domain.health_score = 50  # Start with base score
        else:
            domain.status = DomainStatus.PENDING.value

        domain.dns_records = [r.model_dump() for r in dns_records]
        domain.updated_at = datetime.now(timezone.utc)
        await self.db.flush()

        return DomainVerificationResponse(
            domain=domain.domain,
            spf_verified=spf_verified,
            dkim_verified=dkim_verified,
            dmarc_verified=dmarc_verified,
            all_verified=all_verified,
            dns_records=dns_records,
        )

    async def start_warming(self, domain_id: UUID) -> DomainResponse | None:
        """Start domain warming process."""
        from mailagent.models import SendingDomain

        result = await self.db.execute(
            select(SendingDomain).where(SendingDomain.id == domain_id)
        )
        domain = result.scalar_one_or_none()

        if domain is None:
            return None

        if domain.status != DomainStatus.VERIFIED.value:
            raise ValueError("Domain must be verified before warming")

        domain.status = DomainStatus.WARMING.value
        domain.warming_started_at = datetime.now(timezone.utc)
        domain.warming_day = 1

        # Set initial daily limit based on warming schedule
        schedule_type = WarmingScheduleType(domain.warming_schedule)
        domain.daily_limit = self.WARMING_SCHEDULES[schedule_type].get(1, 50)

        domain.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(domain)

        return self._to_response(domain)

    async def advance_warming_day(self, domain_id: UUID) -> DomainResponse | None:
        """Advance to next warming day and update limits."""
        from mailagent.models import SendingDomain

        result = await self.db.execute(
            select(SendingDomain).where(SendingDomain.id == domain_id)
        )
        domain = result.scalar_one_or_none()

        if domain is None:
            return None

        if domain.status != DomainStatus.WARMING.value:
            return self._to_response(domain)

        schedule_type = WarmingScheduleType(domain.warming_schedule)
        schedule = self.WARMING_SCHEDULES[schedule_type]
        max_day = max(schedule.keys())

        domain.warming_day = min(domain.warming_day + 1, max_day)

        if domain.warming_day >= max_day:
            domain.status = DomainStatus.ACTIVE.value
            domain.daily_limit = None  # No limit once warmed
            domain.health_score = 100
        else:
            domain.daily_limit = schedule.get(domain.warming_day, domain.daily_limit)

        domain.updated_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(domain)

        return self._to_response(domain)

    def _generate_dns_records(self, domain: str) -> list[DNSRecord]:
        """Generate required DNS records for domain verification."""
        import secrets

        dkim_selector = "mailagent"
        verification_token = secrets.token_hex(16)

        return [
            DNSRecord(
                record_type="TXT",
                name=domain,
                value=f"v=spf1 include:_spf.mailagent.io ~all",
                verified=False,
            ),
            DNSRecord(
                record_type="TXT",
                name=f"{dkim_selector}._domainkey.{domain}",
                value=f"v=DKIM1; k=rsa; p={verification_token}",  # Placeholder
                verified=False,
            ),
            DNSRecord(
                record_type="TXT",
                name=f"_dmarc.{domain}",
                value="v=DMARC1; p=quarantine; rua=mailto:dmarc@mailagent.io",
                verified=False,
            ),
            DNSRecord(
                record_type="TXT",
                name=f"_mailagent.{domain}",
                value=f"mailagent-verify={verification_token}",
                verified=False,
            ),
        ]

    async def _verify_dns_record(self, domain: str, record: DNSRecord) -> bool:
        """Verify a DNS record exists and matches expected value."""
        try:
            # Run DNS query in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            answers = await loop.run_in_executor(
                None,
                lambda: dns.resolver.resolve(record.name, record.record_type),
            )

            for rdata in answers:
                txt_value = str(rdata).strip('"')
                if record.value in txt_value or txt_value in record.value:
                    return True

            return False
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return False
        except Exception:
            return False

    def _to_response(self, domain) -> DomainResponse:
        """Convert domain model to response schema."""
        dns_records = [DNSRecord(**r) for r in (domain.dns_records or [])]

        return DomainResponse(
            id=domain.id,
            domain=domain.domain,
            status=DomainStatus(domain.status),
            dns_records=dns_records,
            warming_schedule=(
                WarmingScheduleType(domain.warming_schedule)
                if domain.warming_schedule
                else None
            ),
            daily_limit=domain.daily_limit,
            health_score=domain.health_score or 0,
            created_at=domain.created_at,
            updated_at=domain.updated_at,
        )

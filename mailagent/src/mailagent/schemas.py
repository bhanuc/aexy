"""Pydantic schemas for API validation."""

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


# Enums
class ProviderType(str, Enum):
    SES = "ses"
    SENDGRID = "sendgrid"
    MAILGUN = "mailgun"
    POSTMARK = "postmark"
    SMTP = "smtp"


class ProviderStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    SETUP = "setup"


class DomainStatus(str, Enum):
    PENDING = "pending"
    VERIFYING = "verifying"
    VERIFIED = "verified"
    FAILED = "failed"
    PAUSED = "paused"
    WARMING = "warming"
    ACTIVE = "active"


class WarmingScheduleType(str, Enum):
    CONSERVATIVE = "conservative"  # 21 days
    MODERATE = "moderate"  # 14 days
    AGGRESSIVE = "aggressive"  # 7 days


# Provider Schemas
class ProviderCredentials(BaseModel):
    """Provider-specific credentials."""

    api_key: str | None = None
    api_secret: str | None = None
    region: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_username: str | None = None
    smtp_password: str | None = None


class ProviderCreate(BaseModel):
    """Schema for creating a new email provider."""

    name: str = Field(..., min_length=1, max_length=100)
    provider_type: ProviderType
    credentials: ProviderCredentials
    is_default: bool = False
    priority: int = Field(default=100, ge=1, le=1000)
    rate_limit_per_minute: int | None = None
    rate_limit_per_day: int | None = None


class ProviderUpdate(BaseModel):
    """Schema for updating an email provider."""

    name: str | None = None
    credentials: ProviderCredentials | None = None
    status: ProviderStatus | None = None
    is_default: bool | None = None
    priority: int | None = Field(default=None, ge=1, le=1000)
    rate_limit_per_minute: int | None = None
    rate_limit_per_day: int | None = None


class ProviderResponse(BaseModel):
    """Schema for provider response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    provider_type: ProviderType
    status: ProviderStatus
    is_default: bool
    priority: int
    rate_limit_per_minute: int | None
    rate_limit_per_day: int | None
    last_health_check: datetime | None
    error_count: int
    created_at: datetime
    updated_at: datetime


# Domain Schemas
class DNSRecord(BaseModel):
    """DNS record for domain verification."""

    record_type: str  # TXT, CNAME, MX
    name: str
    value: str
    verified: bool = False


class DomainCreate(BaseModel):
    """Schema for creating a new sending domain."""

    domain: str = Field(..., pattern=r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.[a-zA-Z]{2,}$")
    warming_schedule: WarmingScheduleType = WarmingScheduleType.MODERATE


class DomainUpdate(BaseModel):
    """Schema for updating a sending domain."""

    status: DomainStatus | None = None
    warming_schedule: WarmingScheduleType | None = None
    daily_limit: int | None = Field(default=None, ge=0)


class DomainResponse(BaseModel):
    """Schema for domain response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    status: DomainStatus
    dns_records: list[DNSRecord]
    warming_schedule: WarmingScheduleType | None
    daily_limit: int | None
    health_score: int
    created_at: datetime
    updated_at: datetime


class DomainVerificationResponse(BaseModel):
    """Schema for domain verification result."""

    domain: str
    spf_verified: bool
    dkim_verified: bool
    dmarc_verified: bool
    all_verified: bool
    dns_records: list[DNSRecord]


# Inbox/Onboarding Schemas
class InboxCreate(BaseModel):
    """Schema for creating a new inbox."""

    email: EmailStr
    display_name: str | None = None
    domain_id: UUID | None = None


class InboxResponse(BaseModel):
    """Schema for inbox response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    display_name: str | None
    domain_id: UUID | None
    is_verified: bool
    created_at: datetime


class OnboardingRequest(BaseModel):
    """Schema for starting email onboarding."""

    email: EmailStr
    display_name: str | None = None
    send_welcome_email: bool = True


class OnboardingResponse(BaseModel):
    """Schema for onboarding result."""

    inbox_id: UUID
    email: str
    verification_sent: bool
    welcome_email_sent: bool
    next_steps: list[str]


# Health Schemas
class HealthResponse(BaseModel):
    """Schema for health check response."""

    status: str
    service: str
    version: str
    database: bool
    redis: bool
    timestamp: datetime


class AdminDashboardResponse(BaseModel):
    """Schema for admin dashboard data."""

    total_providers: int
    active_providers: int
    total_domains: int
    verified_domains: int
    total_inboxes: int
    emails_sent_today: int
    emails_sent_this_month: int
    error_rate_percent: float
    avg_delivery_time_ms: float | None

"""Base email provider interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr


class ProviderType(str, Enum):
    SES = "ses"
    SENDGRID = "sendgrid"
    MAILGUN = "mailgun"
    POSTMARK = "postmark"
    SMTP = "smtp"


class EmailAddress(BaseModel):
    """Email address with optional name."""
    address: EmailStr
    name: Optional[str] = None

    def formatted(self) -> str:
        """Return formatted email string."""
        if self.name:
            return f'"{self.name}" <{self.address}>'
        return self.address


class Attachment(BaseModel):
    """Email attachment."""
    filename: str
    content: bytes
    content_type: str
    content_id: Optional[str] = None  # For inline attachments


class EmailMessage(BaseModel):
    """Email message to send."""
    from_address: EmailAddress
    to_addresses: list[EmailAddress]
    cc_addresses: list[EmailAddress] = []
    bcc_addresses: list[EmailAddress] = []
    reply_to: Optional[EmailAddress] = None

    subject: str
    body_html: Optional[str] = None
    body_text: Optional[str] = None

    attachments: list[Attachment] = []
    headers: dict[str, str] = {}

    # Threading
    in_reply_to: Optional[str] = None
    references: list[str] = []

    # Tracking
    track_opens: bool = True
    track_clicks: bool = True

    # Metadata
    tags: list[str] = []
    metadata: dict = {}

    class Config:
        arbitrary_types_allowed = True


class SendResult(BaseModel):
    """Result of sending an email."""
    success: bool
    message_id: Optional[str] = None
    provider: str
    provider_message_id: Optional[str] = None
    error: Optional[str] = None
    timestamp: datetime = None

    def __init__(self, **data):
        if "timestamp" not in data or data["timestamp"] is None:
            data["timestamp"] = datetime.utcnow()
        super().__init__(**data)


class ProviderConfig(BaseModel):
    """Configuration for an email provider."""
    id: UUID
    name: str
    provider_type: ProviderType
    credentials: dict
    is_default: bool = False
    priority: int = 100
    rate_limit_per_minute: Optional[int] = None
    rate_limit_per_day: Optional[int] = None


class EmailProvider(ABC):
    """Abstract base class for email providers."""

    def __init__(self, config: ProviderConfig):
        self.config = config
        self._credentials = config.credentials

    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """The type of this provider."""
        pass

    @abstractmethod
    async def send(self, message: EmailMessage) -> SendResult:
        """Send an email message.

        Args:
            message: The email message to send

        Returns:
            SendResult with success status and message ID
        """
        pass

    @abstractmethod
    async def verify_credentials(self) -> bool:
        """Verify that credentials are valid.

        Returns:
            True if credentials are valid
        """
        pass

    async def send_batch(self, messages: list[EmailMessage]) -> list[SendResult]:
        """Send multiple emails. Override for batch-optimized providers.

        Args:
            messages: List of messages to send

        Returns:
            List of SendResults
        """
        results = []
        for message in messages:
            result = await self.send(message)
            results.append(result)
        return results

    def _get_credential(self, key: str, required: bool = True) -> Optional[str]:
        """Get a credential value."""
        value = self._credentials.get(key)
        if required and not value:
            raise ValueError(f"Missing required credential: {key}")
        return value

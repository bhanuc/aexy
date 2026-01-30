"""Email provider integrations."""

from mailagent.providers.base import EmailProvider, SendResult, EmailMessage
from mailagent.providers.factory import get_email_provider

__all__ = ["EmailProvider", "SendResult", "EmailMessage", "get_email_provider"]

"""External service integrations."""

from aexy.integrations.mailagent_client import (
    MailagentClient,
    MailagentError,
    get_mailagent_client,
    AgentInfo,
    InvocationResponse,
    AgentActionResponse,
)

__all__ = [
    "MailagentClient",
    "MailagentError",
    "get_mailagent_client",
    "AgentInfo",
    "InvocationResponse",
    "AgentActionResponse",
]

"""Email agents for automated email handling."""

from mailagent.agents.base import (
    EmailAgent,
    AgentType,
    AgentConfig,
    AgentContext,
    AgentDecision,
    AgentAction,
    MessageData,
    ContactData,
)
from mailagent.agents.factory import create_agent, create_agent_from_db, get_agents_for_inbox
from mailagent.agents.support import SupportAgent
from mailagent.agents.sales import SalesAgent
from mailagent.agents.scheduling import SchedulingAgent
from mailagent.agents.onboarding import OnboardingAgent
from mailagent.agents.recruiting import RecruitingAgent
from mailagent.agents.newsletter import NewsletterAgent

__all__ = [
    # Base
    "EmailAgent",
    "AgentType",
    "AgentConfig",
    "AgentContext",
    "AgentDecision",
    "AgentAction",
    "MessageData",
    "ContactData",
    # Factory
    "create_agent",
    "create_agent_from_db",
    "get_agents_for_inbox",
    # Agents
    "SupportAgent",
    "SalesAgent",
    "SchedulingAgent",
    "OnboardingAgent",
    "RecruitingAgent",
    "NewsletterAgent",
]

"""Service layer for mailagent."""

from mailagent.services.admin_service import AdminService
from mailagent.services.domain_service import DomainService
from mailagent.services.onboarding_service import OnboardingService
from mailagent.services.send_service import SendService, get_send_service
from mailagent.services.orchestrator import AgentOrchestrator, get_orchestrator
from mailagent.services.invocation_service import InvocationService, get_invocation_service

__all__ = [
    "AdminService",
    "DomainService",
    "OnboardingService",
    "SendService",
    "get_send_service",
    "AgentOrchestrator",
    "get_orchestrator",
    "InvocationService",
    "get_invocation_service",
]

"""API routers for mailagent service."""

from mailagent.api.admin import router as admin_router
from mailagent.api.domains import router as domains_router
from mailagent.api.onboarding import router as onboarding_router
from mailagent.api.health import router as health_router
from mailagent.api.agents import router as agents_router
from mailagent.api.send import router as send_router
from mailagent.api.webhooks import router as webhooks_router
from mailagent.api.process import router as process_router
from mailagent.api.invocations import router as invocations_router

__all__ = [
    "admin_router",
    "domains_router",
    "onboarding_router",
    "health_router",
    "agents_router",
    "send_router",
    "webhooks_router",
    "process_router",
    "invocations_router",
]

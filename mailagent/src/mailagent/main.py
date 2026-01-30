"""Main application entry point for mailagent service."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from mailagent import __version__
from mailagent.api import (
    admin_router,
    domains_router,
    health_router,
    onboarding_router,
    agents_router,
    send_router,
    webhooks_router,
    process_router,
    invocations_router,
)
from mailagent.config import get_settings
from mailagent.database import engine
from mailagent.models import Base
from mailagent.redis_client import close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    settings = get_settings()

    # Create tables (in production, use migrations)
    if settings.environment == "development":
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    yield

    # Shutdown
    await close_redis()
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Mailagent",
        description="Email administration, onboarding, and domain setup microservice",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Configure appropriately for production
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    app.include_router(health_router)
    app.include_router(admin_router, prefix=settings.api_prefix)
    app.include_router(domains_router, prefix=settings.api_prefix)
    app.include_router(onboarding_router, prefix=settings.api_prefix)
    app.include_router(agents_router, prefix=settings.api_prefix)
    app.include_router(send_router, prefix=settings.api_prefix)
    app.include_router(webhooks_router, prefix=settings.api_prefix)
    app.include_router(process_router, prefix=settings.api_prefix)
    app.include_router(invocations_router, prefix=settings.api_prefix)

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "mailagent.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
    )

"""Pytest configuration and fixtures."""

import asyncio
from collections.abc import AsyncGenerator
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from mailagent.config import Settings
from mailagent.database import get_db
from mailagent.main import app
from mailagent.models import Base


# Test database URL (use SQLite for tests)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def test_settings() -> Settings:
    """Get test settings."""
    return Settings(
        database_url=TEST_DATABASE_URL,
        redis_url="redis://localhost:6379/1",
        debug=True,
        environment="test",
    )


@pytest_asyncio.fixture
async def test_engine():
    """Create test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session_factory = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with async_session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def client(test_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Create test HTTP client."""

    async def override_get_db():
        yield test_session

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client

    app.dependency_overrides.clear()


# Factory fixtures for creating test data
@pytest.fixture
def provider_factory():
    """Factory for creating test provider data."""

    def _create(
        name: str | None = None,
        provider_type: str = "ses",
        **kwargs,
    ) -> dict:
        return {
            "name": name or f"Test Provider {uuid4().hex[:8]}",
            "provider_type": provider_type,
            "credentials": {
                "api_key": "test-api-key",
                "region": "us-east-1",
            },
            "is_default": False,
            "priority": 100,
            **kwargs,
        }

    return _create


@pytest.fixture
def domain_factory():
    """Factory for creating test domain data."""

    def _create(domain: str | None = None, **kwargs) -> dict:
        return {
            "domain": domain or f"test-{uuid4().hex[:8]}.com",
            "warming_schedule": "moderate",
            **kwargs,
        }

    return _create


@pytest.fixture
def inbox_factory():
    """Factory for creating test inbox data."""

    def _create(email: str | None = None, **kwargs) -> dict:
        random_id = uuid4().hex[:8]
        return {
            "email": email or f"test-{random_id}@example.com",
            "display_name": f"Test User {random_id}",
            **kwargs,
        }

    return _create

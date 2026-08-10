"""Pytest scaffolding for the AI test suite.

The suite at `tests/ai/` is the integration tier that exercises every
AI surface (provider, gateway, service, agent, API) against a real LLM.
By convention we use LM Studio at `http://localhost:1234` so tests run
locally without spending cloud-LLM budget.

Marker:
    @pytest.mark.local_llm
        Test requires LM Studio to be running. Auto-skipped (with a
        clear reason) if the probe fails. Use `pytest -m local_llm`
        to run only these tests, or `pytest -m "not local_llm"` to
        keep CI fast.

Key fixtures:
    lmstudio_config       — `LLMConfig` pointed at the local server
    lmstudio_provider     — bare `LMStudioProvider`
    lmstudio_gateway      — `LLMGateway` wrapping the provider (no cache,
                            no rate limiter), suitable as a drop-in for
                            services that call `gateway.analyze(...)`
    lmstudio_native       — `LMStudioNativeClient` for tests that want
                            the native `/api/v1/chat` endpoint
    recorder              — per-test prompt/completion JSONL recorder
    ai_db_session         — in-memory SQLite session (separate from the
                            top-level `db_session` so we don't fight the
                            session-scoped event loop)
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Generator

import httpx
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from aexy.core.database import Base
from aexy.llm.base import LLMConfig
from aexy.llm.gateway import LLMGateway
from aexy.llm.lmstudio_provider import LMStudioProvider

from tests.ai.utils.lmstudio_native import LMStudioNativeClient
from tests.ai.utils.prompt_recorder import PromptRecorder


LMSTUDIO_BASE = os.environ.get("LMSTUDIO_BASE_URL", "http://localhost:1234/v1")
LMSTUDIO_NATIVE_BASE = LMSTUDIO_BASE.rsplit("/v1", 1)[0]
LMSTUDIO_MODEL = os.environ.get("LMSTUDIO_MODEL", "qwen/qwen3.5-9b")
LMSTUDIO_PROBE_TIMEOUT = float(os.environ.get("LMSTUDIO_PROBE_TIMEOUT", "3.0"))


# ─── Marker registration & skip logic ──────────────────────────────────


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "local_llm: requires LM Studio running at LMSTUDIO_BASE_URL "
        "(default http://localhost:1234/v1). Auto-skipped if unreachable.",
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Refresh golden JSON outputs in tests/ai/goldens/.",
    )
    parser.addoption(
        "--ai-verbose",
        action="store_true",
        default=False,
        help="Print per-test recorder summary at the end of each AI test.",
    )


def _lmstudio_alive() -> tuple[bool, str]:
    """Cheap probe: GET /v1/models (OpenAI-compat). Returns (ok, message).

    We probe the same surface the provider uses (`/v1`), not the native
    `/api/v1`, so a probe-pass really means provider calls will pass.
    """
    url = f"{LMSTUDIO_BASE.rstrip('/')}/models"
    try:
        with httpx.Client(timeout=LMSTUDIO_PROBE_TIMEOUT) as c:
            r = c.get(url)
            if r.status_code != 200:
                return False, f"LM Studio returned HTTP {r.status_code} from {url}"
            data = r.json().get("data", [])
            ids = {m.get("id") for m in data}
            if LMSTUDIO_MODEL not in ids:
                return False, (
                    f"Model {LMSTUDIO_MODEL!r} not present in {sorted(ids)!r}. "
                    f"Load it in LM Studio or set LMSTUDIO_MODEL."
                )
            return True, ""
    except Exception as e:
        return False, f"LM Studio probe failed at {url}: {e}"


_PROBE_RESULT: tuple[bool, str] | None = None


def _cached_probe() -> tuple[bool, str]:
    global _PROBE_RESULT
    if _PROBE_RESULT is None:
        _PROBE_RESULT = _lmstudio_alive()
    return _PROBE_RESULT


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Auto-skip `local_llm` tests when LM Studio is unreachable."""
    if not any("local_llm" in item.keywords for item in items):
        return
    ok, reason = _cached_probe()
    if ok:
        return
    skip = pytest.mark.skip(reason=f"local_llm unavailable: {reason}")
    for item in items:
        if "local_llm" in item.keywords:
            item.add_marker(skip)


# ─── Event loop & DB ───────────────────────────────────────────────────


# @pytest.fixture(scope="session")
# def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
#     loop = asyncio.new_event_loop()
#     yield loop
#     loop.close()


@pytest_asyncio.fixture(scope="function")
async def ai_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Fresh in-memory SQLite session per test."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ─── LM Studio fixtures ────────────────────────────────────────────────


@pytest.fixture
def lmstudio_config() -> LLMConfig:
    return LLMConfig(
        provider="lmstudio",
        model=LMSTUDIO_MODEL,
        api_key=os.environ.get("LMSTUDIO_API_KEY", ""),
        base_url=LMSTUDIO_BASE,
        # Qwen "thinking" models burn through the budget on chain-of-thought
        # before producing the requested JSON; 8192 leaves headroom even
        # when /no_think isn't fully suppressing the reasoning trace.
        max_tokens=8192,
        temperature=0.0,
        timeout=180,
    )


@pytest_asyncio.fixture
async def lmstudio_provider(lmstudio_config: LLMConfig) -> AsyncGenerator[LMStudioProvider, None]:
    provider = LMStudioProvider(lmstudio_config)
    try:
        yield provider
    finally:
        await provider.close()


@pytest_asyncio.fixture
async def lmstudio_gateway(
    lmstudio_provider: LMStudioProvider,
) -> AsyncGenerator[LLMGateway, None]:
    """Gateway with no cache and no rate limiter — wraps the local provider."""

    class _NoopRateLimiter:
        """In-memory stub matching the LLMRateLimiter surface that the
        gateway actually calls. Avoids needing Redis in the test env."""

        async def check_rate_limit(self, provider, *, tokens_estimate, workspace_id, developer_id):
            from aexy.services.llm_rate_limiter import RateLimitResult
            return RateLimitResult(allowed=True, reason=None, retry_after=None, wait_seconds=0.0)

        async def record_request(self, provider, *, tokens_used, workspace_id, developer_id):
            return None

        async def get_status(self, provider, *, workspace_id, developer_id):
            from datetime import datetime, timezone
            from aexy.services.llm_rate_limiter import RateLimitStatus
            now = datetime.now(timezone.utc)
            return RateLimitStatus(
                provider=provider,
                is_limited=False,
                requests_remaining_minute=-1,
                requests_remaining_day=-1,
                tokens_remaining_minute=-1,
                reset_at_minute=now,
                reset_at_day=now,
                wait_seconds=0.0,
                workspace_id=workspace_id,
                developer_id=developer_id,
                source="noop",
            )

    gateway = LLMGateway(
        provider=lmstudio_provider,
        cache=None,
        rate_limiter=_NoopRateLimiter(),
    )
    yield gateway


@pytest_asyncio.fixture
async def lmstudio_native() -> AsyncGenerator[LMStudioNativeClient, None]:
    """Native LM Studio client — only used by tests that need MCP /
    reasoning="off" / stateful chats. Most tests should use
    `lmstudio_gateway` instead."""
    client = LMStudioNativeClient(base_url=LMSTUDIO_NATIVE_BASE)
    try:
        yield client
    finally:
        await client.close()


# ─── Recorder & verbose output ─────────────────────────────────────────


@pytest.fixture
def recorder(request: pytest.FixtureRequest) -> PromptRecorder:
    """Per-test prompt/completion recorder.

    The recorder is always created so tests can use `recorder.record(...)`
    explicitly. When the gateway is in use, `recording_gateway` wraps the
    gateway's _log_prompt to feed this recorder automatically.
    """
    return PromptRecorder(request.node.nodeid, enabled=True)


@pytest.fixture
def recording_gateway(
    lmstudio_gateway: LLMGateway, recorder: PromptRecorder, monkeypatch: pytest.MonkeyPatch
) -> LLMGateway:
    """Wrap the gateway's _log_prompt so every prompt/completion lands in
    the recorder's JSONL file. Yields the same gateway instance."""
    original = lmstudio_gateway._log_prompt

    async def _spy(*args, **kwargs):
        recorder.record(
            operation=kwargs.get("operation", "?"),
            provider=kwargs.get("provider", lmstudio_gateway.provider_name),
            model=kwargs.get("model", lmstudio_gateway.model_name),
            system_prompt=kwargs.get("system_prompt"),
            user_prompt=kwargs.get("user_prompt", ""),
            completion=kwargs.get("completion", ""),
            input_tokens=kwargs.get("input_tokens", 0),
            output_tokens=kwargs.get("output_tokens", 0),
            extra={
                "analysis_type": kwargs.get("analysis_type"),
                "confidence": kwargs.get("confidence"),
            },
        )
        # Skip the DB-write side of the original because we don't pass a
        # real session into the gateway in tests.
        if kwargs.get("db") is not None:
            return await original(*args, **kwargs)
        return None

    monkeypatch.setattr(lmstudio_gateway, "_log_prompt", _spy)
    return lmstudio_gateway


def pytest_terminal_summary(terminalreporter, exitstatus, config) -> None:
    """At end of session, print where the .logs live so devs can grep them."""
    if not config.getoption("--ai-verbose", default=False):
        return
    from tests.ai.utils.prompt_recorder import LOGS_DIR
    if LOGS_DIR.exists():
        terminalreporter.write_sep("-", "ai test recorder logs")
        terminalreporter.write_line(f"Per-test JSONL transcripts: {LOGS_DIR}")

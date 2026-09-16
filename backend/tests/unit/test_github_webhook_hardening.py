"""The GitHub webhook endpoint refuses what it cannot vouch for.

Three holes this pins shut, each of which made the endpoint usable by someone
who is not GitHub:

- an unset secret used to be tolerated under `debug`, which turned a config
  error into an open ingestion endpoint — and the payloads it accepts reach
  task linking, task status transitions and LLM analysis dispatch;
- `X-Forwarded-For` was trusted from any caller, so rotating the header gave
  an attacker a fresh per-IP rate-limit bucket per request;
- a signed body could be replayed for as long as the secret lived, because
  the delivery id was echoed but never remembered.
"""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient

from aexy.api import webhooks as webhooks_api

SECRET = "s3kret"
BODY = {"zen": "Design for failure.", "hook_id": 1}


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _raw(payload: dict | None = None) -> bytes:
    return json.dumps(payload or BODY).encode()


@pytest.fixture
def secret_set(monkeypatch):
    """A configured secret, and debug on — so debug earns nothing."""
    monkeypatch.setattr(webhooks_api.settings, "github_webhook_secret", SECRET)
    monkeypatch.setattr(webhooks_api.settings, "debug", True)


@pytest.fixture(autouse=True)
def no_redis(monkeypatch):
    """Keep rate limiting and replay lookups out of these assertions."""
    async def _never_seen(delivery_id: str) -> bool:
        return False

    async def _noop(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(webhooks_api, "_delivery_already_applied", _never_seen)
    monkeypatch.setattr(webhooks_api, "_mark_delivery_applied", _noop)
    monkeypatch.setattr(webhooks_api, "_enforce_webhook_rate_limit", _noop)


@pytest.mark.asyncio
async def test_unset_secret_refuses_even_in_debug(
    client: AsyncClient, monkeypatch
):
    """The debug bypass is gone: no secret means no ingestion, anywhere."""
    monkeypatch.setattr(webhooks_api.settings, "github_webhook_secret", "")
    monkeypatch.setattr(webhooks_api.settings, "debug", True)

    response = await client.post(
        "/api/v1/webhooks/github",
        content=_raw(),
        headers={"X-GitHub-Event": "ping", "Content-Type": "application/json"},
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


@pytest.mark.asyncio
async def test_missing_signature_is_rejected(client: AsyncClient, secret_set):
    response = await client.post(
        "/api/v1/webhooks/github",
        content=_raw(),
        headers={"X-GitHub-Event": "ping", "Content-Type": "application/json"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_signature_over_a_different_body_is_rejected(
    client: AsyncClient, secret_set
):
    """Signature must cover *this* body, not merely be well-formed."""
    response = await client.post(
        "/api/v1/webhooks/github",
        content=_raw({"zen": "tampered"}),
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(_raw()),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_wrong_secret_is_rejected(client: AsyncClient, secret_set):
    body = _raw()
    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(body, "not-the-secret"),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_correctly_signed_delivery_gets_through(
    client: AsyncClient, secret_set
):
    """`ping` is unsupported, so reaching "ignored" means auth passed."""
    body = _raw()
    response = await client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "X-GitHub-Event": "ping",
            "X-Hub-Signature-256": _sign(body),
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_replayed_delivery_is_dropped(
    client: AsyncClient, secret_set, monkeypatch
):
    """A valid signature does not license unlimited resends of one delivery."""
    async def _already_seen(delivery_id: str) -> bool:
        return delivery_id == "seen-once"

    monkeypatch.setattr(webhooks_api, "_delivery_already_applied", _already_seen)

    body = _raw()
    headers = {
        "X-GitHub-Event": "ping",
        "X-Hub-Signature-256": _sign(body),
        "X-GitHub-Delivery": "seen-once",
        "Content-Type": "application/json",
    }
    response = await client.post(
        "/api/v1/webhooks/github", content=body, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "duplicate"


@pytest.mark.asyncio
async def test_replay_check_runs_after_signature_check(
    client: AsyncClient, secret_set, monkeypatch
):
    """An unsigned caller must not be able to probe which ids we have seen."""
    probed: list[str] = []

    async def _record(delivery_id: str) -> bool:
        probed.append(delivery_id)
        return False

    monkeypatch.setattr(webhooks_api, "_delivery_already_applied", _record)

    response = await client.post(
        "/api/v1/webhooks/github",
        content=_raw(),
        headers={
            "X-GitHub-Event": "ping",
            "X-GitHub-Delivery": "probe-me",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 401
    assert probed == [], "delivery id was looked up before the signature passed"

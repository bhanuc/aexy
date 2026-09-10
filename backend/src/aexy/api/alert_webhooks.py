"""Alert integration API: inbound webhook + management endpoints.

Two routers:
  * ``webhook_router`` — public ``POST /webhooks/alerts/{inbound_token}``.
    Verifies + persists + dispatches to Temporal, then ACKs fast.
  * ``router`` — authenticated ``/workspaces/{ws}/alert-integrations`` CRUD,
    event log, and a synchronous "send test alert" endpoint.
"""

import hashlib
import hmac
import json
import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.api.developers import get_current_developer
from aexy.api.webhooks import _enforce_webhook_rate_limit
from aexy.core.config import get_settings
from aexy.core.database import get_db
from aexy.models.alerting import AlertEvent
from aexy.models.developer import Developer
from aexy.schemas.alerting import (
    AlertEventListResponse,
    AlertEventResponse,
    AlertIntegrationCreate,
    AlertIntegrationResponse,
    AlertIntegrationSecretResponse,
    AlertIntegrationUpdate,
    TestAlertResponse,
)
from aexy.services.alert_ingestion_service import AlertIngestionService
from aexy.services.alert_integration_service import AlertIntegrationService
from aexy.services.workspace_service import WorkspaceService

logger = logging.getLogger(__name__)
settings = get_settings()

_ALERT_WEBHOOK_LIMIT_PER_INTEGRATION_PER_MIN = 120

router = APIRouter(prefix="/workspaces/{workspace_id}/alert-integrations", tags=["Alert Integrations"])
webhook_router = APIRouter(prefix="/webhooks/alerts", tags=["Alert Webhooks"])


# =============================================================================
# Helpers
# =============================================================================

def _verify_signature(secret: str | None, signature_header: str | None, body: bytes) -> bool:
    """Accept either an HMAC-SHA256 hex digest of the body or the raw secret.

    OpenObserve deployments vary: some can compute an HMAC, others can only
    send a fixed header value. Both are compared in constant time.
    """
    if not secret:
        return False
    if not signature_header:
        return False
    sig = signature_header.strip()
    # Strip an optional "sha256=" prefix (GitHub-style).
    if sig.lower().startswith("sha256="):
        sig = sig[7:]
    expected_hmac = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    if hmac.compare_digest(sig, expected_hmac):
        return True
    return hmac.compare_digest(sig, secret)


def _webhook_url(inbound_token: str) -> str:
    return f"{settings.backend_url.rstrip('/')}/api/v1/webhooks/alerts/{inbound_token}"


def _to_response(integration) -> AlertIntegrationResponse:
    return AlertIntegrationResponse(
        id=str(integration.id),
        workspace_id=str(integration.workspace_id),
        provider=integration.provider,
        name=integration.name,
        base_url=integration.base_url,
        default_form_id=str(integration.default_form_id) if integration.default_form_id else None,
        routing_rules=integration.routing_rules or [],
        fingerprint_template=integration.fingerprint_template,
        dedup_window_minutes=integration.dedup_window_minutes,
        comment_throttle_minutes=integration.comment_throttle_minutes,
        auto_resolve=integration.auto_resolve,
        enabled=integration.enabled,
        webhook_url=_webhook_url(integration.inbound_token),
        created_at=integration.created_at,
        updated_at=integration.updated_at,
    )


async def _verify_access(
    workspace_id: str, current_user: Developer, db: AsyncSession, required_role: str = "viewer"
) -> None:
    ws = WorkspaceService(db)
    if not await ws.check_permission(workspace_id, str(current_user.id), required_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{required_role.capitalize()} permission required",
        )


# =============================================================================
# Inbound webhook (public)
# =============================================================================

@webhook_router.post("/{inbound_token}")
async def receive_alert(
    inbound_token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_aexy_signature: str | None = Header(None),
) -> dict:
    """Receive an alert from an observability platform and enqueue processing."""
    service = AlertIntegrationService(db)
    integration = await service.get_by_token(inbound_token)
    if integration is None or not integration.enabled:
        # Unknown/disabled token — don't reveal which.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown alert endpoint")

    await _enforce_webhook_rate_limit(
        f"webhook:alerts:{integration.id}",
        _ALERT_WEBHOOK_LIMIT_PER_INTEGRATION_PER_MIN,
    )

    body = await request.body()
    secret = AlertIntegrationService.signing_secret_plaintext(integration)
    if not _verify_signature(secret, x_aexy_signature, body):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    try:
        payload = json.loads(body) if body else {}
        if not isinstance(payload, dict):
            payload = {"_raw": payload}
    except (json.JSONDecodeError, ValueError):
        # Never 5xx a malformed body — that would make the sender retry in a
        # loop. Record it as a dropped event instead.
        payload = {"_unparseable": body.decode("utf-8", errors="replace")[:4000]}

    event = AlertEvent(
        id=str(uuid4()),
        integration_id=integration.id,
        workspace_id=integration.workspace_id,
        raw_payload=payload,
    )
    db.add(event)
    await db.flush()

    from aexy.temporal.dispatch import dispatch
    from aexy.temporal.task_queues import TaskQueue
    from aexy.temporal.activities.alerting import ProcessAlertEventInput

    await dispatch(
        "process_alert_event",
        ProcessAlertEventInput(event_id=event.id),
        task_queue=TaskQueue.OPERATIONS,
        workflow_id=f"alert-event-{event.id}",
    )
    return {"status": "accepted", "event_id": event.id}


# =============================================================================
# Management (authenticated)
# =============================================================================

@router.post("", response_model=AlertIntegrationSecretResponse, status_code=201)
async def create_integration(
    workspace_id: str,
    data: AlertIntegrationCreate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> AlertIntegrationSecretResponse:
    await _verify_access(workspace_id, current_user, db, "admin")
    service = AlertIntegrationService(db)
    integration, secret = await service.create(workspace_id, data)
    base = _to_response(integration)
    return AlertIntegrationSecretResponse(**base.model_dump(), signing_secret=secret)


@router.get("", response_model=list[AlertIntegrationResponse])
async def list_integrations(
    workspace_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> list[AlertIntegrationResponse]:
    await _verify_access(workspace_id, current_user, db)
    integrations = await AlertIntegrationService(db).list_integrations(workspace_id)
    return [_to_response(i) for i in integrations]


@router.get("/events", response_model=AlertEventListResponse)
async def list_workspace_events(
    workspace_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    action: list[str] | None = Query(default=None),
    fingerprint: str | None = Query(default=None),
    unresolved_only: bool = Query(default=False),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> AlertEventListResponse:
    """Every integration's alert history, newest first.

    Declared before ``/{integration_id}/events`` so the literal path wins:
    FastAPI matches in declaration order, and a route parameter would otherwise
    swallow "events" as an integration id.

    Read-only, so ``_verify_access`` at its default "viewer" level — a developer
    debugging a noisy alert should not need permission to reconfigure the
    integration.
    """
    await _verify_access(workspace_id, current_user, db)
    events, total = await AlertIntegrationService(db).list_events(
        workspace_id,
        None,
        limit=limit,
        offset=offset,
        actions=action,
        fingerprint=fingerprint,
        unresolved_only=unresolved_only,
    )
    return AlertEventListResponse(
        events=[AlertEventResponse.model_validate(e) for e in events],
        total=total,
    )


@router.get("/{integration_id}", response_model=AlertIntegrationResponse)
async def get_integration(
    workspace_id: str,
    integration_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> AlertIntegrationResponse:
    await _verify_access(workspace_id, current_user, db)
    integration = await AlertIntegrationService(db).get(workspace_id, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    return _to_response(integration)


@router.patch("/{integration_id}", response_model=AlertIntegrationResponse)
async def update_integration(
    workspace_id: str,
    integration_id: str,
    data: AlertIntegrationUpdate,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> AlertIntegrationResponse:
    await _verify_access(workspace_id, current_user, db, "admin")
    service = AlertIntegrationService(db)
    integration = await service.get(workspace_id, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    integration = await service.update(integration, data)
    return _to_response(integration)


@router.post("/{integration_id}/rotate-secret", response_model=AlertIntegrationSecretResponse)
async def rotate_secret(
    workspace_id: str,
    integration_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> AlertIntegrationSecretResponse:
    await _verify_access(workspace_id, current_user, db, "admin")
    service = AlertIntegrationService(db)
    integration = await service.get(workspace_id, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    secret = await service.rotate_secret(integration)
    base = _to_response(integration)
    return AlertIntegrationSecretResponse(**base.model_dump(), signing_secret=secret)


@router.delete("/{integration_id}", status_code=204)
async def delete_integration(
    workspace_id: str,
    integration_id: str,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> None:
    await _verify_access(workspace_id, current_user, db, "admin")
    service = AlertIntegrationService(db)
    integration = await service.get(workspace_id, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")
    await service.delete(integration)


@router.get("/{integration_id}/events", response_model=AlertEventListResponse)
async def list_events(
    workspace_id: str,
    integration_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    action: list[str] | None = Query(default=None),
    fingerprint: str | None = Query(default=None),
    unresolved_only: bool = Query(default=False),
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> AlertEventListResponse:
    await _verify_access(workspace_id, current_user, db)
    events, total = await AlertIntegrationService(db).list_events(
        workspace_id,
        integration_id,
        limit=limit,
        offset=offset,
        actions=action,
        fingerprint=fingerprint,
        unresolved_only=unresolved_only,
    )
    return AlertEventListResponse(
        events=[AlertEventResponse.model_validate(e) for e in events],
        total=total,
    )


@router.post("/{integration_id}/test", response_model=TestAlertResponse)
async def send_test_alert(
    workspace_id: str,
    integration_id: str,
    payload: dict,
    current_user: Developer = Depends(get_current_developer),
    db: AsyncSession = Depends(get_db),
) -> TestAlertResponse:
    """Run a sample payload through the full pipeline synchronously (for setup).

    Creates a real ticket so operators can see the end result, but skips firing
    ``alert.ticket_*`` automations — a setup test shouldn't page on-call or
    trigger escalation rules.
    """
    await _verify_access(workspace_id, current_user, db, "admin")
    service = AlertIntegrationService(db)
    integration = await service.get(workspace_id, integration_id)
    if integration is None:
        raise HTTPException(status_code=404, detail="Integration not found")

    event = AlertEvent(
        id=str(uuid4()),
        integration_id=integration.id,
        workspace_id=workspace_id,
        raw_payload=payload if isinstance(payload, dict) else {"_raw": payload},
    )
    db.add(event)
    await db.flush()
    event = await AlertIngestionService(db).process_event(event, dispatch_automations=False)
    return TestAlertResponse(
        action_taken=event.action_taken,
        ticket_id=event.ticket_id,
        fingerprint=event.fingerprint,
        error_message=event.error_message,
    )

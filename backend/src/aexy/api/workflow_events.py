"""Workflow events API for receiving external events and webhooks."""

import hashlib
import hmac
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Request, Header
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.core.config import get_settings
from aexy.api.access_guard import require_workspace_member
from aexy.api.developers import get_current_developer
from aexy.models.developer import Developer
from aexy.services.workflow_event_service import WorkflowEventService

logger = logging.getLogger(__name__)
settings = get_settings()

# =============================================================================
# WEBHOOK AUTHENTICATION
# =============================================================================
#
# The receivers below are called by outside systems — a form tool, a calendar,
# an email provider — so they cannot carry a user's bearer token. Until this
# guard they carried nothing: anyone who knew a workspace id could post
# "form submitted" or "meeting booked" events into it and resume that
# workspace's waiting workflows with made-up data.
#
# Each workspace has a secret derived from the server key — no migration, no
# state to lose — and a sender proves it holds that secret in one of two ways:
#
# * **A signature over the body**, `X-Aexy-Signature: sha256=<hex>`. This is
#   what `api/webhooks.py` does for the CRM automation triggers, and it is the
#   better of the two: the secret itself never travels, so a captured request
#   cannot be replayed against a different payload.
# * **The secret in a header**, for senders that can set a header but cannot
#   compute an HMAC. The secret does travel, so it is only as private as the
#   channel — which is why it is never accepted in the query string, where it
#   would be written to every proxy and CDN access log along the way.
#
# One caveat worth stating plainly: because the secret is derived from
# `settings.secret_key`, a workspace's secret cannot be rotated on its own.
# Rotating it means rotating the server key, which invalidates every session.
# Giving workspaces their own rotatable secret needs a column and a migration;
# until then, treat a leaked secret as a reason to rotate `SECRET_KEY`.

WEBHOOK_SECRET_HEADER = "X-Aexy-Webhook-Secret"
WEBHOOK_SIGNATURE_HEADER = "X-Aexy-Signature"

#: Per-workspace ceiling. A secret that does leak should not be able to fan
#: out Temporal workflows without bound; the same reasoning as WS-082 on the
#: CRM automation trigger.
WEBHOOK_LIMIT_PER_WORKSPACE_PER_MIN = 120


def _payload(body: Any) -> dict[str, Any]:
    """A webhook body as an object, or ``{}`` if it is anything else.

    Senders disagree about shape, and the disagreement reaches further than
    the top level: one sends ``{"event": {"uuid": …}}``, another sends
    ``{"event": "booked"}``, and SendGrid sends a whole JSON *array*. Reading
    ``.get()`` off any of those is an AttributeError — a 500 on a request the
    sender will then retry forever.
    """
    return body if isinstance(body, dict) else {}


def _nested(payload: Any, key: str) -> dict[str, Any]:
    """A nested object from a webhook body, or ``{}`` if it is anything else."""
    value = _payload(payload).get(key)
    return value if isinstance(value, dict) else {}


def _events(body: Any) -> list[dict[str, Any]]:
    """The event objects in a body that may hold one or many.

    SendGrid's event webhook posts a batch — a JSON array of event objects —
    and so do several of the others under load. A single object is the
    one-element case of the same thing.
    """
    if isinstance(body, list):
        return [item for item in body if isinstance(item, dict)]
    return [_payload(body)]


def derive_workflow_webhook_secret(workspace_id: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"workflow-events:{workspace_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _secret_matches(presented: str | None, expected: str) -> bool:
    """Constant-time compare of two hex secrets.

    Encoded first: `compare_digest` refuses two `str` arguments when either
    holds a non-ASCII character, and the presented value comes from a header
    an attacker writes. Left as `str` it raises TypeError, which is a 500 and
    a stack trace on every probe instead of the 401 this is here to return.
    """
    if not presented:
        return False
    return hmac.compare_digest(presented.encode("utf-8", "ignore"), expected.encode("utf-8"))


def _signature_matches(signature_header: str | None, expected_secret: str, body: bytes) -> bool:
    """Verify `X-Aexy-Signature: sha256=<hex>` over the raw body."""
    if not signature_header:
        return False
    # Both `sha256=<hex>` and a bare `<hex>`, as the CRM trigger accepts.
    presented = (
        signature_header.split("=", 1)[1] if "=" in signature_header else signature_header
    )
    expected = hmac.new(
        expected_secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return _secret_matches(presented, expected)


async def verify_webhook_secret(
    workspace_id: str,
    request: Request,
    presented_header: str | None = Header(default=None, alias=WEBHOOK_SECRET_HEADER),
    signature_header: str | None = Header(default=None, alias=WEBHOOK_SIGNATURE_HEADER),
) -> None:
    # Reused rather than reimplemented: the CRM triggers already have this
    # exact ceiling. Imported inside the function because `api.webhooks` pulls
    # in a good deal of the app at module scope.
    from aexy.api.webhooks import _enforce_webhook_rate_limit

    await _enforce_webhook_rate_limit(
        f"webhook:workflow-events:{workspace_id}",
        WEBHOOK_LIMIT_PER_WORKSPACE_PER_MIN,
    )

    expected = derive_workflow_webhook_secret(workspace_id)
    # Starlette caches the body, so reading it here does not stop the endpoint
    # from parsing it again.
    body = await request.body()
    if _signature_matches(signature_header, expected, body):
        return
    if _secret_matches(presented_header, expected):
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=(
            "Missing or invalid webhook credentials. Sign the request body with "
            f"the workspace's webhook secret and send the result in the "
            f"{WEBHOOK_SIGNATURE_HEADER} header, or present the secret itself in "
            f"the {WEBHOOK_SECRET_HEADER} header. Both are shown with the "
            "webhook URLs."
        ),
    )


router = APIRouter(prefix="/workspaces/{workspace_id}/workflow-events")


# =============================================================================
# SCHEMAS
# =============================================================================


class WorkflowEventRequest(BaseModel):
    """Request to trigger a workflow event."""

    event_type: str = Field(..., description="Type of event (e.g., email.opened)")
    event_data: dict[str, Any] = Field(
        default_factory=dict, description="Event payload data"
    )
    record_id: str | None = Field(None, description="Optional record ID")


class WorkflowEventResponse(BaseModel):
    """Response from triggering an event."""

    success: bool
    message: str
    resumed_executions: list[str] = Field(default_factory=list)


class SupportedEventType(BaseModel):
    """Supported event type info."""

    type: str
    label: str
    description: str
    filter_fields: list[str]


# =============================================================================
# WEBHOOK ENDPOINTS (External Event Receivers)
# =============================================================================


@router.post("/webhooks/email-tracking", response_model=WorkflowEventResponse)
async def receive_email_tracking_event(
    workspace_id: str,
    request: Request,
    _: None = Depends(verify_webhook_secret),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive email tracking events (opens, clicks, replies, bounces).
    Used by email tracking services like SendGrid, Mailgun, etc.

    SendGrid posts a *batch* — a JSON array of event objects — so the body is
    read as a list of events of which one object is the single-element case.
    Read as a dict it raised AttributeError on every SendGrid delivery, and a
    500 is the one answer that makes a sender retry forever.
    """
    events = _events(await request.json())

    # Map common email event payloads
    event_type_map = {
        "open": "email.opened",
        "opened": "email.opened",
        "click": "email.clicked",
        "clicked": "email.clicked",
        "reply": "email.replied",
        "replied": "email.replied",
        "bounce": "email.bounced",
        "bounced": "email.bounced",
        "delivered": "email.delivered",
    }

    handled: list[str] = []
    resumed: list[str] = []
    service = WorkflowEventService(db)

    for event in events:
        raw_type = event.get("event") or event.get("type")
        if not raw_type:
            continue
        # `str()` first: a sender that puts a number here would otherwise take
        # the whole batch down on `.lower()`.
        raw_type = str(raw_type)
        normalized_type = event_type_map.get(raw_type.lower(), f"email.{raw_type}")

        event_data = {
            "email_id": event.get("email_id") or event.get("message_id") or event.get("sg_message_id"),
            # `_nested`, not `.get("metadata", {})`: the default only applies
            # to a *missing* key, so an explicit `"metadata": null` still
            # raised.
            "record_id": event.get("record_id") or _nested(event, "metadata").get("record_id"),
            "recipient_email": event.get("email") or event.get("recipient"),
            "timestamp": event.get("timestamp") or datetime.now(timezone.utc).isoformat(),
            "raw_event": event,
        }

        # Handle click-specific data
        if "url" in event or "link" in event:
            event_data["link_url"] = event.get("url") or event.get("link")

        resumed.extend(await service.handle_event(workspace_id, normalized_type, event_data))
        handled.append(normalized_type)

    if not handled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing event type in payload",
        )

    return WorkflowEventResponse(
        success=True,
        message=f"Processed {len(handled)} event(s): {', '.join(sorted(set(handled)))}",
        resumed_executions=resumed,
    )


@router.post("/webhooks/form-submission", response_model=WorkflowEventResponse)
async def receive_form_submission(
    workspace_id: str,
    request: Request,
    _: None = Depends(verify_webhook_secret),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive form submission events.
    Used by form services like Typeform, JotForm, etc.
    """
    # `_payload`, not the raw parse: a body that arrives as an array or a bare
    # string reads as empty here instead of raising AttributeError, and
    # `_nested` covers `"hidden": null` — a present-but-null key, which
    # `.get("hidden", {})` does not.
    body = _payload(await request.json())

    event_data = {
        "form_id": body.get("form_id") or body.get("formId"),
        "record_id": body.get("record_id") or _nested(body, "hidden").get("record_id"),
        "submission_id": body.get("submission_id") or body.get("response_id"),
        "submitted_at": body.get("submitted_at") or datetime.now(timezone.utc).isoformat(),
        "answers": body.get("answers") or body.get("responses") or body.get("data"),
        "raw_event": body,
    }

    service = WorkflowEventService(db)
    resumed = await service.handle_event(workspace_id, "form.submitted", event_data)

    return WorkflowEventResponse(
        success=True,
        message="Processed form.submitted event",
        resumed_executions=resumed,
    )


@router.post("/webhooks/meeting", response_model=WorkflowEventResponse)
async def receive_meeting_event(
    workspace_id: str,
    request: Request,
    _: None = Depends(verify_webhook_secret),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive meeting events from calendar integrations.
    Used by Calendly, Cal.com, Google Calendar, etc.
    """
    body = _payload(await request.json())

    # Determine event type. Only a string names the event: Calendly puts an
    # *object* in `event` (the booking itself) and the name in `payload`, and
    # `{...}.lower()` was an AttributeError — a 500 on a webhook Calendly then
    # retries.
    event_type = next(
        (
            value
            for value in (body.get("event"), body.get("type"))
            if isinstance(value, str) and value
        ),
        "scheduled",
    )
    event_type_map = {
        "invitee.created": "meeting.scheduled",
        "scheduled": "meeting.scheduled",
        "booked": "meeting.scheduled",
        "invitee.canceled": "meeting.cancelled",
        "cancelled": "meeting.cancelled",
        "canceled": "meeting.cancelled",
        "completed": "meeting.completed",
        "ended": "meeting.completed",
    }
    normalized_type = event_type_map.get(event_type.lower(), f"meeting.{event_type}")

    # Extract meeting data. Every nested lookup goes through `_nested`: the
    # same key can arrive as an object from one sender and a string from
    # another — Calendly sends `event` as an object, others send the event
    # *name* there — and `"booked".get(...)` is an AttributeError, which
    # surfaced as a 500 on a webhook the sender then retries forever.
    payload = _nested(body, "payload") or body
    invitee = _nested(payload, "invitee")
    event_block = _nested(payload, "event")
    event_type_block = _nested(payload, "event_type")

    event_data = {
        "meeting_id": event_block.get("uuid") or payload.get("meeting_id"),
        "calendar_id": event_type_block.get("uuid") or payload.get("calendar_id"),
        "record_id": (
            _nested(payload, "tracking").get("record_id")
            or invitee.get("record_id")
            or body.get("record_id")
        ),
        "meeting_type": event_type_block.get("name"),
        "scheduled_at": event_block.get("start_time"),
        "invitee_email": invitee.get("email"),
        "invitee_name": invitee.get("name"),
        "raw_event": body,
    }

    service = WorkflowEventService(db)
    resumed = await service.handle_event(workspace_id, normalized_type, event_data)

    return WorkflowEventResponse(
        success=True,
        message=f"Processed {normalized_type} event",
        resumed_executions=resumed,
    )


@router.post("/webhooks/custom/{webhook_id}", response_model=WorkflowEventResponse)
async def receive_custom_webhook(
    workspace_id: str,
    webhook_id: str,
    request: Request,
    _: None = Depends(verify_webhook_secret),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive custom webhook events.
    Generic endpoint for any external system.
    """
    # The generic receiver: anything at all may arrive, including a bare array
    # or a string. Keep whatever came for `payload`, and read `record_id` only
    # when there is an object to read it from.
    raw = await request.json()

    event_data = {
        "webhook_id": webhook_id,
        "record_id": _payload(raw).get("record_id"),
        "payload": raw,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }

    service = WorkflowEventService(db)
    resumed = await service.handle_event(workspace_id, "webhook.received", event_data)

    return WorkflowEventResponse(
        success=True,
        message="Processed webhook.received event",
        resumed_executions=resumed,
    )


# =============================================================================
# MANUAL EVENT TRIGGER (Authenticated)
# =============================================================================


@router.post("/trigger", response_model=WorkflowEventResponse)
async def trigger_event(
    workspace_id: str,
    data: WorkflowEventRequest,
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """
    Manually trigger a workflow event.
    Useful for testing or internal integrations.
    """
    # Verify workspace access
    from aexy.services.workspace_service import WorkspaceService

    ws_service = WorkspaceService(db)
    workspace = await ws_service.get_workspace(workspace_id)
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Check membership
    member = await ws_service.get_workspace_member(workspace_id, current_user.id)
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not a member of this workspace",
        )

    event_data = {
        **data.event_data,
        "triggered_by": current_user.id,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
    }

    if data.record_id:
        event_data["record_id"] = data.record_id

    service = WorkflowEventService(db)
    resumed = await service.handle_event(workspace_id, data.event_type, event_data)

    return WorkflowEventResponse(
        success=True,
        message=f"Triggered {data.event_type} event",
        resumed_executions=resumed,
    )


# =============================================================================
# METADATA ENDPOINTS
# =============================================================================


@router.get("/types", response_model=list[SupportedEventType])
async def get_supported_event_types(
    workspace_id: str,
    _: None = Depends(require_workspace_member()),
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """Get list of supported event types for wait nodes."""
    return WorkflowEventService.get_supported_events()


@router.get("/webhook-urls")
async def get_webhook_urls(
    workspace_id: str,
    _: None = Depends(require_workspace_member()),
    db: AsyncSession = Depends(get_db),
    current_user: Developer = Depends(get_current_developer),
):
    """The URLs an outside system posts to, and the secret it must present.

    `settings.api_base_url` never existed, so this endpoint raised
    AttributeError on every call — a 500 where the setup instructions should
    be. The URLs it printed also omitted the API prefix.
    """
    base_url = f"{settings.backend_url}{settings.api_v1_prefix}"

    return {
        "email_tracking": f"{base_url}/workspaces/{workspace_id}/workflow-events/webhooks/email-tracking",
        "form_submission": f"{base_url}/workspaces/{workspace_id}/workflow-events/webhooks/form-submission",
        "meeting": f"{base_url}/workspaces/{workspace_id}/workflow-events/webhooks/meeting",
        "custom_webhook_template": f"{base_url}/workspaces/{workspace_id}/workflow-events/webhooks/custom/{{webhook_id}}",
        "secret": derive_workflow_webhook_secret(workspace_id),
        "secret_header": WEBHOOK_SECRET_HEADER,
        "signature_header": WEBHOOK_SIGNATURE_HEADER,
        # Said here rather than left to be discovered: signing is the better
        # of the two, and the secret must never go in the query string, where
        # every proxy and CDN on the way writes it to an access log.
        "how_to_authenticate": (
            f"Sign the raw request body with the secret (HMAC-SHA256) and send "
            f"`{WEBHOOK_SIGNATURE_HEADER}: sha256=<hex>`. If your sender cannot "
            f"compute an HMAC, send the secret itself in `{WEBHOOK_SECRET_HEADER}`. "
            "The secret is never accepted as a query parameter."
        ),
    }

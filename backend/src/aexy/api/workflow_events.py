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
# Each workspace has a secret derived from the server key, the same scheme
# the CRM automation webhooks use (see api/webhooks.py) — no migration, no
# state to lose. It is shown alongside the URLs at GET /webhook-urls and is
# presented either as a header or, for tools that cannot set headers, as a
# `secret` query parameter.

WEBHOOK_SECRET_HEADER = "X-Aexy-Webhook-Secret"


def _nested(payload: Any, key: str) -> dict[str, Any]:
    """A nested object from a webhook body, or `{}` if it is anything else.

    Webhook senders disagree about shape: one sends `{"event": {"uuid": …}}`,
    another sends `{"event": "booked"}`. Reading `.get()` off the second is an
    AttributeError and a 500 on a request the sender will keep retrying.
    """
    if not isinstance(payload, dict):
        return {}
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def derive_workflow_webhook_secret(workspace_id: str) -> str:
    return hmac.new(
        settings.secret_key.encode("utf-8"),
        f"workflow-events:{workspace_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


async def verify_webhook_secret(
    workspace_id: str,
    presented_header: str | None = Header(default=None, alias=WEBHOOK_SECRET_HEADER),
    secret: str | None = None,
) -> None:
    presented = presented_header or secret
    if not presented or not hmac.compare_digest(
        presented, derive_workflow_webhook_secret(workspace_id)
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Missing or invalid webhook secret. Send the workspace's webhook "
                f"secret in the {WEBHOOK_SECRET_HEADER} header (or a `secret` query "
                "parameter); it is shown with the webhook URLs."
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
    """
    body = await request.json()

    # Map common email event payloads
    event_type = body.get("event") or body.get("type")
    if not event_type:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing event type in payload",
        )

    # Normalize event type
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
    normalized_type = event_type_map.get(event_type.lower(), f"email.{event_type}")

    event_data = {
        "email_id": body.get("email_id") or body.get("message_id") or body.get("sg_message_id"),
        "record_id": body.get("record_id") or body.get("metadata", {}).get("record_id"),
        "recipient_email": body.get("email") or body.get("recipient"),
        "timestamp": body.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "raw_event": body,
    }

    # Handle click-specific data
    if "url" in body or "link" in body:
        event_data["link_url"] = body.get("url") or body.get("link")

    service = WorkflowEventService(db)
    resumed = await service.handle_event(workspace_id, normalized_type, event_data)

    return WorkflowEventResponse(
        success=True,
        message=f"Processed {normalized_type} event",
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
    body = await request.json()

    event_data = {
        "form_id": body.get("form_id") or body.get("formId"),
        "record_id": body.get("record_id") or body.get("hidden", {}).get("record_id"),
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
    body = await request.json()

    # Determine event type
    event_type = body.get("event") or body.get("type") or "scheduled"
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
    body = await request.json()

    event_data = {
        "webhook_id": webhook_id,
        "record_id": body.get("record_id"),
        "payload": body,
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
    }

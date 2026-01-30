"""Webhook endpoints for receiving email provider events."""

import hashlib
import hmac
import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Header, Request, status
from pydantic import BaseModel
from sqlalchemy import text

from mailagent.database import get_db
from mailagent.config import get_settings


router = APIRouter(prefix="/webhooks", tags=["webhooks"])
settings = get_settings()


# ============================================
# SENDGRID WEBHOOKS
# ============================================

class SendGridEvent(BaseModel):
    """SendGrid webhook event."""
    email: str
    timestamp: int
    event: str
    sg_message_id: Optional[str] = None
    reason: Optional[str] = None
    url: Optional[str] = None
    useragent: Optional[str] = None
    ip: Optional[str] = None


@router.post("/sendgrid")
async def sendgrid_webhook(
    request: Request,
    session=Depends(get_db),
):
    """Handle SendGrid webhook events.

    Events: processed, dropped, delivered, deferred, bounce, open, click,
            spam_report, unsubscribe, group_unsubscribe, group_resubscribe
    """
    body = await request.body()

    # Verify webhook signature if configured
    webhook_key = getattr(settings, 'sendgrid_webhook_key', None)
    if webhook_key:
        signature = request.headers.get('X-Twilio-Email-Event-Webhook-Signature')
        timestamp = request.headers.get('X-Twilio-Email-Event-Webhook-Timestamp')
        if not _verify_sendgrid_signature(webhook_key, signature, timestamp, body):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        events = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    for event_data in events:
        event_type = event_data.get('event', 'unknown')
        message_id = event_data.get('sg_message_id', '').split('.')[0]  # Remove filter ID

        # Store the event
        await session.execute(
            text("""
                INSERT INTO mailagent_provider_events (
                    provider, event_type, external_message_id, payload
                ) VALUES ('sendgrid', :event_type, :message_id, :payload)
            """),
            {
                "event_type": event_type,
                "message_id": message_id,
                "payload": json.dumps(event_data),
            },
        )

        # Update message status based on event
        await _update_message_status(session, 'sendgrid', message_id, event_type, event_data)

    await session.commit()
    return {"status": "ok", "processed": len(events)}


def _verify_sendgrid_signature(key: str, signature: str, timestamp: str, body: bytes) -> bool:
    """Verify SendGrid webhook signature."""
    if not signature or not timestamp:
        return False
    try:
        payload = timestamp.encode() + body
        expected = hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    except Exception:
        return False


# ============================================
# SES WEBHOOKS (via SNS)
# ============================================

@router.post("/ses")
async def ses_webhook(
    request: Request,
    session=Depends(get_db),
):
    """Handle AWS SES webhook events via SNS.

    Events: Bounce, Complaint, Delivery, Send, Reject, Open, Click
    """
    body = await request.body()

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle SNS subscription confirmation
    if data.get('Type') == 'SubscriptionConfirmation':
        # In production, you'd confirm by visiting the SubscribeURL
        return {"status": "subscription_confirmation_received", "url": data.get('SubscribeURL')}

    # Handle notification
    if data.get('Type') == 'Notification':
        message = json.loads(data.get('Message', '{}'))
        notification_type = message.get('notificationType', message.get('eventType', 'unknown'))

        # Extract message ID from mail object
        mail = message.get('mail', {})
        message_id = mail.get('messageId', '')

        # Store the event
        await session.execute(
            text("""
                INSERT INTO mailagent_provider_events (
                    provider, event_type, external_message_id, payload
                ) VALUES ('ses', :event_type, :message_id, :payload)
            """),
            {
                "event_type": notification_type.lower(),
                "message_id": message_id,
                "payload": json.dumps(message),
            },
        )

        # Update message status
        await _update_message_status(session, 'ses', message_id, notification_type.lower(), message)

        await session.commit()
        return {"status": "ok", "event_type": notification_type}

    return {"status": "ignored"}


# ============================================
# GENERIC WEBHOOK HANDLER
# ============================================

@router.post("/generic/{provider}")
async def generic_webhook(
    provider: str,
    request: Request,
    session=Depends(get_db),
):
    """Generic webhook handler for other providers."""
    body = await request.body()

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body.decode('utf-8', errors='ignore')}

    # Store raw event for later processing
    await session.execute(
        text("""
            INSERT INTO mailagent_provider_events (
                provider, event_type, payload
            ) VALUES (:provider, 'raw', :payload)
        """),
        {
            "provider": provider,
            "payload": json.dumps(data),
        },
    )
    await session.commit()

    return {"status": "ok"}


# ============================================
# HELPER FUNCTIONS
# ============================================

async def _update_message_status(
    session,
    provider: str,
    external_message_id: str,
    event_type: str,
    event_data: dict,
):
    """Update message status based on webhook event."""
    if not external_message_id:
        return

    # Map event types to status updates
    status_map = {
        # Delivery events
        'delivered': ('delivered', 'delivered_at'),
        'delivery': ('delivered', 'delivered_at'),

        # Open events
        'open': ('opened', 'opened_at'),
        'opened': ('opened', 'opened_at'),

        # Click events
        'click': ('clicked', 'clicked_at'),
        'clicked': ('clicked', 'clicked_at'),

        # Bounce events
        'bounce': ('bounced', 'bounced_at'),
        'bounced': ('bounced', 'bounced_at'),

        # Complaint events
        'complaint': ('complained', None),
        'spam_report': ('complained', None),
        'spamreport': ('complained', None),
    }

    if event_type.lower() in status_map:
        new_status, timestamp_field = status_map[event_type.lower()]

        # Build update query
        if timestamp_field:
            await session.execute(
                text(f"""
                    UPDATE mailagent_messages
                    SET delivery_status = :status, {timestamp_field} = NOW()
                    WHERE provider_message_id = :message_id
                """),
                {"status": new_status, "message_id": external_message_id},
            )
        else:
            await session.execute(
                text("""
                    UPDATE mailagent_messages
                    SET delivery_status = :status
                    WHERE provider_message_id = :message_id
                """),
                {"status": new_status, "message_id": external_message_id},
            )

        # Handle bounce details
        if event_type.lower() in ('bounce', 'bounced'):
            bounce_reason = event_data.get('reason') or event_data.get('bounce', {}).get('bouncedRecipients', [{}])[0].get('diagnosticCode', '')
            if bounce_reason:
                await session.execute(
                    text("""
                        UPDATE mailagent_messages
                        SET bounce_reason = :reason
                        WHERE provider_message_id = :message_id
                    """),
                    {"reason": bounce_reason[:1000], "message_id": external_message_id},
                )

        # Update domain health metrics
        await _update_domain_health(session, external_message_id, event_type.lower())


async def _update_domain_health(session, message_id: str, event_type: str):
    """Update domain health metrics based on event."""
    # Get the domain from the message
    result = await session.execute(
        text("""
            SELECT m.domain_id FROM mailagent_messages m
            WHERE m.provider_message_id = :message_id AND m.domain_id IS NOT NULL
        """),
        {"message_id": message_id},
    )
    row = result.fetchone()
    if not row:
        return

    domain_id = row.domain_id

    # Upsert domain health record for today
    field_map = {
        'delivered': 'delivered_count',
        'delivery': 'delivered_count',
        'bounced': 'bounced_count',
        'bounce': 'bounced_count',
        'complained': 'complained_count',
        'complaint': 'complained_count',
        'spam_report': 'complained_count',
        'open': 'opened_count',
        'opened': 'opened_count',
        'click': 'clicked_count',
        'clicked': 'clicked_count',
    }

    field = field_map.get(event_type.lower())
    if field:
        await session.execute(
            text(f"""
                INSERT INTO mailagent_domain_health (domain_id, date, {field})
                VALUES (:domain_id, CURRENT_DATE, 1)
                ON CONFLICT (domain_id, date) DO UPDATE
                SET {field} = mailagent_domain_health.{field} + 1
            """),
            {"domain_id": domain_id},
        )


# ============================================
# WEBHOOK MANAGEMENT
# ============================================

class WebhookCreate(BaseModel):
    """Create webhook subscription."""
    url: str
    event_types: list[str]
    secret: Optional[str] = None
    inbox_ids: Optional[list[UUID]] = None


class WebhookResponse(BaseModel):
    """Webhook response."""
    id: UUID
    url: str
    event_types: list[str]
    is_active: bool
    failure_count: int


@router.post("/subscriptions", response_model=WebhookResponse, status_code=status.HTTP_201_CREATED)
async def create_webhook_subscription(
    webhook: WebhookCreate,
    session=Depends(get_db),
):
    """Create a new webhook subscription for outgoing notifications."""
    import secrets

    secret = webhook.secret or secrets.token_hex(32)

    result = await session.execute(
        text("""
            INSERT INTO mailagent_webhooks (url, event_types, secret, inbox_ids)
            VALUES (:url, :event_types, :secret, :inbox_ids)
            RETURNING id, url, event_types, is_active, failure_count
        """),
        {
            "url": webhook.url,
            "event_types": webhook.event_types,
            "secret": secret,
            "inbox_ids": webhook.inbox_ids,
        },
    )
    await session.commit()

    row = result.fetchone()
    return WebhookResponse(
        id=row.id,
        url=row.url,
        event_types=row.event_types,
        is_active=row.is_active,
        failure_count=row.failure_count,
    )


@router.get("/subscriptions", response_model=list[WebhookResponse])
async def list_webhook_subscriptions(
    session=Depends(get_db),
):
    """List all webhook subscriptions."""
    result = await session.execute(
        text("""
            SELECT id, url, event_types, is_active, failure_count
            FROM mailagent_webhooks
            ORDER BY created_at DESC
        """)
    )
    rows = result.fetchall()

    return [
        WebhookResponse(
            id=row.id,
            url=row.url,
            event_types=row.event_types,
            is_active=row.is_active,
            failure_count=row.failure_count,
        )
        for row in rows
    ]


@router.delete("/subscriptions/{webhook_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_webhook_subscription(
    webhook_id: UUID,
    session=Depends(get_db),
):
    """Delete a webhook subscription."""
    result = await session.execute(
        text("DELETE FROM mailagent_webhooks WHERE id = :id RETURNING id"),
        {"id": webhook_id},
    )
    await session.commit()

    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Webhook not found")

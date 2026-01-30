"""API endpoints for sending emails."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from pydantic import BaseModel, EmailStr

from mailagent.database import get_db
from mailagent.providers.base import EmailAddress, EmailMessage, Attachment
from mailagent.services.send_service import get_send_service


router = APIRouter(prefix="/send", tags=["send"])


# Request/Response schemas
class EmailAddressInput(BaseModel):
    """Email address input."""
    address: EmailStr
    name: Optional[str] = None


class AttachmentInput(BaseModel):
    """Attachment input."""
    filename: str
    content_base64: str
    content_type: str
    content_id: Optional[str] = None


class SendEmailRequest(BaseModel):
    """Request to send an email."""
    from_address: EmailAddressInput
    to_addresses: list[EmailAddressInput]
    cc_addresses: list[EmailAddressInput] = []
    bcc_addresses: list[EmailAddressInput] = []
    reply_to: Optional[EmailAddressInput] = None

    subject: str
    body_html: Optional[str] = None
    body_text: Optional[str] = None

    attachments: list[AttachmentInput] = []
    headers: dict[str, str] = {}

    # Threading
    in_reply_to: Optional[str] = None
    references: list[str] = []

    # Tracking
    track_opens: bool = True
    track_clicks: bool = True

    # Metadata
    tags: list[str] = []
    metadata: dict = {}

    # Routing
    provider_id: Optional[UUID] = None
    domain_id: Optional[UUID] = None


class SendBatchRequest(BaseModel):
    """Request to send multiple emails."""
    messages: list[SendEmailRequest]
    concurrency: int = 10


class SendResponse(BaseModel):
    """Response after sending email."""
    success: bool
    message_id: Optional[str] = None
    provider: str
    provider_message_id: Optional[str] = None
    error: Optional[str] = None


class SendBatchResponse(BaseModel):
    """Response after sending batch."""
    total: int
    successful: int
    failed: int
    results: list[SendResponse]


def _to_email_address(addr: EmailAddressInput) -> EmailAddress:
    """Convert input to EmailAddress."""
    return EmailAddress(address=addr.address, name=addr.name)


def _to_attachment(att: AttachmentInput) -> Attachment:
    """Convert input to Attachment."""
    import base64
    return Attachment(
        filename=att.filename,
        content=base64.b64decode(att.content_base64),
        content_type=att.content_type,
        content_id=att.content_id,
    )


def _to_email_message(req: SendEmailRequest) -> EmailMessage:
    """Convert request to EmailMessage."""
    return EmailMessage(
        from_address=_to_email_address(req.from_address),
        to_addresses=[_to_email_address(a) for a in req.to_addresses],
        cc_addresses=[_to_email_address(a) for a in req.cc_addresses],
        bcc_addresses=[_to_email_address(a) for a in req.bcc_addresses],
        reply_to=_to_email_address(req.reply_to) if req.reply_to else None,
        subject=req.subject,
        body_html=req.body_html,
        body_text=req.body_text,
        attachments=[_to_attachment(a) for a in req.attachments],
        headers=req.headers,
        in_reply_to=req.in_reply_to,
        references=req.references,
        track_opens=req.track_opens,
        track_clicks=req.track_clicks,
        tags=req.tags,
        metadata=req.metadata,
    )


@router.post("/email", response_model=SendResponse)
async def send_email(
    request: SendEmailRequest,
):
    """Send a single email."""
    if not request.body_html and not request.body_text:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either body_html or body_text is required",
        )

    message = _to_email_message(request)
    service = await get_send_service()

    result = await service.send(
        message=message,
        provider_id=request.provider_id,
        domain_id=request.domain_id,
    )

    return SendResponse(
        success=result.success,
        message_id=result.message_id,
        provider=result.provider,
        provider_message_id=result.provider_message_id,
        error=result.error,
    )


@router.post("/batch", response_model=SendBatchResponse)
async def send_batch(
    request: SendBatchRequest,
    background_tasks: BackgroundTasks,
):
    """Send multiple emails in batch."""
    if len(request.messages) > 1000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 1000 messages per batch",
        )

    messages = [_to_email_message(m) for m in request.messages]
    service = await get_send_service()

    results = await service.send_batch(
        messages=messages,
        concurrency=min(request.concurrency, 50),  # Cap concurrency
    )

    responses = [
        SendResponse(
            success=r.success,
            message_id=r.message_id,
            provider=r.provider,
            provider_message_id=r.provider_message_id,
            error=r.error,
        )
        for r in results
    ]

    successful = sum(1 for r in results if r.success)

    return SendBatchResponse(
        total=len(results),
        successful=successful,
        failed=len(results) - successful,
        results=responses,
    )


@router.post("/template/{template_id}")
async def send_templated_email(
    template_id: UUID,
    to_addresses: list[EmailAddressInput],
    variables: dict,
    provider_id: Optional[UUID] = None,
):
    """Send an email using a template."""
    # This would integrate with a template system
    # For now, return not implemented
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Template sending not yet implemented",
    )


@router.get("/status/{message_id}")
async def get_send_status(
    message_id: str,
    session=Depends(get_db),
):
    """Get the status of a sent message."""
    from sqlalchemy import text

    result = await session.execute(
        text("""
            SELECT
                m.id, m.message_id, m.status, m.from_address, m.to_addresses,
                m.subject, m.sent_at, m.provider_message_id,
                p.name as provider_name
            FROM mailagent_messages m
            LEFT JOIN mailagent_providers p ON p.id = m.provider_id
            WHERE m.message_id = :message_id OR m.provider_message_id = :message_id
        """),
        {"message_id": message_id},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Message not found")

    return {
        "id": row.id,
        "message_id": row.message_id,
        "status": row.status,
        "from_address": row.from_address,
        "to_addresses": row.to_addresses,
        "subject": row.subject,
        "sent_at": row.sent_at.isoformat() if row.sent_at else None,
        "provider": row.provider_name,
        "provider_message_id": row.provider_message_id,
    }


@router.post("/test")
async def send_test_email(
    to_address: EmailStr,
    provider_id: Optional[UUID] = None,
):
    """Send a test email to verify configuration."""
    message = EmailMessage(
        from_address=EmailAddress(
            address="test@example.com",
            name="Mailagent Test",
        ),
        to_addresses=[EmailAddress(address=to_address)],
        subject="Mailagent Test Email",
        body_text="This is a test email from Mailagent to verify your configuration is working correctly.",
        body_html="""
        <html>
        <body>
            <h2>Mailagent Test Email</h2>
            <p>This is a test email from Mailagent to verify your configuration is working correctly.</p>
            <p>If you received this email, your email provider integration is set up correctly!</p>
        </body>
        </html>
        """,
        tags=["test"],
    )

    service = await get_send_service()
    result = await service.send(message, provider_id=provider_id)

    return SendResponse(
        success=result.success,
        message_id=result.message_id,
        provider=result.provider,
        provider_message_id=result.provider_message_id,
        error=result.error,
    )

"""API endpoints for email processing."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr

from mailagent.database import get_db
from mailagent.services.orchestrator import get_orchestrator


router = APIRouter(prefix="/process", tags=["process"])


class IncomingEmail(BaseModel):
    """Incoming email to process."""
    inbox_id: UUID
    from_address: EmailStr
    from_name: Optional[str] = None
    to_addresses: list[dict]
    cc_addresses: list[dict] = []
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    message_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: list[str] = []
    headers: dict = {}


class ProcessResult(BaseModel):
    """Result of processing an email."""
    status: str
    message_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_name: Optional[str] = None
    action: Optional[str] = None
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
    requires_approval: bool = False
    decision_id: Optional[str] = None
    draft_response: Optional[str] = None
    response_sent: bool = False
    response_message_id: Optional[str] = None
    message: Optional[str] = None


@router.post("/incoming", response_model=ProcessResult)
async def process_incoming_email(
    email: IncomingEmail,
):
    """Process an incoming email through the agent system.

    This endpoint receives incoming emails (typically from a mail server
    or email forwarding service) and routes them through the appropriate
    AI agents for processing.
    """
    orchestrator = get_orchestrator()

    result = await orchestrator.process_incoming_email(
        inbox_id=email.inbox_id,
        message_data={
            "from_address": email.from_address,
            "from_name": email.from_name,
            "to_addresses": email.to_addresses,
            "cc_addresses": email.cc_addresses,
            "subject": email.subject,
            "body_text": email.body_text,
            "body_html": email.body_html,
            "message_id": email.message_id,
            "in_reply_to": email.in_reply_to,
            "references": email.references,
            "headers": email.headers,
        },
    )

    return ProcessResult(
        status=result.get("status", "unknown"),
        message_id=str(result.get("message_id")) if result.get("message_id") else None,
        agent_id=result.get("agent_id"),
        agent_name=result.get("agent_name"),
        action=result.get("action").value if result.get("action") else None,
        confidence=result.get("confidence"),
        reasoning=result.get("reasoning"),
        requires_approval=result.get("requires_approval", False),
        decision_id=result.get("decision_id"),
        draft_response=result.get("draft_response"),
        response_sent=result.get("response_sent", False),
        response_message_id=result.get("response_message_id"),
        message=result.get("message"),
    )


@router.post("/reprocess/{message_id}", response_model=ProcessResult)
async def reprocess_message(
    message_id: UUID,
    agent_id: Optional[UUID] = None,
):
    """Reprocess an existing message.

    Useful for testing agents or re-running failed processing.
    """
    orchestrator = get_orchestrator()

    result = await orchestrator.reprocess_message(message_id, agent_id)

    return ProcessResult(
        status=result.get("status", "unknown"),
        message_id=str(message_id),
        agent_id=result.get("agent_id"),
        action=result.get("action").value if result.get("action") else None,
        confidence=result.get("confidence"),
        reasoning=result.get("reasoning"),
        requires_approval=result.get("requires_approval", False),
        decision_id=result.get("decision_id"),
        draft_response=result.get("draft_response"),
        response_sent=result.get("response_sent", False),
        message=result.get("message"),
    )


@router.post("/approve/{decision_id}")
async def approve_and_execute(
    decision_id: UUID,
    modified_response: Optional[str] = None,
    session=Depends(get_db),
):
    """Approve a pending decision and execute it.

    If a modified_response is provided, it will be used instead of
    the original draft.
    """
    from sqlalchemy import text

    # Get decision details
    result = await session.execute(
        text("""
            SELECT d.id, d.agent_id, d.message_id, d.action, d.response_draft,
                   d.requires_approval, d.approved, d.executed,
                   m.inbox_id, m.from_address, m.subject, m.message_id as msg_id,
                   a.name as agent_name
            FROM mailagent_agent_decisions d
            JOIN mailagent_messages m ON m.id = d.message_id
            JOIN mailagent_agents a ON a.id = d.agent_id
            WHERE d.id = :decision_id
        """),
        {"decision_id": decision_id},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Decision not found")

    if row.executed:
        raise HTTPException(status_code=400, detail="Decision already executed")

    # Mark as approved
    await session.execute(
        text("""
            UPDATE mailagent_agent_decisions
            SET approved = true, approved_at = NOW()
            WHERE id = :decision_id
        """),
        {"decision_id": decision_id},
    )

    response_text = modified_response or row.response_draft

    # Execute the action
    if row.action == 'reply' and response_text:
        from mailagent.services.send_service import get_send_service
        from mailagent.providers.base import EmailMessage, EmailAddress

        # Get inbox email
        inbox_result = await session.execute(
            text("SELECT email FROM mailagent_inboxes WHERE id = :inbox_id"),
            {"inbox_id": row.inbox_id},
        )
        inbox_row = inbox_result.fetchone()
        inbox_email = inbox_row.email if inbox_row else "noreply@example.com"

        message = EmailMessage(
            from_address=EmailAddress(address=inbox_email, name=row.agent_name),
            to_addresses=[EmailAddress(address=row.from_address)],
            subject=f"Re: {row.subject or 'Your message'}",
            body_text=response_text,
            body_html=f"<html><body>{response_text.replace(chr(10), '<br>')}</body></html>",
            in_reply_to=row.msg_id,
        )

        send_service = await get_send_service()
        send_result = await send_service.send(message)

        # Mark decision executed
        await session.execute(
            text("""
                UPDATE mailagent_agent_decisions
                SET executed = true, executed_at = NOW(), execution_result = :result
                WHERE id = :decision_id
            """),
            {
                "decision_id": decision_id,
                "result": {"sent": send_result.success, "message_id": send_result.message_id},
            },
        )

        await session.commit()

        return {
            "status": "executed",
            "decision_id": str(decision_id),
            "action": "reply",
            "sent": send_result.success,
            "message_id": send_result.message_id,
            "error": send_result.error,
        }

    await session.commit()
    return {
        "status": "approved",
        "decision_id": str(decision_id),
        "action": row.action,
    }


@router.post("/reject/{decision_id}")
async def reject_decision(
    decision_id: UUID,
    feedback: Optional[str] = None,
    session=Depends(get_db),
):
    """Reject a pending decision with optional feedback."""
    from sqlalchemy import text

    result = await session.execute(
        text("""
            UPDATE mailagent_agent_decisions
            SET approved = false, approved_at = NOW(),
                approval_notes = :feedback
            WHERE id = :decision_id AND approved IS NULL
            RETURNING id
        """),
        {"decision_id": decision_id, "feedback": feedback},
    )
    await session.commit()

    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Decision not found or already processed")

    return {"status": "rejected", "decision_id": str(decision_id)}


@router.get("/pending")
async def get_pending_approvals(
    inbox_id: Optional[UUID] = None,
    limit: int = 50,
    session=Depends(get_db),
):
    """Get all pending approvals."""
    from sqlalchemy import text

    conditions = ["d.requires_approval = true", "d.approved IS NULL", "d.executed = false"]
    params = {"limit": limit}

    if inbox_id:
        conditions.append("m.inbox_id = :inbox_id")
        params["inbox_id"] = inbox_id

    where_clause = " AND ".join(conditions)

    result = await session.execute(
        text(f"""
            SELECT d.id, d.agent_id, d.message_id, d.action, d.confidence,
                   d.reasoning, d.response_draft, d.created_at,
                   m.from_address, m.subject, m.body_text,
                   a.name as agent_name, a.agent_type
            FROM mailagent_agent_decisions d
            JOIN mailagent_messages m ON m.id = d.message_id
            JOIN mailagent_agents a ON a.id = d.agent_id
            WHERE {where_clause}
            ORDER BY d.created_at DESC
            LIMIT :limit
        """),
        params,
    )
    rows = result.fetchall()

    return {
        "pending": [
            {
                "decision_id": str(row.id),
                "agent_id": str(row.agent_id),
                "agent_name": row.agent_name,
                "agent_type": row.agent_type,
                "message_id": str(row.message_id),
                "action": row.action,
                "confidence": float(row.confidence),
                "reasoning": row.reasoning,
                "draft_response": row.response_draft,
                "created_at": row.created_at.isoformat(),
                "original_email": {
                    "from_address": row.from_address,
                    "subject": row.subject,
                    "body_preview": row.body_text[:500] if row.body_text else None,
                },
            }
            for row in rows
        ],
        "total": len(rows),
    }

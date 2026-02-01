"""Agent orchestrator for routing and processing incoming emails."""

import asyncio
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text

from mailagent.database import async_session_factory
from mailagent.agents import (
    EmailAgent,
    AgentContext,
    AgentDecision,
    AgentAction,
    MessageData,
    ContactData,
    get_agents_for_inbox,
    create_agent_from_db,
)
from mailagent.services.send_service import get_send_service
from mailagent.providers.base import EmailMessage, EmailAddress


class AgentOrchestrator:
    """Orchestrates email processing across multiple agents."""

    def __init__(self):
        self._processing_lock = asyncio.Lock()

    async def process_incoming_email(
        self,
        inbox_id: UUID,
        message_data: dict,
    ) -> dict:
        """Process an incoming email through the appropriate agents.

        Args:
            inbox_id: The inbox that received the email
            message_data: Raw email data

        Returns:
            Processing result with decision and response
        """
        async with async_session_factory() as session:
            # Store the incoming message
            message_id = await self._store_message(session, inbox_id, message_data)

            # Get agents for this inbox
            agents = await get_agents_for_inbox(inbox_id)

            if not agents:
                return {
                    "status": "no_agents",
                    "message_id": message_id,
                    "message": "No agents configured for this inbox",
                }

            # Build context
            context = await self._build_context(session, inbox_id, message_id, message_data)

            # Process through agents (in priority order)
            for agent in agents:
                try:
                    result = await self._process_with_agent(session, agent, context)

                    if result["action"] != AgentAction.NO_ACTION:
                        # This agent handled it
                        return {
                            "status": "processed",
                            "message_id": message_id,
                            "agent_id": str(agent.agent_id),
                            "agent_name": agent.config.name,
                            **result,
                        }
                except Exception as e:
                    # Log error but continue to next agent
                    await self._log_agent_error(session, agent.agent_id, message_id, str(e))
                    continue

            # No agent handled it
            return {
                "status": "unhandled",
                "message_id": message_id,
                "message": "No agent could handle this email",
            }

    async def _store_message(
        self,
        session,
        inbox_id: UUID,
        message_data: dict,
    ) -> UUID:
        """Store incoming message in database."""
        message_id = uuid4()

        # Check for existing thread
        thread_id = await self._find_or_create_thread(
            session,
            inbox_id,
            message_data.get('in_reply_to'),
            message_data.get('references', []),
            message_data.get('subject', ''),
            message_data.get('from_address', ''),
        )

        await session.execute(
            text("""
                INSERT INTO mailagent_messages (
                    id, inbox_id, thread_id, message_id, in_reply_to, "references",
                    from_address, from_name, to_addresses, cc_addresses,
                    subject, body_text, body_html, headers,
                    direction, status, received_at
                ) VALUES (
                    :id, :inbox_id, :thread_id, :message_id, :in_reply_to, :references,
                    :from_address, :from_name, :to_addresses, :cc_addresses,
                    :subject, :body_text, :body_html, :headers,
                    'inbound', 'received', NOW()
                )
            """),
            {
                "id": message_id,
                "inbox_id": inbox_id,
                "thread_id": thread_id,
                "message_id": message_data.get('message_id'),
                "in_reply_to": message_data.get('in_reply_to'),
                "references": message_data.get('references', []),
                "from_address": message_data.get('from_address'),
                "from_name": message_data.get('from_name'),
                "to_addresses": message_data.get('to_addresses', []),
                "cc_addresses": message_data.get('cc_addresses', []),
                "subject": message_data.get('subject'),
                "body_text": message_data.get('body_text'),
                "body_html": message_data.get('body_html'),
                "headers": message_data.get('headers', {}),
            },
        )
        await session.commit()

        return message_id

    async def _find_or_create_thread(
        self,
        session,
        inbox_id: UUID,
        in_reply_to: Optional[str],
        references: list[str],
        subject: str,
        from_address: str,
    ) -> Optional[UUID]:
        """Find existing thread or create new one."""
        # Try to find thread by in_reply_to or references
        if in_reply_to or references:
            all_refs = [in_reply_to] + references if in_reply_to else references
            result = await session.execute(
                text("""
                    SELECT DISTINCT thread_id FROM mailagent_messages
                    WHERE inbox_id = :inbox_id
                      AND thread_id IS NOT NULL
                      AND (message_id = ANY(:refs) OR in_reply_to = ANY(:refs))
                    LIMIT 1
                """),
                {"inbox_id": inbox_id, "refs": all_refs},
            )
            row = result.fetchone()
            if row:
                return row.thread_id

        # Create new thread
        thread_id = uuid4()
        await session.execute(
            text("""
                INSERT INTO mailagent_threads (id, inbox_id, subject, participants, message_count)
                VALUES (:id, :inbox_id, :subject, :participants, 1)
            """),
            {
                "id": thread_id,
                "inbox_id": inbox_id,
                "subject": subject,
                "participants": [{"email": from_address}],
            },
        )

        return thread_id

    async def _build_context(
        self,
        session,
        inbox_id: UUID,
        message_id: UUID,
        message_data: dict,
    ) -> AgentContext:
        """Build context for agent processing."""
        # Get thread history
        thread_messages = []
        if message_data.get('in_reply_to'):
            result = await session.execute(
                text("""
                    SELECT id, from_address, from_name, to_addresses, subject,
                           body_text, body_html, received_at, sent_at, thread_id, message_id
                    FROM mailagent_messages
                    WHERE inbox_id = :inbox_id
                      AND thread_id = (
                          SELECT thread_id FROM mailagent_messages
                          WHERE id = :message_id
                      )
                      AND id != :message_id
                    ORDER BY COALESCE(received_at, sent_at) DESC
                    LIMIT 10
                """),
                {"inbox_id": inbox_id, "message_id": message_id},
            )
            rows = result.fetchall()
            thread_messages = [
                MessageData(
                    id=row.id,
                    from_address=row.from_address,
                    from_name=row.from_name,
                    to_addresses=row.to_addresses or [],
                    subject=row.subject,
                    body_text=row.body_text,
                    body_html=row.body_html,
                    received_at=row.received_at or row.sent_at,
                    thread_id=row.thread_id,
                    message_id=row.message_id,
                )
                for row in rows
            ]

        # Get contact info
        contact = await self._get_contact_info(session, message_data.get('from_address'))

        # Get inbox email
        result = await session.execute(
            text("SELECT email FROM mailagent_inboxes WHERE id = :inbox_id"),
            {"inbox_id": inbox_id},
        )
        inbox_row = result.fetchone()
        inbox_email = inbox_row.email if inbox_row else ""

        return AgentContext(
            message=MessageData(
                id=message_id,
                from_address=message_data.get('from_address', ''),
                from_name=message_data.get('from_name'),
                to_addresses=message_data.get('to_addresses', []),
                subject=message_data.get('subject'),
                body_text=message_data.get('body_text'),
                body_html=message_data.get('body_html'),
                received_at=datetime.now(timezone.utc),
                message_id=message_data.get('message_id'),
            ),
            thread_messages=thread_messages,
            contact=contact,
            agent_config={"inbox_email": inbox_email},
        )

    async def _get_contact_info(self, session, email: str) -> Optional[ContactData]:
        """Get contact information from previous interactions."""
        if not email:
            return None

        # Count previous interactions
        result = await session.execute(
            text("""
                SELECT COUNT(*) as count
                FROM mailagent_messages
                WHERE from_address = :email
            """),
            {"email": email},
        )
        row = result.fetchone()

        return ContactData(
            email=email,
            previous_interactions=row.count if row else 0,
        )

    async def _process_with_agent(
        self,
        session,
        agent: EmailAgent,
        context: AgentContext,
    ) -> dict:
        """Process message with a specific agent."""
        # Check working hours
        if not agent.is_within_working_hours():
            return {"action": AgentAction.NO_ACTION, "reason": "Outside working hours"}

        # Get agent decision
        decision = await agent.process_message(context)

        # Store decision
        decision_id = await self._store_decision(session, agent.agent_id, context.message.id, decision)

        result = {
            "action": decision.action,
            "confidence": decision.confidence,
            "reasoning": decision.reasoning,
            "requires_approval": decision.requires_approval,
            "decision_id": str(decision_id),
        }

        # Auto-execute if confidence is high enough
        if decision.should_auto_execute(agent.config.confidence_threshold):
            if decision.action == AgentAction.REPLY and decision.draft_response:
                # Send the response
                send_result = await self._send_response(
                    session, context, decision, agent
                )
                result["response_sent"] = send_result.get("success", False)
                result["response_message_id"] = send_result.get("message_id")

                # Update decision as executed
                await self._mark_decision_executed(session, decision_id, send_result)

            elif decision.action == AgentAction.ESCALATE:
                # Handle escalation
                await self._handle_escalation(session, context, decision, agent)
                result["escalated"] = True

        result["draft_response"] = decision.draft_response

        return result

    async def _store_decision(
        self,
        session,
        agent_id: UUID,
        message_id: UUID,
        decision: AgentDecision,
    ) -> UUID:
        """Store agent decision."""
        decision_id = uuid4()

        await session.execute(
            text("""
                INSERT INTO mailagent_agent_decisions (
                    id, agent_id, message_id, action, confidence,
                    reasoning, response_draft, requires_approval, decision_metadata
                ) VALUES (
                    :id, :agent_id, :message_id, :action, :confidence,
                    :reasoning, :response_draft, :requires_approval, :decision_metadata
                )
            """),
            {
                "id": decision_id,
                "agent_id": agent_id,
                "message_id": message_id,
                "action": decision.action.value,
                "confidence": decision.confidence,
                "reasoning": decision.reasoning,
                "response_draft": decision.draft_response,
                "requires_approval": decision.requires_approval,
                "decision_metadata": decision.metadata,
            },
        )
        await session.commit()

        return decision_id

    async def _mark_decision_executed(self, session, decision_id: UUID, result: dict):
        """Mark decision as executed."""
        await session.execute(
            text("""
                UPDATE mailagent_agent_decisions
                SET executed = true, executed_at = NOW(), execution_result = :result
                WHERE id = :id
            """),
            {"id": decision_id, "result": result},
        )
        await session.commit()

    async def _send_response(
        self,
        session,
        context: AgentContext,
        decision: AgentDecision,
        agent: EmailAgent,
    ) -> dict:
        """Send email response."""
        try:
            # Build response message
            message = EmailMessage(
                from_address=EmailAddress(
                    address=agent.config.inbox_email,
                    name=agent.config.name,
                ),
                to_addresses=[EmailAddress(address=context.message.from_address)],
                subject=f"Re: {context.message.subject or 'Your message'}",
                body_text=decision.draft_response,
                body_html=f"<html><body>{decision.draft_response.replace(chr(10), '<br>')}</body></html>",
                in_reply_to=context.message.message_id,
                references=[context.message.message_id] if context.message.message_id else [],
            )

            # Send via send service
            send_service = await get_send_service()
            result = await send_service.send(message)

            # Store outbound message
            if result.success:
                await session.execute(
                    text("""
                        INSERT INTO mailagent_messages (
                            inbox_id, thread_id, message_id, in_reply_to,
                            from_address, to_addresses, subject, body_text, body_html,
                            direction, status, sent_at, provider_message_id
                        ) VALUES (
                            :inbox_id, (SELECT thread_id FROM mailagent_messages WHERE id = :original_id),
                            :message_id, :in_reply_to,
                            :from_address, :to_addresses, :subject, :body_text, :body_html,
                            'outbound', 'sent', NOW(), :provider_message_id
                        )
                    """),
                    {
                        "inbox_id": agent.config.inbox_id,
                        "original_id": context.message.id,
                        "message_id": result.message_id,
                        "in_reply_to": context.message.message_id,
                        "from_address": agent.config.inbox_email,
                        "to_addresses": [{"email": context.message.from_address}],
                        "subject": message.subject,
                        "body_text": decision.draft_response,
                        "body_html": message.body_html,
                        "provider_message_id": result.provider_message_id,
                    },
                )
                await session.commit()

            return {
                "success": result.success,
                "message_id": result.message_id,
                "error": result.error,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _handle_escalation(
        self,
        session,
        context: AgentContext,
        decision: AgentDecision,
        agent: EmailAgent,
    ):
        """Handle escalation to human."""
        # Store escalation record
        await session.execute(
            text("""
                UPDATE mailagent_messages
                SET status = 'escalated', labels = array_append(labels, 'escalated')
                WHERE id = :message_id
            """),
            {"message_id": context.message.id},
        )

        # Update agent stats
        await session.execute(
            text("""
                UPDATE mailagent_agents
                SET total_escalated = total_escalated + 1, last_active_at = NOW()
                WHERE id = :agent_id
            """),
            {"agent_id": agent.agent_id},
        )

        await session.commit()

        # In production, would send notification to escalation email/Slack

    async def _log_agent_error(self, session, agent_id: UUID, message_id: UUID, error: str):
        """Log agent processing error."""
        await session.execute(
            text("""
                INSERT INTO mailagent_agent_decisions (
                    agent_id, message_id, action, confidence, reasoning, metadata
                ) VALUES (
                    :agent_id, :message_id, 'error', 0, :error, :metadata
                )
            """),
            {
                "agent_id": agent_id,
                "message_id": message_id,
                "error": f"Processing error: {error}",
                "metadata": {"error": error},
            },
        )
        await session.commit()

    async def reprocess_message(self, message_id: UUID, agent_id: Optional[UUID] = None) -> dict:
        """Reprocess a message with a specific agent or all inbox agents."""
        async with async_session_factory() as session:
            # Get message details
            result = await session.execute(
                text("""
                    SELECT id, inbox_id, from_address, from_name, to_addresses,
                           subject, body_text, body_html, message_id as msg_id,
                           in_reply_to, "references"
                    FROM mailagent_messages
                    WHERE id = :message_id
                """),
                {"message_id": message_id},
            )
            row = result.fetchone()

            if not row:
                return {"status": "error", "message": "Message not found"}

            message_data = {
                "from_address": row.from_address,
                "from_name": row.from_name,
                "to_addresses": row.to_addresses,
                "subject": row.subject,
                "body_text": row.body_text,
                "body_html": row.body_html,
                "message_id": row.msg_id,
                "in_reply_to": row.in_reply_to,
                "references": row.references or [],
            }

            # Build context
            context = await self._build_context(session, row.inbox_id, message_id, message_data)

            if agent_id:
                # Process with specific agent
                agent = await create_agent_from_db(agent_id)
                if not agent:
                    return {"status": "error", "message": "Agent not found"}

                result = await self._process_with_agent(session, agent, context)
                return {"status": "processed", "agent_id": str(agent_id), **result}
            else:
                # Process with all inbox agents
                agents = await get_agents_for_inbox(row.inbox_id)
                for agent in agents:
                    result = await self._process_with_agent(session, agent, context)
                    if result["action"] != AgentAction.NO_ACTION:
                        return {"status": "processed", "agent_id": str(agent.agent_id), **result}

                return {"status": "unhandled", "message": "No agent could handle this email"}


# Global instance
_orchestrator: Optional[AgentOrchestrator] = None


def get_orchestrator() -> AgentOrchestrator:
    """Get or create the orchestrator singleton."""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
    return _orchestrator

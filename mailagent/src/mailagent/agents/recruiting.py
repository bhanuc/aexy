"""Recruiting Agent for candidate communication."""

from typing import Optional

from mailagent.agents.base import (
    EmailAgent,
    AgentAction,
    AgentDecision,
    AgentContext,
    AgentConfig,
    AgentType,
)
from mailagent.llm import LLMProvider


class RecruitingAgent(EmailAgent):
    """Agent for handling recruiting communication and candidate management."""

    AGENT_TYPE = AgentType.RECRUITING.value

    def __init__(self, config: AgentConfig, llm: LLMProvider):
        super().__init__(config, llm)

    def _default_system_prompt(self) -> str:
        return """You are a professional recruiting coordinator.

Your responsibilities:
1. Respond to candidate inquiries professionally
2. Coordinate interview scheduling
3. Acknowledge applications
4. Handle status inquiries appropriately

Guidelines:
- Be warm and professional
- Respect candidate confidentiality
- Never make promises about outcomes
- Escalate negotiation discussions
- Keep candidates informed appropriately

Response Format:
- Professional greeting
- Clear, helpful information
- Next steps when applicable
- Professional sign-off
"""

    async def process_message(self, context: AgentContext) -> AgentDecision:
        """Process incoming recruiting email."""
        analysis = await self.analyze_message(context)

        should_escalate, reason = self.should_escalate(analysis, context)
        if should_escalate:
            return AgentDecision(
                action=AgentAction.ESCALATE,
                confidence=0.9,
                reasoning=reason,
                requires_approval=True,
            )

        intent = analysis.get("intent", "question").lower()

        # Negotiations always escalate
        if "negotiat" in intent or "salary" in str(context.message.body_text).lower():
            return AgentDecision(
                action=AgentAction.ESCALATE,
                confidence=0.95,
                reasoning="Negotiation discussion requires human recruiter",
                requires_approval=True,
                metadata={"type": "negotiation", "priority": "high"},
            )

        if "application" in intent or "apply" in intent:
            return await self._handle_application(context, analysis)
        elif "status" in intent or "update" in intent:
            return await self._handle_status_inquiry(context, analysis)
        elif "schedule" in intent or "interview" in intent:
            return await self._handle_scheduling(context, analysis)
        elif "withdraw" in intent or "cancel" in intent:
            return await self._handle_withdrawal(context, analysis)
        else:
            return await self._handle_general(context, analysis)

    async def _handle_application(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle new application."""
        response = """Thank you for your interest in joining our team!

We've received your application and our team is reviewing it. We receive many applications and aim to respond within 5-7 business days.

We appreciate your patience and look forward to being in touch soon.

Best regards,
Recruiting Team"""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.90,
            reasoning="New application - sending acknowledgment",
            draft_response=response,
            requires_approval=False,
            metadata={"type": "application", "action": "log_application"},
        )

    async def _handle_status_inquiry(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle status inquiry - needs human review."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.75,
                reasoning="Status inquiry",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.75,
            reasoning="Status inquiry - needs verification before response",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "status_inquiry", "action": "check_ats"},
        )

    async def _handle_scheduling(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle interview scheduling."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.SCHEDULE,
                confidence=0.80,
                reasoning="Interview scheduling",
            ),
        )

        return AgentDecision(
            action=AgentAction.SCHEDULE,
            confidence=0.80,
            reasoning="Interview scheduling response",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "scheduling"},
        )

    async def _handle_withdrawal(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle candidate withdrawal."""
        response = """Thank you for letting us know about your decision.

While we're disappointed we won't be moving forward together, we completely understand and respect your choice. We wish you the very best in your career.

Please don't hesitate to reach out in the future if your circumstances change or if you see another opportunity that interests you.

Best of luck!

Warm regards,
Recruiting Team"""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.90,
            reasoning="Candidate withdrawal - graceful response",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "withdrawal", "action": "update_ats_withdrawn"},
        )

    async def _handle_general(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle general recruiting inquiry."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.75,
                reasoning="General recruiting inquiry",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.75,
            reasoning="General inquiry - needs review",
            draft_response=response,
            requires_approval=True,
        )

    async def generate_response(
        self, context: AgentContext, decision: AgentDecision
    ) -> str:
        """Generate response based on decision."""
        if decision.draft_response:
            return decision.draft_response

        prompt = f"""Generate a professional recruiting response.

Original message from {context.message.from_address}:
Subject: {context.message.subject}
Body: {context.message.body_text}

Decision: {decision.action.value}
Reasoning: {decision.reasoning}

Generate a professional response that:
1. Is warm but professional
2. Doesn't make promises about outcomes
3. Provides helpful information
4. Maintains appropriate confidentiality"""

        result = await self.llm.generate_json(prompt)
        return result.get("response", "Thank you for reaching out. Our team will review and get back to you soon.")

"""Onboarding Agent for new user/customer onboarding."""

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


class OnboardingAgent(EmailAgent):
    """Agent for handling customer onboarding and guiding new users."""

    AGENT_TYPE = AgentType.ONBOARDING.value

    def __init__(self, config: AgentConfig, llm: LLMProvider):
        super().__init__(config, llm)

    def _default_system_prompt(self) -> str:
        return """You are a helpful onboarding specialist.

Your responsibilities:
1. Guide new users through setup
2. Answer questions about getting started
3. Provide resources and documentation
4. Identify and address blockers quickly

Guidelines:
- Be welcoming and encouraging
- Break down steps clearly
- Anticipate common questions
- Celebrate progress
- Escalate frustrated users quickly

Response Format:
- Warm greeting
- Direct answer to their question
- Clear next steps
- Offer additional help
"""

    async def process_message(self, context: AgentContext) -> AgentDecision:
        """Process incoming onboarding email."""
        analysis = await self.analyze_message(context)

        # Check for escalation
        should_escalate, reason = self.should_escalate(analysis, context)
        if should_escalate:
            return AgentDecision(
                action=AgentAction.ESCALATE,
                confidence=0.9,
                reasoning=reason,
                requires_approval=True,
            )

        # Check sentiment - frustrated users need attention
        if analysis.get("sentiment") == "negative":
            return await self._handle_frustrated_user(context, analysis)

        intent = analysis.get("intent", "question").lower()

        if "question" in intent:
            return await self._handle_question(context, analysis)
        elif "stuck" in intent or "help" in intent:
            return await self._handle_stuck_user(context, analysis)
        elif "feedback" in intent:
            return await self._handle_feedback(context, analysis)
        else:
            return await self._handle_general(context, analysis)

    async def _handle_frustrated_user(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle frustrated user - high priority."""
        response = await self._generate_empathetic_response(context, analysis)

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.85,
            reasoning="User appears frustrated - providing empathetic response",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "frustrated", "priority": "high"},
        )

    async def _handle_question(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle general question."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.85,
                reasoning="Onboarding question",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.85,
            reasoning="Answering onboarding question",
            draft_response=response,
            requires_approval=analysis.get("confidence", 0.8) < self.config.require_approval_below,
            metadata={"type": "question"},
        )

    async def _handle_stuck_user(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle user who is stuck."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.80,
                reasoning="User stuck during onboarding",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.80,
            reasoning="User stuck - providing guidance",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "stuck"},
        )

    async def _handle_feedback(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle feedback."""
        response = """Thank you so much for taking the time to share your feedback!

We really appreciate hearing from users like you - it helps us improve for everyone.

I've noted your feedback and shared it with our product team. Is there anything else I can help you with?

Best regards"""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.90,
            reasoning="User provided feedback",
            draft_response=response,
            requires_approval=False,
            metadata={"type": "feedback", "action": "log_feedback"},
        )

    async def _handle_general(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle general onboarding email."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.75,
                reasoning="General onboarding inquiry",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.75,
            reasoning="General onboarding inquiry",
            draft_response=response,
            requires_approval=True,
        )

    async def _generate_empathetic_response(
        self, context: AgentContext, analysis: dict
    ) -> str:
        """Generate empathetic response for frustrated user."""
        prompt = f"""A new user is frustrated during onboarding. Generate an empathetic response.

Their email:
Subject: {context.message.subject}
Body: {context.message.body_text}

Guidelines:
- Acknowledge their frustration sincerely
- Apologize for the difficulty
- Provide clear, helpful solution
- Offer additional support (call, screen share)
- Be warm and supportive

Generate only the email response body."""

        result = await self.llm.generate_json(prompt)
        return result.get("response", "I'm sorry you're having trouble. Let me help you resolve this right away.")

    async def generate_response(
        self, context: AgentContext, decision: AgentDecision
    ) -> str:
        """Generate response based on decision."""
        if decision.draft_response:
            return decision.draft_response

        prompt = f"""Generate a helpful onboarding response.

Original message from {context.message.from_address}:
Subject: {context.message.subject}
Body: {context.message.body_text}

Decision: {decision.action.value}
Reasoning: {decision.reasoning}

Generate a warm, helpful response that:
1. Addresses their specific question/issue
2. Provides clear guidance
3. Encourages them on their progress
4. Offers additional help"""

        result = await self.llm.generate_json(prompt)
        return result.get("response", "Thank you for reaching out! I'm here to help you get started.")

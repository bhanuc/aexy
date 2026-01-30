"""Newsletter Agent for managing subscriptions and reader engagement."""

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


class NewsletterAgent(EmailAgent):
    """Agent for handling newsletter subscriptions and reader engagement."""

    AGENT_TYPE = AgentType.NEWSLETTER.value

    def __init__(self, config: AgentConfig, llm: LLMProvider):
        super().__init__(config, llm)

    def _default_system_prompt(self) -> str:
        return """You are a friendly newsletter manager.

Your responsibilities:
1. Handle subscription requests
2. Process unsubscribes gracefully
3. Respond to reader feedback
4. Address deliverability issues

Guidelines:
- Be friendly and appreciative
- Make unsubscribing easy
- Thank readers for engagement
- Handle complaints gracefully

Response Format:
- Warm greeting
- Address their request
- Confirm action taken
- Thank them
"""

    async def process_message(self, context: AgentContext) -> AgentDecision:
        """Process incoming newsletter email."""
        analysis = await self.analyze_message(context)

        should_escalate, reason = self.should_escalate(analysis, context)
        if should_escalate:
            return AgentDecision(
                action=AgentAction.ESCALATE,
                confidence=0.9,
                reasoning=reason,
                requires_approval=True,
            )

        body_lower = str(context.message.body_text).lower()
        intent = analysis.get("intent", "").lower()

        if "unsubscribe" in body_lower or "unsubscribe" in intent:
            return await self._handle_unsubscribe(context, analysis)
        elif "subscribe" in body_lower or "subscribe" in intent:
            return await self._handle_subscribe(context, analysis)
        elif "not receiving" in body_lower or "delivery" in intent:
            return await self._handle_deliverability(context, analysis)
        elif analysis.get("sentiment") == "positive":
            return await self._handle_praise(context, analysis)
        elif analysis.get("sentiment") == "negative":
            return await self._handle_complaint(context, analysis)
        else:
            return await self._handle_feedback(context, analysis)

    async def _handle_subscribe(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle subscription request."""
        response = """Welcome! Thank you for subscribing.

We're excited to have you join our community. You'll start receiving our newsletter with the next edition.

In the meantime, feel free to reply to any newsletter if you have questions or feedback.

Best regards"""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.95,
            reasoning="New subscription - sending welcome",
            draft_response=response,
            requires_approval=False,
            metadata={"type": "subscribe", "action": "add_to_list"},
        )

    async def _handle_unsubscribe(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle unsubscribe request."""
        response = """We're sorry to see you go!

You've been unsubscribed and won't receive any more emails from us.

If you unsubscribed by mistake or change your mind, you're always welcome back.

Thank you for being a reader. We wish you all the best!"""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.95,
            reasoning="Unsubscribe request - confirming removal",
            draft_response=response,
            requires_approval=False,
            metadata={"type": "unsubscribe", "action": "remove_from_list"},
        )

    async def _handle_deliverability(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle deliverability issues."""
        response = """Thank you for letting us know about the delivery issues!

Here are a few things that might help:

1. Check your spam/junk folder - our emails might be landing there
2. Add our email address to your contacts
3. If you use Gmail, check the Promotions tab
4. Ask your IT team to whitelist our sending domain

If you're still having issues after trying these steps, please reply with your email provider (Gmail, Outlook, etc.) and we'll investigate further.

Thank you for your patience!"""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.90,
            reasoning="Deliverability issue reported",
            draft_response=response,
            requires_approval=False,
            metadata={"type": "deliverability", "action": "investigate"},
        )

    async def _handle_praise(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle positive feedback."""
        response = """Thank you so much for your kind words!

Messages like yours make all the effort worthwhile. We're thrilled that you're enjoying our newsletter.

If there's ever a specific topic you'd like us to cover, just let us know!

Thanks for being a wonderful reader."""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.90,
            reasoning="Positive feedback - thanking reader",
            draft_response=response,
            requires_approval=False,
            metadata={"type": "praise", "action": "log_positive_feedback"},
        )

    async def _handle_complaint(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle complaint - needs review."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.80,
                reasoning="Reader complaint",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.80,
            reasoning="Reader complaint - needs review before sending",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "complaint", "priority": "high"},
        )

    async def _handle_feedback(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle general feedback."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.85,
                reasoning="Reader feedback",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.85,
            reasoning="Reader feedback - acknowledging",
            draft_response=response,
            requires_approval=analysis.get("sentiment") == "negative",
            metadata={"type": "feedback", "action": "log_feedback"},
        )

    async def generate_response(
        self, context: AgentContext, decision: AgentDecision
    ) -> str:
        """Generate response based on decision."""
        if decision.draft_response:
            return decision.draft_response

        prompt = f"""Generate a friendly newsletter response.

Original message from {context.message.from_address}:
Subject: {context.message.subject}
Body: {context.message.body_text}

Decision: {decision.action.value}
Reasoning: {decision.reasoning}

Generate a friendly response that:
1. Thanks them for engagement
2. Addresses their specific feedback/concern
3. Is warm and appreciative"""

        result = await self.llm.generate_json(prompt)
        return result.get("response", "Thank you for reaching out! We appreciate your feedback.")

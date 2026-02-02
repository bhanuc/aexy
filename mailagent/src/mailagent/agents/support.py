"""Customer Support Email Agent."""

from typing import Optional

from mailagent.agents.base import (
    EmailAgent,
    AgentAction,
    AgentDecision,
    AgentContext,
    AgentConfig,
)
from mailagent.llm import LLMProvider


class SupportAgent(EmailAgent):
    """AI agent for customer support emails."""

    AGENT_TYPE = "support"

    def __init__(self, config: AgentConfig, llm: LLMProvider):
        super().__init__(config, llm)

    def _default_system_prompt(self) -> str:
        return """You are a helpful customer support agent.

Your responsibilities:
1. Understand customer issues and questions
2. Provide accurate, helpful responses
3. Escalate complex issues to human agents when needed
4. Maintain a friendly, professional tone

Guidelines:
- Always acknowledge the customer's concern first
- If you don't know the answer, say so and offer to escalate
- Keep responses concise but complete
- Include relevant next steps when appropriate
- Never make promises about timelines you can't guarantee
- For billing/account issues, be extra careful and consider escalating

Response Format:
- Use a warm greeting
- Address their specific issue
- Provide clear information or next steps
- Offer additional help
- Sign off professionally
"""

    async def process_message(self, context: AgentContext) -> AgentDecision:
        """Process incoming support message."""

        # 1. Analyze the message
        analysis = await self.analyze_message(context)

        # 2. Check for escalation conditions
        should_escalate, escalation_reason = self.should_escalate(analysis, context)

        if should_escalate:
            return AgentDecision(
                action=AgentAction.ESCALATE,
                confidence=0.95,
                reasoning=escalation_reason,
                metadata={
                    "escalation_reason": escalation_reason,
                    "analysis": analysis,
                    "escalate_to": self.config.escalation_email,
                }
            )

        # 3. Check if response is needed
        if not analysis.get("requires_response", True):
            return AgentDecision(
                action=AgentAction.NO_ACTION,
                confidence=analysis.get("confidence", 0.8),
                reasoning="Message does not require a response",
                metadata={"analysis": analysis}
            )

        # 4. Classify the issue type
        classification = await self._classify_issue(context, analysis)

        # 5. Search knowledge base for relevant info
        kb_results = await self._search_knowledge_base(context, classification)

        # 6. Generate response
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.REPLY,
                confidence=classification.get("confidence", 0.7),
                reasoning=classification.get("reasoning", ""),
            ),
            classification=classification,
            kb_results=kb_results,
        )

        confidence = classification.get("confidence", 0.7)

        # 7. Determine if approval needed
        requires_approval = confidence < self.config.require_approval_below

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=confidence,
            reasoning=classification.get("reasoning", "Responding to customer inquiry"),
            draft_response=response,
            requires_approval=requires_approval,
            metadata={
                "analysis": analysis,
                "classification": classification,
                "kb_articles_used": len(kb_results),
            }
        )

    async def generate_response(
        self,
        context: AgentContext,
        decision: AgentDecision,
        classification: Optional[dict] = None,
        kb_results: Optional[list[str]] = None,
    ) -> str:
        """Generate support response."""

        classification = classification or {}
        kb_results = kb_results or context.knowledge_results

        # Build context for response generation
        conversation_context = context.get_conversation_summary()

        prompt = f"""Generate a customer support email response.

Customer's Email:
From: {context.message.from_address}
Subject: {context.message.subject}
Body:
{context.message.body_text}

Issue Classification:
- Category: {classification.get('category', 'general')}
- Sentiment: {classification.get('sentiment', 'neutral')}
- Urgency: {classification.get('urgency', 'medium')}

{f"Previous Conversation:{chr(10)}{conversation_context}" if conversation_context else ""}

{f"Relevant Knowledge Base Information:{chr(10)}{chr(10).join(kb_results)}" if kb_results else ""}

Requirements:
1. Start with a warm, empathetic greeting using their name if available
2. Acknowledge their specific concern
3. Provide a clear, helpful response
4. Include specific next steps if applicable
5. Offer additional assistance
6. Sign off as "The Support Team"

Generate the response in HTML format (use <p> tags, <ul>/<li> for lists if needed).
Keep it concise but complete. Be helpful and professional."""

        response = await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

        return response

    async def _classify_issue(self, context: AgentContext, analysis: dict) -> dict:
        """Classify the support issue in detail."""

        prompt = f"""Classify this customer support issue:

Subject: {context.message.subject}
Body: {context.message.body_text}

Initial Analysis: {analysis}

Classify with:
1. category: (billing, technical, account, product, shipping, returns, general, complaint, feedback, feature_request)
2. sub_category: More specific classification
3. sentiment: (positive, neutral, negative, frustrated, angry)
4. urgency: (low, medium, high, critical)
5. complexity: (simple, moderate, complex)
6. can_auto_resolve: true/false - Can this be resolved with a standard response?
7. confidence: 0.0-1.0 - Your confidence in this classification
8. reasoning: Brief explanation of your classification
9. suggested_response_type: (informational, troubleshooting, apology, escalation, confirmation)

Return valid JSON only."""

        return await self.llm.generate_json(prompt)

    async def _search_knowledge_base(
        self,
        context: AgentContext,
        classification: dict,
    ) -> list[str]:
        """Search knowledge base for relevant information.

        This is a placeholder - in production, this would query a vector DB.
        """
        # For now, return any pre-loaded knowledge from context
        return context.knowledge_results

    async def handle_follow_up(
        self,
        context: AgentContext,
        original_decision: AgentDecision,
    ) -> AgentDecision:
        """Handle a follow-up message in an ongoing conversation."""

        # Analyze if issue is resolved
        prompt = f"""Analyze this follow-up message in a support conversation:

Previous Exchange Summary:
{context.get_conversation_summary()}

New Message:
{context.message.body_text}

Determine:
1. is_resolved: Is the customer's issue resolved?
2. is_satisfied: Does the customer seem satisfied?
3. needs_more_help: Do they need additional assistance?
4. new_issue: Is this a new/different issue?
5. action_needed: What action should we take? (thank_close, continue_helping, escalate, no_action)

Return valid JSON."""

        follow_up_analysis = await self.llm.generate_json(prompt)

        if follow_up_analysis.get("is_resolved") and follow_up_analysis.get("is_satisfied"):
            # Send a thank you and close
            response = await self._generate_closing_response(context)
            return AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.9,
                reasoning="Issue resolved, sending thank you",
                draft_response=response,
                metadata={"follow_up_analysis": follow_up_analysis}
            )

        if follow_up_analysis.get("new_issue"):
            # Treat as new conversation
            return await self.process_message(context)

        if follow_up_analysis.get("action_needed") == "escalate":
            return AgentDecision(
                action=AgentAction.ESCALATE,
                confidence=0.85,
                reasoning="Customer still not satisfied after follow-up",
                metadata={"follow_up_analysis": follow_up_analysis}
            )

        # Continue helping
        return await self.process_message(context)

    async def _generate_closing_response(self, context: AgentContext) -> str:
        """Generate a thank you/closing response."""

        prompt = f"""Generate a brief, warm closing response for a resolved support ticket.

Customer: {context.message.from_address}
Their last message: {context.message.body_text}

Requirements:
- Thank them for their patience
- Confirm the issue is resolved
- Invite them to reach out if they need anything else
- Keep it short (2-3 sentences)

Generate in HTML format."""

        return await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

"""Sales Development Email Agent."""

from typing import Optional

from mailagent.agents.base import (
    EmailAgent,
    AgentAction,
    AgentDecision,
    AgentContext,
    AgentConfig,
)
from mailagent.llm import LLMProvider


class SalesAgent(EmailAgent):
    """AI agent for sales outreach and lead nurturing."""

    AGENT_TYPE = "sales"

    def __init__(self, config: AgentConfig, llm: LLMProvider):
        super().__init__(config, llm)
        self.objection_playbook = config.workspace_context.get("objection_playbook", {})
        self.product_info = config.workspace_context.get("product_info", "")
        self.pricing_info = config.workspace_context.get("pricing_info", "")

    def _default_system_prompt(self) -> str:
        return f"""You are a sales development representative.

Your goal is to nurture leads and book meetings while being helpful, not pushy.

Responsibilities:
1. Respond to inbound inquiries promptly and helpfully
2. Follow up on outreach sequences appropriately
3. Handle objections professionally and empathetically
4. Qualify leads through conversation
5. Book discovery calls when appropriate

Tone Guidelines:
- Professional but conversational and warm
- Curious about their business challenges
- Focused on value and solving problems, not features
- Never desperate, pushy, or salesy
- Respectful of their time and decisions

{f"Product Information:{chr(10)}{self.product_info}" if self.product_info else ""}

{f"Pricing Overview:{chr(10)}{self.pricing_info}" if self.pricing_info else ""}

Remember: Your job is to help them, not to sell to them. If our product isn't a fit, it's okay to say so.
"""

    async def process_message(self, context: AgentContext) -> AgentDecision:
        """Process incoming sales-related message."""

        # 1. Analyze the lead's response
        lead_analysis = await self._analyze_lead_response(context)

        # 2. Determine best action based on intent
        intent = lead_analysis.get("intent", "unclear")

        if intent == "meeting_request":
            return AgentDecision(
                action=AgentAction.SCHEDULE,
                confidence=0.95,
                reasoning="Lead explicitly requested a meeting",
                metadata={
                    "meeting_type": "discovery_call",
                    "duration": 30,
                    "lead_analysis": lead_analysis,
                }
            )

        if intent == "not_interested":
            # Gracefully accept and update CRM
            response = await self._generate_graceful_exit(context, lead_analysis)
            return AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.9,
                reasoning="Lead not interested - sending graceful response",
                draft_response=response,
                requires_approval=False,
                metadata={
                    "crm_action": "mark_not_interested",
                    "reason": lead_analysis.get("decline_reason"),
                    "lead_analysis": lead_analysis,
                }
            )

        if intent == "pricing_question":
            response = await self._handle_pricing_question(context, lead_analysis)
            return AgentDecision(
                action=AgentAction.REPLY,
                confidence=lead_analysis.get("confidence", 0.7),
                reasoning="Responding to pricing inquiry",
                draft_response=response,
                requires_approval=True,  # Always review pricing responses
                metadata={"lead_analysis": lead_analysis}
            )

        if intent == "objection":
            response = await self._handle_objection(context, lead_analysis)
            confidence = lead_analysis.get("confidence", 0.7)
            return AgentDecision(
                action=AgentAction.REPLY,
                confidence=confidence,
                reasoning=f"Handling objection: {lead_analysis.get('objection_type')}",
                draft_response=response,
                requires_approval=confidence < 0.85,
                metadata={"lead_analysis": lead_analysis}
            )

        if intent == "positive_interest":
            response = await self._nurture_interested_lead(context, lead_analysis)
            return AgentDecision(
                action=AgentAction.REPLY,
                confidence=0.85,
                reasoning="Lead showing interest - nurturing conversation",
                draft_response=response,
                requires_approval=False,
                metadata={"lead_analysis": lead_analysis}
            )

        if intent == "question":
            response = await self._answer_question(context, lead_analysis)
            return AgentDecision(
                action=AgentAction.REPLY,
                confidence=lead_analysis.get("confidence", 0.75),
                reasoning="Answering lead's question",
                draft_response=response,
                requires_approval=lead_analysis.get("confidence", 0.75) < 0.8,
                metadata={"lead_analysis": lead_analysis}
            )

        # Default: Request approval for unclear intent
        response = await self.generate_response(context, AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.5,
            reasoning="Unclear intent",
        ))
        return AgentDecision(
            action=AgentAction.REQUEST_APPROVAL,
            confidence=0.5,
            reasoning="Unclear lead intent - requesting human review",
            draft_response=response,
            requires_approval=True,
            metadata={"lead_analysis": lead_analysis}
        )

    async def generate_response(
        self,
        context: AgentContext,
        decision: AgentDecision,
        **kwargs,
    ) -> str:
        """Generate a sales response."""

        prompt = f"""Generate a sales email response.

Their Message:
From: {context.message.from_address}
Subject: {context.message.subject}
Body:
{context.message.body_text}

{f"Previous Conversation:{chr(10)}{context.get_conversation_summary()}" if context.thread_messages else ""}

Requirements:
- Be conversational and helpful, not salesy
- Address their specific points or questions
- Focus on value, not features
- End with a soft call-to-action (question, not demand)
- Keep it concise (under 150 words)

Generate the response in HTML format."""

        return await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

    async def _analyze_lead_response(self, context: AgentContext) -> dict:
        """Analyze the lead's response for intent and sentiment."""

        prompt = f"""Analyze this sales email reply:

Our Previous Message: {context.thread_messages[-1].body_text if context.thread_messages else 'Initial outreach'}

Their Reply:
Subject: {context.message.subject}
Body: {context.message.body_text}

Analyze and return JSON with:
1. intent: (meeting_request, pricing_question, feature_question, objection, not_interested, positive_interest, question, unclear)
2. objection_type: If objection, what type? (budget, timing, authority, need, competitor, null)
3. decline_reason: If not interested, why? (string or null)
4. lead_temperature: (hot, warm, cold)
5. sentiment: (positive, neutral, skeptical, negative)
6. key_points: List of main points they raised
7. questions_asked: List of questions they asked
8. buying_signals: List of any buying signals detected
9. confidence: 0.0-1.0 for this analysis

Return valid JSON only."""

        return await self.llm.generate_json(prompt)

    async def _handle_objection(self, context: AgentContext, analysis: dict) -> str:
        """Handle a sales objection."""

        objection_type = analysis.get("objection_type", "general")
        playbook_guidance = self.objection_playbook.get(objection_type, "")

        prompt = f"""Handle this sales objection:

Their Message: {context.message.body_text}

Objection Type: {objection_type}
{f"Playbook Guidance: {playbook_guidance}" if playbook_guidance else ""}

Guidelines:
1. Acknowledge their concern genuinely
2. Don't be defensive or dismissive
3. Address the underlying concern, not just the surface objection
4. Provide relevant proof points or examples if helpful
5. Pivot back to value without being pushy
6. End with an open question, not a pitch

Generate a warm, helpful response in HTML format. Keep it under 120 words."""

        return await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

    async def _handle_pricing_question(self, context: AgentContext, analysis: dict) -> str:
        """Handle pricing-related questions."""

        prompt = f"""Respond to this pricing question:

Their Question: {context.message.body_text}

{f"Pricing Information:{chr(10)}{self.pricing_info}" if self.pricing_info else "Note: We don't have specific pricing info loaded."}

Guidelines:
1. Be transparent about pricing when possible
2. Connect pricing to value delivered
3. If pricing varies, explain what factors affect it
4. Offer to discuss their specific needs
5. Don't be evasive - that erodes trust

Generate response in HTML format."""

        return await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

    async def _nurture_interested_lead(self, context: AgentContext, analysis: dict) -> str:
        """Nurture a lead showing positive interest."""

        buying_signals = analysis.get("buying_signals", [])
        questions = analysis.get("questions_asked", [])

        prompt = f"""Nurture this interested lead:

Their Message: {context.message.body_text}

Buying Signals Detected: {buying_signals}
Questions They Asked: {questions}

Guidelines:
1. Match their enthusiasm appropriately
2. Answer any questions they asked
3. Provide additional value (insight, resource, example)
4. Naturally guide toward next step (call/demo)
5. Don't rush them - build the relationship

Generate response in HTML format. Keep conversational."""

        return await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

    async def _answer_question(self, context: AgentContext, analysis: dict) -> str:
        """Answer a question from a lead."""

        questions = analysis.get("questions_asked", [context.message.body_text])

        prompt = f"""Answer this lead's question(s):

Their Message: {context.message.body_text}
Questions: {questions}

{f"Product Info: {self.product_info}" if self.product_info else ""}

Guidelines:
1. Answer their specific questions clearly
2. Be honest if you don't know something
3. Add relevant context that might help
4. End with an invitation to ask more or chat

Generate response in HTML format."""

        return await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

    async def _generate_graceful_exit(self, context: AgentContext, analysis: dict) -> str:
        """Generate a graceful response when lead isn't interested."""

        reason = analysis.get("decline_reason", "")

        prompt = f"""Generate a graceful response to a lead who isn't interested.

Their Message: {context.message.body_text}
Reason (if given): {reason}

Guidelines:
1. Thank them for their time and honesty
2. Respect their decision completely
3. Leave the door open for the future without being pushy
4. Keep it very brief (2-3 sentences max)

Generate response in HTML format."""

        return await self.llm.generate_simple(
            prompt,
            system_prompt=self.get_system_prompt(),
        )

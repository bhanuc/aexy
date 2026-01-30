"""Scheduling Agent for calendar and meeting management."""

from datetime import datetime, timedelta
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


class SchedulingAgent(EmailAgent):
    """Agent for handling scheduling requests and calendar management."""

    AGENT_TYPE = AgentType.SCHEDULING.value

    def __init__(self, config: AgentConfig, llm: LLMProvider):
        super().__init__(config, llm)
        self._default_duration = config.working_hours.get("default_meeting_duration", 30) if config.working_hours else 30
        self._buffer_minutes = 15

    def _default_system_prompt(self) -> str:
        return """You are a professional scheduling assistant.

Your responsibilities:
1. Understand meeting and scheduling requests
2. Propose available time slots
3. Handle reschedules and cancellations gracefully
4. Coordinate between parties

Guidelines:
- Always confirm time zones
- Propose multiple options when possible
- Be flexible and accommodating
- Acknowledge urgency when expressed
- Keep responses concise and actionable

Response Format:
- Acknowledge the request
- Provide available times or confirm the request
- Ask for any missing information
- Include calendar invite details when confirming
"""

    async def process_message(self, context: AgentContext) -> AgentDecision:
        """Process incoming scheduling request."""
        # Analyze the message
        analysis = await self.analyze_message(context)

        # Check for escalation conditions
        should_escalate, reason = self.should_escalate(analysis, context)
        if should_escalate:
            return AgentDecision(
                action=AgentAction.ESCALATE,
                confidence=0.9,
                reasoning=reason,
                requires_approval=True,
            )

        # Determine intent
        intent = analysis.get("intent", "").lower()

        if "cancel" in intent:
            return await self._handle_cancellation(context, analysis)
        elif "reschedule" in intent or "change" in intent:
            return await self._handle_reschedule(context, analysis)
        elif "confirm" in intent:
            return await self._handle_confirmation(context, analysis)
        else:
            return await self._handle_new_meeting(context, analysis)

    async def _handle_new_meeting(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle new meeting request."""
        # Generate available slots
        available_slots = self._get_available_slots()

        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.SCHEDULE,
                confidence=0.85,
                reasoning="New meeting request - proposing available times",
                metadata={"available_slots": available_slots},
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.85,
            reasoning="New meeting request - proposing available times",
            draft_response=response,
            requires_approval=analysis.get("confidence", 0.8) < self.config.require_approval_below,
            metadata={"type": "new_meeting", "slots": available_slots},
        )

    async def _handle_reschedule(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle reschedule request."""
        response = await self.generate_response(
            context,
            AgentDecision(
                action=AgentAction.SCHEDULE,
                confidence=0.80,
                reasoning="Reschedule request",
            ),
        )

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.80,
            reasoning="Reschedule request - proposing alternatives",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "reschedule"},
        )

    async def _handle_cancellation(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle cancellation request."""
        response = f"""Thank you for letting me know.

I've noted the cancellation. Would you like to reschedule for another time?

If so, please let me know your availability and I'll find a time that works.

Best regards"""

        return AgentDecision(
            action=AgentAction.REPLY,
            confidence=0.90,
            reasoning="Cancellation acknowledged",
            draft_response=response,
            requires_approval=True,
            metadata={"type": "cancel"},
        )

    async def _handle_confirmation(
        self, context: AgentContext, analysis: dict
    ) -> AgentDecision:
        """Handle meeting confirmation."""
        response = f"""Great! The meeting is confirmed.

I'll send a calendar invite shortly with all the details. Looking forward to it!

Best regards"""

        return AgentDecision(
            action=AgentAction.SCHEDULE,
            confidence=0.90,
            reasoning="Meeting confirmed - creating calendar event",
            draft_response=response,
            requires_approval=False,
            metadata={"type": "confirm", "create_event": True},
        )

    async def generate_response(
        self, context: AgentContext, decision: AgentDecision
    ) -> str:
        """Generate response based on decision."""
        if decision.draft_response:
            return decision.draft_response

        slots = decision.metadata.get("available_slots", self._get_available_slots())
        slots_text = "\n".join(f"- {slot['day']} at {slot['time']}" for slot in slots)

        prompt = f"""Generate a professional scheduling response.

Original message from {context.message.from_address}:
Subject: {context.message.subject}
Body: {context.message.body_text}

Decision: {decision.action.value}
Reasoning: {decision.reasoning}

Available slots:
{slots_text}

Generate a helpful, professional response that:
1. Acknowledges their request
2. Proposes available times or confirms
3. Is concise and actionable"""

        response = await self.llm.generate_json(prompt)
        return response.get("response", f"Here are some available times:\n{slots_text}")

    def _get_available_slots(self) -> list[dict]:
        """Get available time slots."""
        available = []
        base_time = datetime.now().replace(hour=10, minute=0, second=0)

        for day_offset in range(1, 5):
            slot_time = base_time + timedelta(days=day_offset)
            if slot_time.weekday() < 5:
                available.append({
                    "start": slot_time.isoformat(),
                    "end": (slot_time + timedelta(minutes=self._default_duration)).isoformat(),
                    "day": slot_time.strftime("%A, %B %d"),
                    "time": slot_time.strftime("%I:%M %p"),
                })

        return available[:3]

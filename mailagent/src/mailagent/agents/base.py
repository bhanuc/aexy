"""Base email agent class and core types."""

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel

if TYPE_CHECKING:
    from mailagent.llm import LLMProvider


class AgentType(str, Enum):
    """Types of email agents."""
    SUPPORT = "support"
    SALES = "sales"
    SCHEDULING = "scheduling"
    ONBOARDING = "onboarding"
    RECRUITING = "recruiting"
    NEWSLETTER = "newsletter"
    CUSTOM = "custom"


class AgentAction(str, Enum):
    """Possible actions an agent can take."""
    REPLY = "reply"
    FORWARD = "forward"
    ESCALATE = "escalate"
    SCHEDULE = "schedule"
    CREATE_TASK = "create_task"
    UPDATE_CRM = "update_crm"
    NO_ACTION = "no_action"
    WAIT = "wait"
    REQUEST_APPROVAL = "request_approval"


class AgentDecision(BaseModel):
    """A decision made by an agent."""
    action: AgentAction
    confidence: float  # 0.0 - 1.0
    reasoning: str
    draft_response: Optional[str] = None
    metadata: dict = {}
    requires_approval: bool = False

    def should_auto_execute(self, threshold: float = 0.8) -> bool:
        """Check if decision should auto-execute based on confidence."""
        return self.confidence >= threshold and not self.requires_approval


class MessageData(BaseModel):
    """Message data for agent context."""
    id: UUID
    from_address: str
    from_name: Optional[str] = None
    to_addresses: list[dict]
    subject: Optional[str] = None
    body_text: Optional[str] = None
    body_html: Optional[str] = None
    received_at: Optional[datetime] = None
    thread_id: Optional[UUID] = None
    message_id: Optional[str] = None


class ContactData(BaseModel):
    """Contact data for agent context."""
    email: str
    name: Optional[str] = None
    company: Optional[str] = None
    title: Optional[str] = None
    previous_interactions: int = 0
    tags: list[str] = []
    metadata: dict = {}


class AgentContext(BaseModel):
    """Context provided to agent for decision making."""
    message: MessageData
    thread_messages: list[MessageData] = []
    contact: Optional[ContactData] = None
    knowledge_results: list[str] = []
    agent_config: dict = {}
    workspace_context: dict = {}

    def get_conversation_summary(self, max_messages: int = 5) -> str:
        """Get a summary of the conversation for context."""
        messages = self.thread_messages[-max_messages:] if self.thread_messages else []
        summary_parts = []

        for msg in messages:
            direction = "Them" if msg.from_address != self.agent_config.get("inbox_email") else "Us"
            summary_parts.append(f"{direction}: {msg.body_text[:200] if msg.body_text else '(no text)'}...")

        return "\n---\n".join(summary_parts)


class AgentConfig(BaseModel):
    """Configuration for an email agent."""
    id: UUID
    name: str
    agent_type: str
    inbox_id: UUID
    inbox_email: str

    # LLM settings
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.0-flash"
    temperature: float = 0.7
    max_tokens: int = 2000

    # Behavior
    auto_respond: bool = True
    confidence_threshold: float = 0.7
    require_approval_below: float = 0.8
    max_daily_responses: int = 100
    response_delay_minutes: int = 5

    # Working hours (None = 24/7)
    working_hours: Optional[dict] = None

    # Escalation
    escalation_email: Optional[str] = None
    escalation_slack: Optional[str] = None
    escalation_conditions: list[str] = []

    # Custom
    system_prompt: Optional[str] = None
    custom_instructions: Optional[str] = None


class EmailAgent(ABC):
    """Base class for all email agents."""

    AGENT_TYPE: str = "base"

    def __init__(
        self,
        config: AgentConfig,
        llm: "LLMProvider",
    ):
        self.config = config
        self.llm = llm

    @property
    def agent_id(self) -> UUID:
        return self.config.id

    @property
    def inbox_id(self) -> UUID:
        return self.config.inbox_id

    @abstractmethod
    async def process_message(self, context: AgentContext) -> AgentDecision:
        """Process incoming message and decide on action.

        Args:
            context: Full context about the message and conversation

        Returns:
            AgentDecision with action, confidence, and optional response
        """
        pass

    @abstractmethod
    async def generate_response(
        self,
        context: AgentContext,
        decision: AgentDecision,
    ) -> str:
        """Generate email response based on decision.

        Args:
            context: Full context about the message
            decision: The decision that was made

        Returns:
            HTML email content
        """
        pass

    def get_system_prompt(self) -> str:
        """Get the system prompt for this agent.

        Override in subclasses for specialized prompts.
        """
        base_prompt = self.config.system_prompt or self._default_system_prompt()

        if self.config.custom_instructions:
            base_prompt += f"\n\nAdditional Instructions:\n{self.config.custom_instructions}"

        return base_prompt

    def _default_system_prompt(self) -> str:
        """Default system prompt. Override in subclasses."""
        return f"""You are an AI email assistant named {self.config.name}.
Your job is to help manage email communications professionally and helpfully.

Guidelines:
- Be professional and courteous
- Provide accurate, helpful information
- If you're unsure, say so
- Keep responses concise but complete
"""

    async def analyze_message(self, context: AgentContext) -> dict:
        """Analyze incoming message for intent, sentiment, etc."""
        prompt = f"""Analyze this email message:

From: {context.message.from_address}
Subject: {context.message.subject}
Body: {context.message.body_text}

Provide analysis as JSON with:
- intent: The primary intent (question, request, complaint, information, greeting, etc.)
- sentiment: positive, negative, or neutral
- urgency: low, medium, high, or critical
- topics: List of main topics mentioned
- requires_response: true/false
- confidence: 0.0-1.0 for this analysis

Return valid JSON only."""

        return await self.llm.generate_json(prompt)

    def is_within_working_hours(self) -> bool:
        """Check if current time is within configured working hours."""
        if not self.config.working_hours:
            return True

        now = datetime.now(timezone.utc)
        tz_name = self.config.working_hours.get("timezone", "UTC")

        try:
            from zoneinfo import ZoneInfo
            local_now = now.astimezone(ZoneInfo(tz_name))
        except Exception:
            local_now = now

        start_hour = int(self.config.working_hours.get("start", "09:00").split(":")[0])
        end_hour = int(self.config.working_hours.get("end", "17:00").split(":")[0])

        return start_hour <= local_now.hour < end_hour

    def should_escalate(self, analysis: dict, context: AgentContext) -> tuple[bool, str]:
        """Check if message should be escalated based on conditions.

        Returns:
            Tuple of (should_escalate, reason)
        """
        # Check configured escalation conditions
        for condition in self.config.escalation_conditions:
            condition_lower = condition.lower()

            # Check sentiment
            if "angry" in condition_lower and analysis.get("sentiment") == "negative":
                if analysis.get("urgency") in ["high", "critical"]:
                    return True, "Customer sentiment is angry/negative with high urgency"

            # Check for specific keywords
            if "billing" in condition_lower:
                if "billing" in str(context.message.body_text).lower():
                    return True, "Billing mentioned - requires human review"

            if "refund" in condition_lower:
                if "refund" in str(context.message.body_text).lower():
                    return True, "Refund mentioned - requires human review"

            if "legal" in condition_lower:
                if any(word in str(context.message.body_text).lower()
                       for word in ["legal", "lawyer", "lawsuit", "attorney"]):
                    return True, "Legal matter mentioned - requires human review"

        # Check urgency
        if analysis.get("urgency") == "critical":
            return True, "Critical urgency detected"

        return False, ""

    async def log_decision(
        self,
        context: AgentContext,
        decision: AgentDecision,
        db_session,
    ):
        """Log the decision for learning and auditing."""
        from mailagent.models import AgentDecisionLog

        log_entry = AgentDecisionLog(
            agent_id=self.agent_id,
            message_id=context.message.id,
            action=decision.action.value,
            confidence=decision.confidence,
            reasoning=decision.reasoning,
            response_draft=decision.draft_response,
            requires_approval=decision.requires_approval,
            metadata=decision.metadata,
        )

        db_session.add(log_entry)
        await db_session.commit()

        return log_entry

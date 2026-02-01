"""Database models for mailagent service."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import JSON, Boolean, Integer, String, Text, ForeignKey
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base model with common fields."""

    pass


class EmailProvider(Base):
    """Email provider configuration."""

    __tablename__ = "mailagent_providers"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(50), nullable=False)
    credentials: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="setup")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    priority: Mapped[int] = mapped_column(Integer, default=100)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rate_limit_per_day: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_health_check: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SendingDomain(Base):
    """Sending domain configuration and verification."""

    __tablename__ = "mailagent_domains"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    domain: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    dns_records: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    warming_schedule: Mapped[str | None] = mapped_column(String(20), nullable=True)
    warming_day: Mapped[int] = mapped_column(Integer, default=0)
    warming_started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    daily_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    health_score: Mapped[int] = mapped_column(Integer, default=0)
    emails_sent_today: Mapped[int] = mapped_column(Integer, default=0)
    last_email_sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    inboxes: Mapped[list["Inbox"]] = relationship("Inbox", back_populates="domain")


class Inbox(Base):
    """Email inbox / sending identity."""

    __tablename__ = "mailagent_inboxes"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    domain_id: Mapped[UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailagent_domains.id"), nullable=True
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    emails_sent: Mapped[int] = mapped_column(Integer, default=0)
    last_email_sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    domain: Mapped[SendingDomain | None] = relationship(
        "SendingDomain", back_populates="inboxes"
    )


class Agent(Base):
    """AI Agent configuration."""

    __tablename__ = "mailagent_agents"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    workspace_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    mention_handle: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # LLM Configuration
    llm_provider: Mapped[str] = mapped_column(String(50), default="claude")
    llm_model: Mapped[str] = mapped_column(String(100), default="claude-3-opus-20240229")
    temperature: Mapped[float | None] = mapped_column(nullable=True, default=0.7)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2000)

    # Behavior
    system_prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    auto_respond: Mapped[bool] = mapped_column(Boolean, default=True)
    confidence_threshold: Mapped[float] = mapped_column(default=0.70)
    require_approval_below: Mapped[float] = mapped_column(default=0.80)
    max_daily_responses: Mapped[int] = mapped_column(Integer, default=100)
    response_delay_minutes: Mapped[int] = mapped_column(Integer, default=5)

    # Working hours
    working_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Escalation
    escalation_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    escalation_slack_channel: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Integration
    crm_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    calendar_sync: Mapped[bool] = mapped_column(Boolean, default=False)
    calendar_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_active_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    # Stats cache
    total_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_auto_replied: Mapped[int] = mapped_column(Integer, default=0)
    total_escalated: Mapped[int] = mapped_column(Integer, default=0)
    avg_confidence: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Message(Base):
    """Email message stored in mailagent."""

    __tablename__ = "mailagent_messages"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    inbox_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailagent_inboxes.id"), nullable=False
    )
    thread_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    in_reply_to: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Envelope
    from_address: Mapped[str] = mapped_column(String(255), nullable=False)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_addresses: Mapped[list] = mapped_column(JSON, default=list)
    cc_addresses: Mapped[list] = mapped_column(JSON, default=list)
    bcc_addresses: Mapped[list] = mapped_column(JSON, default=list)
    reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Content
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    attachments: Mapped[list] = mapped_column(JSON, default=list)
    headers: Mapped[dict] = mapped_column(JSON, default=dict)

    # Metadata
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="received")
    labels: Mapped[list] = mapped_column(JSON, default=list)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)

    # AI extraction
    extracted_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    intent: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Tracking
    provider_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    domain_used: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivery_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    bounced_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    bounce_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    received_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AgentDecision(Base):
    """Agent decision log for tracking and approval workflow."""

    __tablename__ = "mailagent_agent_decisions"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    agent_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailagent_agents.id"), nullable=False
    )
    message_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailagent_messages.id"), nullable=False
    )

    # Decision
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_draft: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_metadata: Mapped[dict] = mapped_column(JSON, default=dict)

    # Execution
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    executed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    execution_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Approval
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    approved_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    approval_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Human feedback
    feedback_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    feedback_correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    feedback_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class AgentInvocation(Base):
    """Tracks agent invocations from Aexy (mentions in comments, direct calls, etc.)."""

    __tablename__ = "mailagent_agent_invocations"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    agent_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailagent_agents.id"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Source context (from Aexy)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)  # comment, direct, scheduled
    entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)  # task, ticket, crm_record, etc.
    entity_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    activity_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # Entity activity ID

    # The invoking user
    invoked_by: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    invoked_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The instruction/prompt given to the agent
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    context: Mapped[dict] = mapped_column(JSON, default=dict)  # Additional context passed

    # Status
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, processing, completed, failed
    started_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AgentAction(Base):
    """Proposed action from an agent that may require human review."""

    __tablename__ = "mailagent_agent_actions"

    id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid4
    )
    invocation_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailagent_agent_invocations.id"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("mailagent_agents.id"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # Action type and details
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: create_task, update_task, create_crm_record, update_crm_record,
    #        schedule_meeting, send_email, update_ticket, add_comment, escalate

    # Target entity (if modifying something)
    target_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    target_entity_id: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # The proposed action payload
    action_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # Example for create_task: {"title": "...", "description": "...", "assignee_id": "..."}

    # Agent's reasoning
    confidence: Mapped[float] = mapped_column(nullable=False)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Preview for human review (human-readable summary)
    preview_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    preview_diff: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # For updates

    # Review status
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True)
    review_status: Mapped[str] = mapped_column(String(20), default="pending")
    # pending, approved, rejected, auto_approved, expired

    # Review details
    reviewed_by: Mapped[UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    reviewed_by_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Modified payload (if reviewer made changes)
    modified_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Execution
    executed: Mapped[bool] = mapped_column(Boolean, default=False)
    executed_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
    execution_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Expiry for auto-cleanup
    expires_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# Alias for backwards compatibility
AgentDecisionLog = AgentDecision

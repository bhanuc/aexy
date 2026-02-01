"""Agent inbox models for email integration."""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aexy.core.database import Base

if TYPE_CHECKING:
    from aexy.models.agent import CRMAgent
    from aexy.models.developer import Developer
    from aexy.models.workspace import Workspace


class AgentInboxMessage(Base):
    """Email received by an agent for processing."""

    __tablename__ = "agent_inboxes"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    agent_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Email metadata
    message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    thread_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    from_email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    from_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    to_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Processing state
    status: Mapped[str] = mapped_column(
        String(50),
        default="pending",
        nullable=False,
        index=True,
    )  # pending, processing, responded, escalated, archived
    priority: Mapped[str] = mapped_column(
        String(20),
        default="normal",
        nullable=False,
    )  # low, normal, high, urgent

    # AI processing results
    classification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # {intent, sentiment, urgency, topics}
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    suggested_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), nullable=True)

    # Response tracking
    response_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        nullable=True,
    )  # References sent email
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    escalated_to: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("developers.id", ondelete="SET NULL"),
        nullable=True,
    )
    escalated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Metadata
    headers: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attachments: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    agent: Mapped["CRMAgent"] = relationship(
        "CRMAgent",
        back_populates="inbox_messages",
    )
    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    escalated_to_developer: Mapped["Developer | None"] = relationship(
        "Developer",
        lazy="selectin",
        foreign_keys=[escalated_to],
    )


class AgentEmailRoutingRule(Base):
    """Rule for routing incoming emails to specific agents."""

    __tablename__ = "agent_email_routing_rules"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    workspace_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Rule definition
    rule_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )  # domain, sender, subject_contains, keyword
    rule_value: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    workspace: Mapped["Workspace"] = relationship("Workspace", lazy="selectin")
    agent: Mapped["CRMAgent"] = relationship("CRMAgent", lazy="selectin")

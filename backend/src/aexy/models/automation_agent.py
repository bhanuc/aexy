"""Models for automation-agent integration.

Enables AI agents to be spawned from automations and workflows with full
context passing and result handling.
"""

from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from aexy.core.database import Base

if TYPE_CHECKING:
    from aexy.models.agent import CRMAgent, CRMAgentExecution
    from aexy.models.crm import CRMAutomation, CRMAutomationRun
    from aexy.models.workflow import WorkflowExecution, WorkflowExecutionStep


class AgentTriggerPoint(str, Enum):
    """When an agent can be triggered in an automation."""

    ON_START = "on_start"  # At the start of the automation
    ON_CONDITION_MATCH = "on_condition_match"  # When conditions are met
    AS_ACTION = "as_action"  # As an explicit action step


class AutomationAgentExecutionStatus(str, Enum):
    """Status of an automation-triggered agent execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class AutomationAgentTrigger(Base):
    """Configuration for triggering an agent from an automation.

    Defines which agent should run at what point in an automation,
    how to map context data to the agent, and execution options.
    """

    __tablename__ = "automation_agent_triggers"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )
    automation_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_automations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    agent_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # When to trigger: 'on_start', 'on_condition_match', 'as_action'
    trigger_point: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Additional configuration for the trigger
    trigger_config: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    # Map automation context to agent input
    # Example: {"contact_name": "record.values.name", "company": "record.values.company"}
    input_mapping: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    # Whether to wait for agent completion before continuing
    wait_for_completion: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )

    # Maximum time to wait for agent completion (seconds)
    timeout_seconds: Mapped[int] = mapped_column(
        Integer,
        default=300,
        nullable=False,
    )

    # Whether this trigger is active
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )

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
    automation: Mapped["CRMAutomation"] = relationship(
        "CRMAutomation",
        lazy="selectin",
    )
    agent: Mapped["CRMAgent"] = relationship(
        "CRMAgent",
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint(
            "automation_id",
            "agent_id",
            "trigger_point",
            name="uq_automation_agent_trigger",
        ),
    )


class AutomationAgentExecution(Base):
    """Tracks agent executions triggered by automations/workflows.

    Links agent executions to their triggering automation run or workflow
    execution, providing full traceability.
    """

    __tablename__ = "automation_agent_executions"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        default=lambda: str(uuid4()),
    )

    # Link to automation run (for simple automations)
    automation_run_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_automation_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Link to workflow execution (for visual workflows)
    workflow_execution_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_workflow_executions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Link to specific workflow step (for agent nodes)
    workflow_step_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_workflow_execution_steps.id", ondelete="SET NULL"),
        nullable=True,
    )

    # The agent that was executed
    agent_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_agents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Link to the actual agent execution for detailed trace
    agent_execution_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("crm_agent_executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # When in the automation this agent was triggered
    trigger_point: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )

    # Input context passed to the agent
    input_context: Mapped[dict] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )

    # Output/result from the agent
    output_result: Mapped[dict | None] = mapped_column(
        JSONB,
        nullable=True,
    )

    # Execution status
    status: Mapped[str] = mapped_column(
        String(20),
        default=AutomationAgentExecutionStatus.PENDING.value,
        nullable=False,
    )

    # Error message if failed
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Record timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    # Relationships
    automation_run: Mapped["CRMAutomationRun | None"] = relationship(
        "CRMAutomationRun",
        lazy="selectin",
    )
    workflow_execution: Mapped["WorkflowExecution | None"] = relationship(
        "WorkflowExecution",
        lazy="selectin",
    )
    workflow_step: Mapped["WorkflowExecutionStep | None"] = relationship(
        "WorkflowExecutionStep",
        lazy="selectin",
    )
    agent: Mapped["CRMAgent"] = relationship(
        "CRMAgent",
        lazy="selectin",
    )
    agent_execution: Mapped["CRMAgentExecution | None"] = relationship(
        "CRMAgentExecution",
        lazy="selectin",
    )

    @property
    def duration_ms(self) -> int | None:
        """Calculate execution duration in milliseconds."""
        if self.started_at and self.completed_at:
            return int((self.completed_at - self.started_at).total_seconds() * 1000)
        return None

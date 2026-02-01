"""Schemas for automation-agent integration."""

from datetime import datetime
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# TRIGGER SCHEMAS
# =============================================================================


class AutomationAgentTriggerCreate(BaseModel):
    """Schema for creating an agent trigger on an automation."""

    agent_id: str = Field(..., description="ID of the agent to trigger")
    trigger_point: Literal["on_start", "on_condition_match", "as_action"] = Field(
        ..., description="When to trigger the agent"
    )
    trigger_config: dict = Field(
        default_factory=dict,
        description="Additional trigger configuration",
    )
    input_mapping: dict = Field(
        default_factory=dict,
        description="Map automation context to agent input fields",
    )
    wait_for_completion: bool = Field(
        default=False,
        description="Whether to wait for agent completion",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Max time to wait for agent completion",
    )


class AutomationAgentTriggerUpdate(BaseModel):
    """Schema for updating an agent trigger."""

    trigger_config: dict | None = None
    input_mapping: dict | None = None
    wait_for_completion: bool | None = None
    timeout_seconds: int | None = Field(default=None, ge=30, le=3600)
    is_active: bool | None = None


class AutomationAgentTriggerResponse(BaseModel):
    """Schema for agent trigger response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    automation_id: str
    agent_id: str
    trigger_point: str
    trigger_config: dict
    input_mapping: dict
    wait_for_completion: bool
    timeout_seconds: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    # Nested agent info (optional, loaded via relationship)
    agent_name: str | None = None
    agent_type: str | None = None


class AutomationAgentTriggerListResponse(BaseModel):
    """Schema for listing agent triggers with agent details."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    automation_id: str
    agent_id: str
    trigger_point: str
    wait_for_completion: bool
    timeout_seconds: int
    is_active: bool
    created_at: datetime

    # Agent details
    agent_name: str
    agent_type: str
    agent_is_active: bool


# =============================================================================
# EXECUTION SCHEMAS
# =============================================================================


class AutomationAgentExecutionResponse(BaseModel):
    """Schema for agent execution response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    automation_run_id: str | None = None
    workflow_execution_id: str | None = None
    workflow_step_id: str | None = None
    agent_id: str
    agent_execution_id: str | None = None
    trigger_point: str
    input_context: dict
    output_result: dict | None = None
    status: str
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime

    # Agent details
    agent_name: str | None = None


class AutomationAgentExecutionListResponse(BaseModel):
    """Schema for listing agent executions."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    automation_run_id: str | None = None
    workflow_execution_id: str | None = None
    agent_id: str
    trigger_point: str
    status: str
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None
    created_at: datetime

    # Agent details
    agent_name: str


# =============================================================================
# WORKFLOW AGENT NODE SCHEMAS
# =============================================================================


class AgentNodeConfig(BaseModel):
    """Configuration for an agent node in a workflow."""

    agent_id: str = Field(..., description="ID of the agent to execute")
    input_mapping: dict = Field(
        default_factory=dict,
        description="Map workflow variables to agent input",
    )
    output_variable: str | None = Field(
        default=None,
        description="Variable name to store agent output",
    )
    wait_for_completion: bool = Field(
        default=True,
        description="Whether to wait for agent completion",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Max time to wait for agent completion",
    )


class AgentNodeExecutionResult(BaseModel):
    """Result of executing an agent node in a workflow."""

    execution_id: str
    agent_id: str
    status: Literal["pending", "running", "completed", "failed", "timeout"]
    output: dict | None = None
    error: str | None = None
    duration_ms: int | None = None


# =============================================================================
# SPAWN REQUEST SCHEMA
# =============================================================================


class SpawnAgentRequest(BaseModel):
    """Request to spawn an agent from an automation or workflow."""

    agent_id: str = Field(..., description="ID of the agent to spawn")
    trigger_point: str = Field(..., description="Where in the automation this is triggered")
    context: dict = Field(
        default_factory=dict,
        description="Context data to pass to the agent",
    )
    wait_for_completion: bool = Field(
        default=False,
        description="Whether to wait for completion",
    )
    timeout_seconds: int = Field(
        default=300,
        ge=30,
        le=3600,
        description="Max wait time for completion",
    )


class SpawnAgentResponse(BaseModel):
    """Response from spawning an agent."""

    execution_id: str
    agent_id: str
    status: str
    output: dict | None = None
    error: str | None = None

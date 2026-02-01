"""API endpoints for automation-agent integration.

Provides endpoints for:
- Configuring agent triggers on automations
- Viewing agent execution history for automations
- Viewing automation-triggered executions for agents
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.api.developers import get_current_developer
from aexy.models.developer import Developer
from aexy.services.workspace_service import WorkspaceService
from aexy.schemas.automation_agent import (
    AutomationAgentTriggerCreate,
    AutomationAgentTriggerUpdate,
    AutomationAgentTriggerResponse,
    AutomationAgentTriggerListResponse,
    AutomationAgentExecutionResponse,
    AutomationAgentExecutionListResponse,
)
from aexy.services.automation_agent_service import AutomationAgentService

router = APIRouter()


async def check_workspace_permission(
    db: AsyncSession,
    workspace_id: str,
    developer_id: str,
    required_role: str = "member",
) -> None:
    """Check if user has permission to access workspace."""
    workspace_service = WorkspaceService(db)
    if not await workspace_service.check_permission(
        workspace_id, developer_id, required_role
    ):
        raise HTTPException(
            status_code=403,
            detail="Insufficient permissions for this workspace",
        )


# =============================================================================
# AGENT TRIGGERS ON AUTOMATIONS
# =============================================================================


@router.post(
    "/workspaces/{workspace_id}/crm/automations/{automation_id}/agent-triggers",
    response_model=AutomationAgentTriggerResponse,
    summary="Configure agent trigger for automation",
    description="Configure an AI agent to be triggered by this automation at a specific point.",
)
async def create_agent_trigger(
    workspace_id: str,
    automation_id: str,
    data: AutomationAgentTriggerCreate,
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """Create or update an agent trigger for an automation."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    try:
        trigger = await service.configure_agent_trigger(
            automation_id=automation_id,
            agent_id=data.agent_id,
            trigger_point=data.trigger_point,
            trigger_config=data.trigger_config,
            input_mapping=data.input_mapping,
            wait_for_completion=data.wait_for_completion,
            timeout_seconds=data.timeout_seconds,
        )

        # Build response with agent info
        return AutomationAgentTriggerResponse(
            id=trigger.id,
            automation_id=trigger.automation_id,
            agent_id=trigger.agent_id,
            trigger_point=trigger.trigger_point,
            trigger_config=trigger.trigger_config,
            input_mapping=trigger.input_mapping,
            wait_for_completion=trigger.wait_for_completion,
            timeout_seconds=trigger.timeout_seconds,
            is_active=trigger.is_active,
            created_at=trigger.created_at,
            updated_at=trigger.updated_at,
            agent_name=trigger.agent.name if trigger.agent else None,
            agent_type=trigger.agent.agent_type if trigger.agent else None,
        )

    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get(
    "/workspaces/{workspace_id}/crm/automations/{automation_id}/agent-triggers",
    response_model=list[AutomationAgentTriggerListResponse],
    summary="List agent triggers for automation",
    description="Get all agent triggers configured for this automation.",
)
async def list_agent_triggers(
    workspace_id: str,
    automation_id: str,
    trigger_point: str | None = Query(
        None,
        description="Filter by trigger point (on_start, on_condition_match, as_action)",
    ),
    active_only: bool = Query(True, description="Only return active triggers"),
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """List agent triggers for an automation."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    triggers = await service.get_agent_triggers(
        automation_id=automation_id,
        trigger_point=trigger_point,
        active_only=active_only,
    )

    return [
        AutomationAgentTriggerListResponse(
            id=t.id,
            automation_id=t.automation_id,
            agent_id=t.agent_id,
            trigger_point=t.trigger_point,
            wait_for_completion=t.wait_for_completion,
            timeout_seconds=t.timeout_seconds,
            is_active=t.is_active,
            created_at=t.created_at,
            agent_name=t.agent.name if t.agent else "Unknown",
            agent_type=t.agent.agent_type if t.agent else "unknown",
            agent_is_active=t.agent.is_active if t.agent else False,
        )
        for t in triggers
    ]


@router.get(
    "/workspaces/{workspace_id}/crm/automations/{automation_id}/agent-triggers/{trigger_id}",
    response_model=AutomationAgentTriggerResponse,
    summary="Get agent trigger details",
)
async def get_agent_trigger(
    workspace_id: str,
    automation_id: str,
    trigger_id: str,
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """Get details of a specific agent trigger."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    trigger = await service.get_agent_trigger(trigger_id)
    if not trigger or trigger.automation_id != automation_id:
        raise HTTPException(status_code=404, detail="Agent trigger not found")

    return AutomationAgentTriggerResponse(
        id=trigger.id,
        automation_id=trigger.automation_id,
        agent_id=trigger.agent_id,
        trigger_point=trigger.trigger_point,
        trigger_config=trigger.trigger_config,
        input_mapping=trigger.input_mapping,
        wait_for_completion=trigger.wait_for_completion,
        timeout_seconds=trigger.timeout_seconds,
        is_active=trigger.is_active,
        created_at=trigger.created_at,
        updated_at=trigger.updated_at,
        agent_name=trigger.agent.name if trigger.agent else None,
        agent_type=trigger.agent.agent_type if trigger.agent else None,
    )


@router.patch(
    "/workspaces/{workspace_id}/crm/automations/{automation_id}/agent-triggers/{trigger_id}",
    response_model=AutomationAgentTriggerResponse,
    summary="Update agent trigger",
)
async def update_agent_trigger(
    workspace_id: str,
    automation_id: str,
    trigger_id: str,
    data: AutomationAgentTriggerUpdate,
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """Update an agent trigger configuration."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    # Verify trigger belongs to this automation
    existing = await service.get_agent_trigger(trigger_id)
    if not existing or existing.automation_id != automation_id:
        raise HTTPException(status_code=404, detail="Agent trigger not found")

    trigger = await service.update_agent_trigger(
        trigger_id=trigger_id,
        trigger_config=data.trigger_config,
        input_mapping=data.input_mapping,
        wait_for_completion=data.wait_for_completion,
        timeout_seconds=data.timeout_seconds,
        is_active=data.is_active,
    )

    if not trigger:
        raise HTTPException(status_code=404, detail="Agent trigger not found")

    return AutomationAgentTriggerResponse(
        id=trigger.id,
        automation_id=trigger.automation_id,
        agent_id=trigger.agent_id,
        trigger_point=trigger.trigger_point,
        trigger_config=trigger.trigger_config,
        input_mapping=trigger.input_mapping,
        wait_for_completion=trigger.wait_for_completion,
        timeout_seconds=trigger.timeout_seconds,
        is_active=trigger.is_active,
        created_at=trigger.created_at,
        updated_at=trigger.updated_at,
        agent_name=trigger.agent.name if trigger.agent else None,
        agent_type=trigger.agent.agent_type if trigger.agent else None,
    )


@router.delete(
    "/workspaces/{workspace_id}/crm/automations/{automation_id}/agent-triggers/{trigger_id}",
    summary="Delete agent trigger",
)
async def delete_agent_trigger(
    workspace_id: str,
    automation_id: str,
    trigger_id: str,
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """Delete an agent trigger."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    # Verify trigger belongs to this automation
    existing = await service.get_agent_trigger(trigger_id)
    if not existing or existing.automation_id != automation_id:
        raise HTTPException(status_code=404, detail="Agent trigger not found")

    success = await service.delete_agent_trigger(trigger_id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent trigger not found")

    return {"success": True, "message": "Agent trigger deleted"}


# =============================================================================
# AGENT EXECUTIONS FOR AUTOMATIONS
# =============================================================================


@router.get(
    "/workspaces/{workspace_id}/crm/automations/{automation_id}/agent-executions",
    response_model=list[AutomationAgentExecutionListResponse],
    summary="List agent executions for automation",
    description="Get all agent executions triggered by this automation.",
)
async def list_automation_agent_executions(
    workspace_id: str,
    automation_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """List agent executions for an automation."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    executions = await service.list_executions_for_automation(
        automation_id=automation_id,
        skip=skip,
        limit=limit,
    )

    return [
        AutomationAgentExecutionListResponse(
            id=e.id,
            automation_run_id=e.automation_run_id,
            workflow_execution_id=e.workflow_execution_id,
            agent_id=e.agent_id,
            trigger_point=e.trigger_point,
            status=e.status,
            started_at=e.started_at,
            completed_at=e.completed_at,
            duration_ms=e.duration_ms,
            created_at=e.created_at,
            agent_name=e.agent.name if e.agent else "Unknown",
        )
        for e in executions
    ]


@router.get(
    "/workspaces/{workspace_id}/crm/automations/{automation_id}/agent-executions/{execution_id}",
    response_model=AutomationAgentExecutionResponse,
    summary="Get agent execution details",
)
async def get_automation_agent_execution(
    workspace_id: str,
    automation_id: str,
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """Get details of a specific agent execution."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    execution = await service.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="Agent execution not found")

    return AutomationAgentExecutionResponse(
        id=execution.id,
        automation_run_id=execution.automation_run_id,
        workflow_execution_id=execution.workflow_execution_id,
        workflow_step_id=execution.workflow_step_id,
        agent_id=execution.agent_id,
        agent_execution_id=execution.agent_execution_id,
        trigger_point=execution.trigger_point,
        input_context=execution.input_context,
        output_result=execution.output_result,
        status=execution.status,
        error_message=execution.error_message,
        started_at=execution.started_at,
        completed_at=execution.completed_at,
        duration_ms=execution.duration_ms,
        created_at=execution.created_at,
        agent_name=execution.agent.name if execution.agent else None,
    )


# =============================================================================
# AGENT AUTOMATION EXECUTIONS (from agent perspective)
# =============================================================================


@router.get(
    "/workspaces/{workspace_id}/agents/{agent_id}/automation-executions",
    response_model=list[AutomationAgentExecutionListResponse],
    summary="List automation executions for agent",
    description="Get all automation-triggered executions for this agent.",
)
async def list_agent_automation_executions(
    workspace_id: str,
    agent_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    developer: Developer = Depends(get_current_developer),
):
    """List automation-triggered executions for an agent."""
    await check_workspace_permission(db, workspace_id, str(developer.id))
    service = AutomationAgentService(db)

    executions = await service.list_executions_for_agent(
        agent_id=agent_id,
        skip=skip,
        limit=limit,
    )

    return [
        AutomationAgentExecutionListResponse(
            id=e.id,
            automation_run_id=e.automation_run_id,
            workflow_execution_id=e.workflow_execution_id,
            agent_id=e.agent_id,
            trigger_point=e.trigger_point,
            status=e.status,
            started_at=e.started_at,
            completed_at=e.completed_at,
            duration_ms=e.duration_ms,
            created_at=e.created_at,
            agent_name=e.agent.name if e.agent else "Unknown",
        )
        for e in executions
    ]

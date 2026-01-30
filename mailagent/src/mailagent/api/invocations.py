"""API endpoints for agent invocations and human review workflow."""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from mailagent.database import get_db
from mailagent.services.invocation_service import get_invocation_service, InvocationService


router = APIRouter(prefix="/invocations", tags=["Agent Invocations"])


# ==========================================
# SCHEMAS
# ==========================================

class AgentInfo(BaseModel):
    """Agent information for discovery."""
    id: UUID
    name: str
    agent_type: str
    mention_handle: Optional[str] = None
    description: Optional[str] = None
    is_active: bool


class InvokeAgentRequest(BaseModel):
    """Request to invoke an agent."""
    agent_id: Optional[UUID] = None
    agent_handle: Optional[str] = None  # Alternative: use @mention handle
    workspace_id: UUID
    source_type: str = Field(default="direct", description="comment, direct, scheduled, webhook")
    entity_type: Optional[str] = None
    entity_id: Optional[UUID] = None
    activity_id: Optional[UUID] = None
    invoked_by: UUID
    invoked_by_name: Optional[str] = None
    instruction: Optional[str] = None
    context: Optional[dict] = None


class ParseMentionsRequest(BaseModel):
    """Request to parse @mentions from text."""
    text: str
    workspace_id: UUID


class ParseMentionsResponse(BaseModel):
    """Response with parsed agent mentions."""
    agents: list[AgentInfo]
    mention_count: int


class InvocationResponse(BaseModel):
    """Response after creating an invocation."""
    id: UUID
    agent_id: UUID
    status: str
    created_at: datetime


class ActionResponse(BaseModel):
    """Agent action details."""
    id: UUID
    invocation_id: UUID
    agent_id: UUID
    action_type: str
    target_entity_type: Optional[str] = None
    target_entity_id: Optional[UUID] = None
    action_payload: dict
    confidence: float
    reasoning: Optional[str] = None
    preview_summary: Optional[str] = None
    requires_review: bool
    review_status: str
    reviewed_by: Optional[UUID] = None
    reviewed_by_name: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None
    executed: bool
    executed_at: Optional[datetime] = None
    execution_result: Optional[dict] = None
    execution_error: Optional[str] = None
    created_at: datetime


class PendingActionsResponse(BaseModel):
    """Response with pending actions."""
    actions: list[ActionResponse]
    total: int


class ReviewActionRequest(BaseModel):
    """Request to review (approve/reject) an action."""
    reviewed_by: UUID
    reviewed_by_name: Optional[str] = None
    notes: Optional[str] = None
    modified_payload: Optional[dict] = None  # For approve only


class ActionListResponse(BaseModel):
    """List of actions."""
    actions: list[ActionResponse]
    total: int


# ==========================================
# ENDPOINTS
# ==========================================

@router.get("/agents", response_model=list[AgentInfo])
async def list_workspace_agents(
    workspace_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """List all agents available in a workspace for @mention discovery."""
    service = await get_invocation_service(db)
    agents = await service.get_agents_for_workspace(workspace_id)
    return [
        AgentInfo(
            id=a.id,
            name=a.name,
            agent_type=a.agent_type,
            mention_handle=getattr(a, 'mention_handle', None),
            description=a.description,
            is_active=a.is_active,
        )
        for a in agents
    ]


@router.post("/parse-mentions", response_model=ParseMentionsResponse)
async def parse_mentions(
    request: ParseMentionsRequest,
    db: AsyncSession = Depends(get_db),
):
    """Parse @mentions from text and return matching agents.

    Use this to validate mentions before creating a comment/activity.
    """
    service = await get_invocation_service(db)
    agents = await service.parse_mentions(request.text, request.workspace_id)
    return ParseMentionsResponse(
        agents=[
            AgentInfo(
                id=a.id,
                name=a.name,
                agent_type=a.agent_type,
                mention_handle=getattr(a, 'mention_handle', None),
                description=a.description,
                is_active=a.is_active,
            )
            for a in agents
        ],
        mention_count=len(agents),
    )


@router.post("/invoke", response_model=InvocationResponse)
async def invoke_agent(
    request: InvokeAgentRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Invoke an agent to process a request.

    The agent will analyze the context and generate proposed actions.
    Actions may require human review based on the agent's confidence threshold.
    """
    service = await get_invocation_service(db)

    # Resolve agent ID from handle if needed
    agent_id = request.agent_id
    if not agent_id and request.agent_handle:
        agents = await service.parse_mentions(f"@{request.agent_handle}", request.workspace_id)
        if not agents:
            raise HTTPException(status_code=404, detail=f"Agent @{request.agent_handle} not found")
        agent_id = agents[0].id

    if not agent_id:
        raise HTTPException(status_code=400, detail="Either agent_id or agent_handle is required")

    # Create the invocation
    invocation = await service.create_invocation(
        agent_id=agent_id,
        workspace_id=request.workspace_id,
        source_type=request.source_type,
        invoked_by=request.invoked_by,
        invoked_by_name=request.invoked_by_name,
        entity_type=request.entity_type,
        entity_id=request.entity_id,
        activity_id=request.activity_id,
        instruction=request.instruction,
        context=request.context,
    )

    # Process in background
    background_tasks.add_task(
        _process_invocation_background,
        invocation.id,
    )

    return InvocationResponse(
        id=invocation.id,
        agent_id=invocation.agent_id,
        status=invocation.status,
        created_at=invocation.created_at,
    )


async def _process_invocation_background(invocation_id: UUID):
    """Background task to process an invocation."""
    from mailagent.database import async_session_maker

    async with async_session_maker() as db:
        service = await get_invocation_service(db)
        try:
            await service.process_invocation(invocation_id)
        except Exception as e:
            # Log the error - invocation status is already updated in the service
            import logging
            logging.error(f"Failed to process invocation {invocation_id}: {e}")


@router.get("/pending", response_model=PendingActionsResponse)
async def get_pending_actions(
    workspace_id: UUID,
    agent_id: Optional[UUID] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[UUID] = None,
    limit: int = Query(default=50, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Get pending actions requiring human review."""
    service = await get_invocation_service(db)
    actions = await service.get_pending_actions(
        workspace_id=workspace_id,
        agent_id=agent_id,
        entity_type=entity_type,
        entity_id=entity_id,
        limit=limit,
    )
    return PendingActionsResponse(
        actions=[_action_to_response(a) for a in actions],
        total=len(actions),
    )


@router.post("/actions/{action_id}/approve", response_model=ActionResponse)
async def approve_action(
    action_id: UUID,
    request: ReviewActionRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Approve an action and optionally execute it."""
    service = await get_invocation_service(db)

    try:
        action = await service.approve_action(
            action_id=action_id,
            reviewed_by=request.reviewed_by,
            reviewed_by_name=request.reviewed_by_name,
            notes=request.notes,
            modified_payload=request.modified_payload,
        )

        # Execute in background
        background_tasks.add_task(
            _execute_action_background,
            action_id,
        )

        return _action_to_response(action)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/actions/{action_id}/reject", response_model=ActionResponse)
async def reject_action(
    action_id: UUID,
    request: ReviewActionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Reject an action."""
    service = await get_invocation_service(db)

    try:
        action = await service.reject_action(
            action_id=action_id,
            reviewed_by=request.reviewed_by,
            reviewed_by_name=request.reviewed_by_name,
            notes=request.notes,
        )
        return _action_to_response(action)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/actions/{action_id}/execute", response_model=ActionResponse)
async def execute_action(
    action_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Execute an approved action."""
    service = await get_invocation_service(db)

    try:
        action = await service.execute_action(action_id)
        return _action_to_response(action)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


async def _execute_action_background(action_id: UUID):
    """Background task to execute an action."""
    from mailagent.database import async_session_maker

    async with async_session_maker() as db:
        service = await get_invocation_service(db)
        try:
            await service.execute_action(action_id)
        except Exception as e:
            import logging
            logging.error(f"Failed to execute action {action_id}: {e}")


@router.get("/actions", response_model=ActionListResponse)
async def list_actions(
    workspace_id: UUID,
    invocation_id: Optional[UUID] = None,
    review_status: Optional[str] = None,
    executed: Optional[bool] = None,
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """List actions with optional filters."""
    from sqlalchemy import select, and_
    from mailagent.models import AgentAction

    query = select(AgentAction).where(AgentAction.workspace_id == workspace_id)

    if invocation_id:
        query = query.where(AgentAction.invocation_id == invocation_id)
    if review_status:
        query = query.where(AgentAction.review_status == review_status)
    if executed is not None:
        query = query.where(AgentAction.executed == executed)

    query = query.order_by(AgentAction.created_at.desc()).offset(offset).limit(limit)

    result = await db.execute(query)
    actions = list(result.scalars().all())

    return ActionListResponse(
        actions=[_action_to_response(a) for a in actions],
        total=len(actions),
    )


def _action_to_response(action) -> ActionResponse:
    """Convert AgentAction model to response schema."""
    return ActionResponse(
        id=action.id,
        invocation_id=action.invocation_id,
        agent_id=action.agent_id,
        action_type=action.action_type,
        target_entity_type=action.target_entity_type,
        target_entity_id=action.target_entity_id,
        action_payload=action.action_payload,
        confidence=action.confidence,
        reasoning=action.reasoning,
        preview_summary=action.preview_summary,
        requires_review=action.requires_review,
        review_status=action.review_status,
        reviewed_by=action.reviewed_by,
        reviewed_by_name=action.reviewed_by_name,
        reviewed_at=action.reviewed_at,
        review_notes=action.review_notes,
        executed=action.executed,
        executed_at=action.executed_at,
        execution_result=action.execution_result,
        execution_error=action.execution_error,
        created_at=action.created_at,
    )

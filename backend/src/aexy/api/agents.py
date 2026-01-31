"""API endpoints for AI Agents."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.database import get_db
from aexy.api.developers import get_current_developer
from aexy.models.developer import Developer
from aexy.services.workspace_service import WorkspaceService
from aexy.services.agent_service import AgentService
from aexy.services.writing_style_service import WritingStyleService
from aexy.schemas.agent import (
    AgentCreate,
    AgentUpdate,
    AgentResponse,
    AgentExecuteRequest,
    AgentExecutionResponse,
    AgentToolInfo,
    AgentMetricsResponse,
    HandleAvailabilityResponse,
    WritingStyleResponse,
    GenerateEmailRequest,
    GenerateEmailResponse,
    ConversationCreate,
    ConversationUpdate,
    ConversationResponse,
    ConversationWithMessagesResponse,
    MessageCreate,
    MessageResponse,
)

router = APIRouter(prefix="/workspaces/{workspace_id}/crm/agents")
writing_style_router = APIRouter(prefix="/workspaces/{workspace_id}/crm/writing-style")


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
# AGENT CRUD
# =============================================================================


@router.get("", response_model=list[AgentResponse])
async def list_agents(
    workspace_id: str,
    agent_type: str | None = None,
    is_active: bool | None = None,
    include_system: bool = True,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """List agents in a workspace."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)

    # Ensure system agents exist
    await service.ensure_system_agents(workspace_id)

    agents = await service.list_agents(
        workspace_id=workspace_id,
        agent_type=agent_type,
        is_active=is_active,
        include_system=include_system,
        skip=skip,
        limit=limit,
    )
    return agents


@router.post("", response_model=AgentResponse)
async def create_agent(
    workspace_id: str,
    data: AgentCreate,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Create a custom agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id), "admin")
    service = AgentService(db)

    # Check handle availability if provided
    if data.mention_handle:
        is_available = await service.check_handle_available(
            workspace_id=workspace_id,
            handle=data.mention_handle,
        )
        if not is_available:
            raise HTTPException(
                status_code=400,
                detail=f"Handle @{data.mention_handle} is already in use",
            )

    # Convert working_hours Pydantic model to dict if provided
    working_hours_dict = data.working_hours.model_dump() if data.working_hours else None

    agent = await service.create_agent(
        workspace_id=workspace_id,
        name=data.name,
        description=data.description,
        agent_type=data.agent_type,
        mention_handle=data.mention_handle,
        goal=data.goal,
        system_prompt=data.system_prompt,
        custom_instructions=data.custom_instructions,
        tools=data.tools,
        llm_provider=data.llm_provider,
        model=data.model,
        temperature=data.temperature,
        max_tokens=data.max_tokens,
        max_iterations=data.max_iterations,
        timeout_seconds=data.timeout_seconds,
        confidence_threshold=data.confidence_threshold,
        require_approval_below=data.require_approval_below,
        max_daily_responses=data.max_daily_responses,
        response_delay_minutes=data.response_delay_minutes,
        working_hours=working_hours_dict,
        escalation_email=data.escalation_email,
        escalation_slack_channel=data.escalation_slack_channel,
        created_by_id=current_developer.id,
    )
    await db.commit()
    return agent


@router.get("/tools", response_model=list[AgentToolInfo])
async def list_available_tools(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """List all available tools for agent configuration."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    return AgentService.get_available_tools()


@router.get("/check-handle", response_model=HandleAvailabilityResponse)
async def check_handle_availability(
    workspace_id: str,
    handle: str = Query(..., min_length=1, max_length=50),
    exclude_agent_id: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Check if a mention handle is available."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)
    is_available = await service.check_handle_available(
        workspace_id=workspace_id,
        handle=handle,
        exclude_agent_id=exclude_agent_id,
    )
    return HandleAvailabilityResponse(
        available=is_available,
        handle=handle,
        message=None if is_available else f"Handle @{handle} is already in use",
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    workspace_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get an agent by ID."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    workspace_id: str,
    agent_id: str,
    data: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Update an agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id), "admin")
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    update_data = data.model_dump(exclude_unset=True)
    agent = await service.update_agent(agent_id, **update_data)
    if not agent:
        raise HTTPException(status_code=400, detail="Cannot modify system agent")

    await db.commit()
    return agent


@router.delete("/{agent_id}")
async def delete_agent(
    workspace_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Delete an agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id), "admin")
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    success = await service.delete_agent(agent_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot delete system agent")

    await db.commit()
    return {"message": "Agent deleted"}


@router.post("/{agent_id}/toggle", response_model=AgentResponse)
async def toggle_agent(
    workspace_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Toggle agent active status."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id), "admin")
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent = await service.toggle_agent(agent_id)
    await db.commit()
    return agent


@router.get("/{agent_id}/metrics", response_model=AgentMetricsResponse)
async def get_agent_metrics(
    workspace_id: str,
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get metrics for an agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    metrics = await service.get_agent_metrics(agent_id)
    return metrics


# =============================================================================
# AGENT EXECUTION
# =============================================================================


@router.post("/{agent_id}/run", response_model=AgentExecutionResponse)
async def execute_agent(
    workspace_id: str,
    agent_id: str,
    data: AgentExecuteRequest,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Execute an agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        execution = await service.execute_agent(
            agent_id=agent_id,
            record_id=data.record_id,
            context=data.context,
            user_id=current_developer.id,
            triggered_by="manual",
        )
        await db.commit()
        return execution
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{agent_id}/executions", response_model=list[AgentExecutionResponse])
async def list_agent_executions(
    workspace_id: str,
    agent_id: str,
    status: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """List executions for an agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)
    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    executions = await service.list_executions(
        agent_id=agent_id,
        status=status,
        skip=skip,
        limit=limit,
    )
    return executions


@router.get("/{agent_id}/executions/{execution_id}", response_model=AgentExecutionResponse)
async def get_execution(
    workspace_id: str,
    agent_id: str,
    execution_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get a specific execution."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)
    execution = await service.get_execution(execution_id)
    if not execution or execution.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Execution not found")
    return execution


# =============================================================================
# CONVERSATIONS
# =============================================================================


@router.post("/{agent_id}/conversations", response_model=ConversationWithMessagesResponse)
async def create_conversation(
    workspace_id: str,
    agent_id: str,
    data: ConversationCreate,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Start a new conversation with an agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)

    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    try:
        conversation, user_message, execution = await service.create_conversation(
            agent_id=agent_id,
            workspace_id=workspace_id,
            initial_message=data.message,
            record_id=data.record_id,
            title=data.title,
            user_id=str(current_developer.id),
        )
        await db.commit()

        # Refresh to get messages
        await db.refresh(conversation)
        messages = await service.get_conversation_messages(conversation.id)

        return ConversationWithMessagesResponse(
            id=conversation.id,
            workspace_id=conversation.workspace_id,
            agent_id=conversation.agent_id,
            record_id=conversation.record_id,
            title=conversation.title,
            status=conversation.status,
            conversation_metadata=conversation.conversation_metadata,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            ended_at=conversation.ended_at,
            message_count=len(messages),
            messages=[MessageResponse.model_validate(m) for m in messages],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{agent_id}/conversations", response_model=list[ConversationResponse])
async def list_conversations(
    workspace_id: str,
    agent_id: str,
    status: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """List conversations for an agent."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)

    agent = await service.get_agent(agent_id)
    if not agent or agent.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="Agent not found")

    conversations = await service.list_conversations(
        agent_id=agent_id,
        status=status,
        skip=skip,
        limit=limit,
    )

    # Get message counts
    result = []
    for conv in conversations:
        messages = await service.get_conversation_messages(conv.id, limit=1000)
        result.append(ConversationResponse(
            id=conv.id,
            workspace_id=conv.workspace_id,
            agent_id=conv.agent_id,
            record_id=conv.record_id,
            title=conv.title,
            status=conv.status,
            conversation_metadata=conv.conversation_metadata,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
            ended_at=conv.ended_at,
            message_count=len(messages),
        ))

    return result


@router.get("/{agent_id}/conversations/{conversation_id}", response_model=ConversationWithMessagesResponse)
async def get_conversation(
    workspace_id: str,
    agent_id: str,
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get a conversation with messages."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)

    conversation = await service.get_conversation(conversation_id)
    if not conversation or conversation.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    messages = await service.get_conversation_messages(conversation_id)

    return ConversationWithMessagesResponse(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
        record_id=conversation.record_id,
        title=conversation.title,
        status=conversation.status,
        conversation_metadata=conversation.conversation_metadata,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        ended_at=conversation.ended_at,
        message_count=len(messages),
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


@router.post("/{agent_id}/conversations/{conversation_id}/messages", response_model=ConversationWithMessagesResponse)
async def send_message(
    workspace_id: str,
    agent_id: str,
    conversation_id: str,
    data: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Send a message in a conversation."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)

    conversation = await service.get_conversation(conversation_id)
    if not conversation or conversation.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        user_message, execution = await service.send_message(
            conversation_id=conversation_id,
            content=data.content,
            user_id=str(current_developer.id),
        )
        await db.commit()

        # Refresh conversation and get all messages
        conversation = await service.get_conversation(conversation_id)
        messages = await service.get_conversation_messages(conversation_id)

        return ConversationWithMessagesResponse(
            id=conversation.id,
            workspace_id=conversation.workspace_id,
            agent_id=conversation.agent_id,
            record_id=conversation.record_id,
            title=conversation.title,
            status=conversation.status,
            conversation_metadata=conversation.conversation_metadata,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            ended_at=conversation.ended_at,
            message_count=len(messages),
            messages=[MessageResponse.model_validate(m) for m in messages],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{agent_id}/conversations/{conversation_id}", response_model=ConversationResponse)
async def update_conversation(
    workspace_id: str,
    agent_id: str,
    conversation_id: str,
    data: ConversationUpdate,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Update a conversation (title, status)."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)

    conversation = await service.get_conversation(conversation_id)
    if not conversation or conversation.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation = await service.update_conversation(
        conversation_id=conversation_id,
        title=data.title,
        status=data.status,
    )
    await db.commit()

    messages = await service.get_conversation_messages(conversation_id)

    return ConversationResponse(
        id=conversation.id,
        workspace_id=conversation.workspace_id,
        agent_id=conversation.agent_id,
        record_id=conversation.record_id,
        title=conversation.title,
        status=conversation.status,
        conversation_metadata=conversation.conversation_metadata,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        ended_at=conversation.ended_at,
        message_count=len(messages),
    )


@router.delete("/{agent_id}/conversations/{conversation_id}")
async def delete_conversation(
    workspace_id: str,
    agent_id: str,
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Archive/delete a conversation."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = AgentService(db)

    conversation = await service.get_conversation(conversation_id)
    if not conversation or conversation.agent_id != agent_id:
        raise HTTPException(status_code=404, detail="Conversation not found")

    success = await service.delete_conversation(conversation_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to delete conversation")

    await db.commit()
    return {"message": "Conversation archived"}


# =============================================================================
# WRITING STYLE
# =============================================================================


@writing_style_router.get("", response_model=WritingStyleResponse | None)
async def get_writing_style(
    workspace_id: str,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Get the current user's writing style profile."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = WritingStyleService(db)
    style = await service.get_style(str(current_developer.id), workspace_id)
    return style


@writing_style_router.post("/analyze", response_model=WritingStyleResponse)
async def analyze_writing_style(
    workspace_id: str,
    max_samples: int = Query(default=50, ge=10, le=200),
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Analyze user's sent emails to build a writing style profile."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = WritingStyleService(db)
    style = await service.analyze_emails(
        developer_id=str(current_developer.id),
        workspace_id=workspace_id,
        max_samples=max_samples,
    )
    await db.commit()
    return style


@writing_style_router.post("/generate-email", response_model=GenerateEmailResponse)
async def generate_email(
    workspace_id: str,
    data: GenerateEmailRequest,
    db: AsyncSession = Depends(get_db),
    current_developer: Developer = Depends(get_current_developer),
):
    """Generate an email matching the user's writing style."""
    await check_workspace_permission(db, workspace_id, str(current_developer.id))
    service = WritingStyleService(db)
    result = await service.generate_email(
        developer_id=str(current_developer.id),
        workspace_id=workspace_id,
        recipient_name=data.recipient_name,
        purpose=data.purpose,
        key_points=data.key_points,
        tone_override=data.tone_override,
    )
    return GenerateEmailResponse(**result)

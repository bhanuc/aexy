"""API endpoints for managing email agents."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from mailagent.database import get_db
from mailagent.agents.base import AgentType, AgentAction


router = APIRouter(prefix="/agents", tags=["agents"])


# Request/Response schemas
class AgentCreate(BaseModel):
    """Request to create a new agent."""
    name: str
    agent_type: AgentType
    description: Optional[str] = None
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.0-flash"
    confidence_threshold: float = 0.70
    require_approval_below: float = 0.80
    system_prompt: Optional[str] = None
    custom_instructions: Optional[str] = None


class AgentUpdate(BaseModel):
    """Request to update an agent."""
    name: Optional[str] = None
    description: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    confidence_threshold: Optional[float] = None
    require_approval_below: Optional[float] = None
    system_prompt: Optional[str] = None
    custom_instructions: Optional[str] = None
    is_active: Optional[bool] = None


class AgentResponse(BaseModel):
    """Agent response model."""
    id: UUID
    name: str
    agent_type: str
    description: Optional[str]
    llm_provider: str
    llm_model: str
    confidence_threshold: float
    require_approval_below: float
    is_active: bool
    total_processed: int
    total_auto_replied: int
    total_escalated: int


class AgentListResponse(BaseModel):
    """List of agents response."""
    agents: list[AgentResponse]
    total: int


class InboxAgentAssign(BaseModel):
    """Request to assign agent to inbox."""
    agent_id: UUID
    priority: int = 100


class AgentDecisionResponse(BaseModel):
    """Recent agent decision response."""
    id: UUID
    agent_id: UUID
    message_id: UUID
    action: str
    confidence: float
    reasoning: Optional[str]
    requires_approval: bool
    approved: Optional[bool]
    created_at: str


# Endpoints
@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent: AgentCreate,
    session=Depends(get_db),
):
    """Create a new email agent."""
    result = await session.execute(
        text("""
            INSERT INTO mailagent_agents (
                name, agent_type, description,
                llm_provider, llm_model, confidence_threshold,
                require_approval_below, system_prompt, custom_instructions
            ) VALUES (
                :name, :agent_type, :description,
                :llm_provider, :llm_model, :confidence_threshold,
                :require_approval_below, :system_prompt, :custom_instructions
            )
            RETURNING id, name, agent_type, description,
                      llm_provider, llm_model, confidence_threshold,
                      require_approval_below, is_active,
                      total_processed, total_auto_replied, total_escalated
        """),
        {
            "name": agent.name,
            "agent_type": agent.agent_type.value,
            "description": agent.description,
            "llm_provider": agent.llm_provider,
            "llm_model": agent.llm_model,
            "confidence_threshold": agent.confidence_threshold,
            "require_approval_below": agent.require_approval_below,
            "system_prompt": agent.system_prompt,
            "custom_instructions": agent.custom_instructions,
        },
    )
    await session.commit()

    row = result.fetchone()
    return AgentResponse(
        id=row.id,
        name=row.name,
        agent_type=row.agent_type,
        description=row.description,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        confidence_threshold=float(row.confidence_threshold or 0.7),
        require_approval_below=float(row.require_approval_below or 0.8),
        is_active=row.is_active,
        total_processed=row.total_processed or 0,
        total_auto_replied=row.total_auto_replied or 0,
        total_escalated=row.total_escalated or 0,
    )


@router.get("", response_model=AgentListResponse)
async def list_agents(
    agent_type: Optional[AgentType] = None,
    is_active: Optional[bool] = None,
    limit: int = 50,
    offset: int = 0,
    session=Depends(get_db),
):
    """List all agents with optional filtering."""
    # Build query with filters
    conditions = []
    params = {"limit": limit, "offset": offset}

    if agent_type:
        conditions.append("agent_type = :agent_type")
        params["agent_type"] = agent_type.value

    if is_active is not None:
        conditions.append("is_active = :is_active")
        params["is_active"] = is_active

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    result = await session.execute(
        text(f"""
            SELECT id, name, agent_type, description,
                   llm_provider, llm_model, confidence_threshold,
                   require_approval_below, is_active,
                   total_processed, total_auto_replied, total_escalated
            FROM mailagent_agents
            WHERE {where_clause}
            ORDER BY name
            LIMIT :limit OFFSET :offset
        """),
        params,
    )
    rows = result.fetchall()

    count_result = await session.execute(
        text(f"SELECT COUNT(*) FROM mailagent_agents WHERE {where_clause}"),
        params,
    )
    total = count_result.scalar()

    return AgentListResponse(
        agents=[
            AgentResponse(
                id=row.id,
                name=row.name,
                agent_type=row.agent_type,
                description=row.description,
                llm_provider=row.llm_provider,
                llm_model=row.llm_model,
                confidence_threshold=float(row.confidence_threshold or 0.7),
                require_approval_below=float(row.require_approval_below or 0.8),
                is_active=row.is_active,
                total_processed=row.total_processed or 0,
                total_auto_replied=row.total_auto_replied or 0,
                total_escalated=row.total_escalated or 0,
            )
            for row in rows
        ],
        total=total,
    )


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
    agent_id: UUID,
    session=Depends(get_db),
):
    """Get a specific agent by ID."""
    result = await session.execute(
        text("""
            SELECT id, name, agent_type, description,
                   llm_provider, llm_model, confidence_threshold,
                   require_approval_below, is_active,
                   total_processed, total_auto_replied, total_escalated
            FROM mailagent_agents
            WHERE id = :agent_id
        """),
        {"agent_id": agent_id},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return AgentResponse(
        id=row.id,
        name=row.name,
        agent_type=row.agent_type,
        description=row.description,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        confidence_threshold=float(row.confidence_threshold or 0.7),
        require_approval_below=float(row.require_approval_below or 0.8),
        is_active=row.is_active,
        total_processed=row.total_processed or 0,
        total_auto_replied=row.total_auto_replied or 0,
        total_escalated=row.total_escalated or 0,
    )


@router.patch("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: UUID,
    agent: AgentUpdate,
    session=Depends(get_db),
):
    """Update an agent."""
    # Build update query dynamically
    updates = []
    params = {"agent_id": agent_id}

    if agent.name is not None:
        updates.append("name = :name")
        params["name"] = agent.name

    if agent.description is not None:
        updates.append("description = :description")
        params["description"] = agent.description

    if agent.llm_provider is not None:
        updates.append("llm_provider = :llm_provider")
        params["llm_provider"] = agent.llm_provider

    if agent.llm_model is not None:
        updates.append("llm_model = :llm_model")
        params["llm_model"] = agent.llm_model

    if agent.confidence_threshold is not None:
        updates.append("confidence_threshold = :confidence_threshold")
        params["confidence_threshold"] = agent.confidence_threshold

    if agent.require_approval_below is not None:
        updates.append("require_approval_below = :require_approval_below")
        params["require_approval_below"] = agent.require_approval_below

    if agent.system_prompt is not None:
        updates.append("system_prompt = :system_prompt")
        params["system_prompt"] = agent.system_prompt

    if agent.custom_instructions is not None:
        updates.append("custom_instructions = :custom_instructions")
        params["custom_instructions"] = agent.custom_instructions

    if agent.is_active is not None:
        updates.append("is_active = :is_active")
        params["is_active"] = agent.is_active

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    updates.append("updated_at = NOW()")
    set_clause = ", ".join(updates)

    result = await session.execute(
        text(f"""
            UPDATE mailagent_agents
            SET {set_clause}
            WHERE id = :agent_id
            RETURNING id, name, agent_type, description,
                      llm_provider, llm_model, confidence_threshold,
                      require_approval_below, is_active,
                      total_processed, total_auto_replied, total_escalated
        """),
        params,
    )
    await session.commit()

    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return AgentResponse(
        id=row.id,
        name=row.name,
        agent_type=row.agent_type,
        description=row.description,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        confidence_threshold=float(row.confidence_threshold or 0.7),
        require_approval_below=float(row.require_approval_below or 0.8),
        is_active=row.is_active,
        total_processed=row.total_processed or 0,
        total_auto_replied=row.total_auto_replied or 0,
        total_escalated=row.total_escalated or 0,
    )


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(
    agent_id: UUID,
    session=Depends(get_db),
):
    """Delete an agent."""
    result = await session.execute(
        text("DELETE FROM mailagent_agents WHERE id = :agent_id RETURNING id"),
        {"agent_id": agent_id},
    )
    await session.commit()

    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Agent not found")


@router.post("/inboxes/{inbox_id}/agents", status_code=status.HTTP_201_CREATED)
async def assign_agent_to_inbox(
    inbox_id: UUID,
    assignment: InboxAgentAssign,
    session=Depends(get_db),
):
    """Assign an agent to an inbox."""
    # Verify inbox exists
    inbox_check = await session.execute(
        text("SELECT id FROM mailagent_inboxes WHERE id = :inbox_id"),
        {"inbox_id": inbox_id},
    )
    if not inbox_check.fetchone():
        raise HTTPException(status_code=404, detail="Inbox not found")

    # Verify agent exists
    agent_check = await session.execute(
        text("SELECT id FROM mailagent_agents WHERE id = :agent_id"),
        {"agent_id": assignment.agent_id},
    )
    if not agent_check.fetchone():
        raise HTTPException(status_code=404, detail="Agent not found")

    # Create assignment
    await session.execute(
        text("""
            INSERT INTO mailagent_inbox_agents (inbox_id, agent_id, priority)
            VALUES (:inbox_id, :agent_id, :priority)
            ON CONFLICT (inbox_id, agent_id) DO UPDATE SET priority = :priority
        """),
        {
            "inbox_id": inbox_id,
            "agent_id": assignment.agent_id,
            "priority": assignment.priority,
        },
    )
    await session.commit()

    return {"status": "assigned", "inbox_id": inbox_id, "agent_id": assignment.agent_id}


@router.delete("/inboxes/{inbox_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_agent_from_inbox(
    inbox_id: UUID,
    agent_id: UUID,
    session=Depends(get_db),
):
    """Remove an agent from an inbox."""
    result = await session.execute(
        text("""
            DELETE FROM mailagent_inbox_agents
            WHERE inbox_id = :inbox_id AND agent_id = :agent_id
            RETURNING inbox_id
        """),
        {"inbox_id": inbox_id, "agent_id": agent_id},
    )
    await session.commit()

    if not result.fetchone():
        raise HTTPException(status_code=404, detail="Assignment not found")


@router.get("/{agent_id}/decisions", response_model=list[AgentDecisionResponse])
async def get_agent_decisions(
    agent_id: UUID,
    limit: int = 50,
    pending_approval: Optional[bool] = None,
    session=Depends(get_db),
):
    """Get recent decisions made by an agent."""
    conditions = ["agent_id = :agent_id"]
    params = {"agent_id": agent_id, "limit": limit}

    if pending_approval is not None:
        if pending_approval:
            conditions.append("requires_approval = true AND approved IS NULL")
        else:
            conditions.append("(requires_approval = false OR approved IS NOT NULL)")

    where_clause = " AND ".join(conditions)

    result = await session.execute(
        text(f"""
            SELECT id, agent_id, message_id, action, confidence,
                   reasoning, requires_approval, approved, created_at
            FROM mailagent_agent_decisions
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        params,
    )
    rows = result.fetchall()

    return [
        AgentDecisionResponse(
            id=row.id,
            agent_id=row.agent_id,
            message_id=row.message_id,
            action=row.action,
            confidence=float(row.confidence),
            reasoning=row.reasoning,
            requires_approval=row.requires_approval,
            approved=row.approved,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.post("/{agent_id}/decisions/{decision_id}/approve")
async def approve_decision(
    agent_id: UUID,
    decision_id: UUID,
    approved: bool = True,
    session=Depends(get_db),
):
    """Approve or reject an agent's decision."""
    result = await session.execute(
        text("""
            UPDATE mailagent_agent_decisions
            SET approved = :approved, approved_at = NOW()
            WHERE id = :decision_id AND agent_id = :agent_id
            RETURNING id, action
        """),
        {"decision_id": decision_id, "agent_id": agent_id, "approved": approved},
    )
    await session.commit()

    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Decision not found")

    return {
        "status": "approved" if approved else "rejected",
        "decision_id": decision_id,
        "action": row.action,
    }


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(
    agent_id: UUID,
    session=Depends(get_db),
):
    """Get metrics for an agent."""
    # Get agent stats
    result = await session.execute(
        text("""
            SELECT
                a.total_processed,
                a.total_auto_replied,
                a.total_escalated,
                AVG(CASE WHEN m.date >= NOW() - INTERVAL '7 days' THEN m.avg_confidence END) as recent_avg_confidence,
                AVG(CASE WHEN m.date >= NOW() - INTERVAL '7 days' THEN m.avg_response_time_seconds END) as recent_avg_response_time
            FROM mailagent_agents a
            LEFT JOIN mailagent_agent_metrics m ON m.agent_id = a.id
            WHERE a.id = :agent_id
            GROUP BY a.id, a.total_processed, a.total_auto_replied, a.total_escalated
        """),
        {"agent_id": agent_id},
    )
    row = result.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "agent_id": agent_id,
        "total_processed": row.total_processed or 0,
        "total_auto_replied": row.total_auto_replied or 0,
        "total_escalated": row.total_escalated or 0,
        "automation_rate": (
            (row.total_auto_replied / row.total_processed * 100)
            if row.total_processed else 0
        ),
        "recent_avg_confidence": float(row.recent_avg_confidence) if row.recent_avg_confidence else None,
        "recent_avg_response_time_sec": float(row.recent_avg_response_time) if row.recent_avg_response_time else None,
    }

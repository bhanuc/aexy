"""Agent factory for creating email agents."""

from typing import Optional
from uuid import UUID

from mailagent.agents.base import EmailAgent, AgentType, AgentConfig
from mailagent.agents.support import SupportAgent
from mailagent.agents.sales import SalesAgent
from mailagent.agents.scheduling import SchedulingAgent
from mailagent.agents.onboarding import OnboardingAgent
from mailagent.agents.recruiting import RecruitingAgent
from mailagent.agents.newsletter import NewsletterAgent
from mailagent.llm import get_llm_provider


AGENT_CLASSES = {
    AgentType.SUPPORT.value: SupportAgent,
    AgentType.SALES.value: SalesAgent,
    AgentType.SCHEDULING.value: SchedulingAgent,
    AgentType.ONBOARDING.value: OnboardingAgent,
    AgentType.RECRUITING.value: RecruitingAgent,
    AgentType.NEWSLETTER.value: NewsletterAgent,
}


def create_agent(
    config: AgentConfig,
    llm_provider_name: str = "gemini",
) -> EmailAgent:
    """Create an email agent instance.

    Args:
        config: Agent configuration
        llm_provider_name: LLM provider to use (claude, gemini)

    Returns:
        EmailAgent instance

    Raises:
        ValueError: If agent type is not supported
    """
    agent_class = AGENT_CLASSES.get(config.agent_type)

    if not agent_class:
        raise ValueError(
            f"Unsupported agent type: {config.agent_type}. "
            f"Supported: {list(AGENT_CLASSES.keys())}"
        )

    # Get LLM provider
    llm = get_llm_provider(llm_provider_name)

    return agent_class(config, llm)


async def create_agent_from_db(agent_id: UUID) -> Optional[EmailAgent]:
    """Create an agent from database configuration.

    Args:
        agent_id: Database ID of the agent

    Returns:
        EmailAgent instance or None if not found
    """
    from mailagent.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(
            text("""
                SELECT a.id, a.agent_type, a.name, a.llm_provider, a.llm_model,
                       a.temperature, a.max_tokens, a.auto_respond,
                       a.confidence_threshold, a.require_approval_below,
                       a.max_daily_responses, a.response_delay_minutes,
                       a.working_hours, a.escalation_email, a.escalation_slack_channel,
                       a.escalation_conditions, a.system_prompt, a.custom_instructions,
                       a.is_active, i.id as inbox_id, i.email as inbox_email
                FROM mailagent_agents a
                LEFT JOIN mailagent_inbox_agents ia ON ia.agent_id = a.id
                LEFT JOIN mailagent_inboxes i ON i.id = ia.inbox_id
                WHERE a.id = :agent_id
            """),
            {"agent_id": agent_id},
        )
        row = result.fetchone()

        if not row or not row.is_active:
            return None

        config = AgentConfig(
            id=row.id,
            name=row.name,
            agent_type=row.agent_type,
            inbox_id=row.inbox_id or UUID('00000000-0000-0000-0000-000000000000'),
            inbox_email=row.inbox_email or "",
            llm_provider=row.llm_provider or "gemini",
            llm_model=row.llm_model or "gemini-2.0-flash",
            temperature=float(row.temperature) if row.temperature else 0.7,
            max_tokens=row.max_tokens or 2000,
            auto_respond=row.auto_respond if row.auto_respond is not None else True,
            confidence_threshold=float(row.confidence_threshold) if row.confidence_threshold else 0.7,
            require_approval_below=float(row.require_approval_below) if row.require_approval_below else 0.8,
            max_daily_responses=row.max_daily_responses or 100,
            response_delay_minutes=row.response_delay_minutes or 5,
            working_hours=row.working_hours,
            escalation_email=row.escalation_email,
            escalation_slack=row.escalation_slack_channel,
            escalation_conditions=row.escalation_conditions or [],
            system_prompt=row.system_prompt,
            custom_instructions=row.custom_instructions,
        )

        return create_agent(config, llm_provider_name=row.llm_provider or "gemini")


async def get_agents_for_inbox(inbox_id: UUID) -> list[EmailAgent]:
    """Get all active agents assigned to an inbox.

    Args:
        inbox_id: Inbox ID

    Returns:
        List of EmailAgent instances
    """
    from mailagent.database import async_session_factory
    from sqlalchemy import text

    async with async_session_factory() as session:
        result = await session.execute(
            text("""
                SELECT a.id, a.agent_type, a.name, a.llm_provider, a.llm_model,
                       a.temperature, a.max_tokens, a.auto_respond,
                       a.confidence_threshold, a.require_approval_below,
                       a.max_daily_responses, a.response_delay_minutes,
                       a.working_hours, a.escalation_email, a.escalation_slack_channel,
                       a.escalation_conditions, a.system_prompt, a.custom_instructions,
                       i.id as inbox_id, i.email as inbox_email, ia.priority
                FROM mailagent_agents a
                JOIN mailagent_inbox_agents ia ON ia.agent_id = a.id
                JOIN mailagent_inboxes i ON i.id = ia.inbox_id
                WHERE ia.inbox_id = :inbox_id
                  AND a.is_active = true
                  AND ia.is_active = true
                ORDER BY ia.priority
            """),
            {"inbox_id": inbox_id},
        )
        rows = result.fetchall()

        agents = []
        for row in rows:
            config = AgentConfig(
                id=row.id,
                name=row.name,
                agent_type=row.agent_type,
                inbox_id=row.inbox_id,
                inbox_email=row.inbox_email or "",
                llm_provider=row.llm_provider or "gemini",
                llm_model=row.llm_model or "gemini-2.0-flash",
                temperature=float(row.temperature) if row.temperature else 0.7,
                max_tokens=row.max_tokens or 2000,
                auto_respond=row.auto_respond if row.auto_respond is not None else True,
                confidence_threshold=float(row.confidence_threshold) if row.confidence_threshold else 0.7,
                require_approval_below=float(row.require_approval_below) if row.require_approval_below else 0.8,
                max_daily_responses=row.max_daily_responses or 100,
                response_delay_minutes=row.response_delay_minutes or 5,
                working_hours=row.working_hours,
                escalation_email=row.escalation_email,
                escalation_slack=row.escalation_slack_channel,
                escalation_conditions=row.escalation_conditions or [],
                system_prompt=row.system_prompt,
                custom_instructions=row.custom_instructions,
            )
            agent = create_agent(config, llm_provider_name=row.llm_provider or "gemini")
            agents.append(agent)

        return agents

"""Shared Slack integration helper functions.

This module contains reusable functions for Slack integration lookups
that are used across multiple services (uptime, notifications, etc.).
"""

import logging
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from aexy.models.integrations import SlackIntegration
from aexy.models.tracking import SlackChannelConfig

logger = logging.getLogger(__name__)

# Notification channel constants
NOTIFICATION_CHANNEL_SLACK = "slack"
NOTIFICATION_CHANNEL_WEBHOOK = "webhook"
NOTIFICATION_CHANNEL_TICKET = "ticket"


async def get_slack_integration_for_workspace(
    db: AsyncSession,
    workspace_id: str,
) -> SlackIntegration | None:
    """Get the active Slack integration for a workspace.

    Checks both workspace_id and organization_id fields since integrations
    may be associated with either.

    Args:
        db: Database session.
        workspace_id: Workspace or organization ID.

    Returns:
        SlackIntegration or None if not found.
    """
    try:
        stmt = select(SlackIntegration).where(
            or_(
                SlackIntegration.workspace_id == workspace_id,
                SlackIntegration.organization_id == workspace_id,
            ),
            SlackIntegration.is_active == True,
        )
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error(f"Database error getting Slack integration for workspace {workspace_id}: {e}")
        return None


async def get_slack_channel_config(
    db: AsyncSession,
    integration_id: str,
) -> SlackChannelConfig | None:
    """Get the first active Slack channel config for an integration.

    Args:
        db: Database session.
        integration_id: Slack integration ID.

    Returns:
        SlackChannelConfig or None if not found.
    """
    try:
        stmt = select(SlackChannelConfig).where(
            SlackChannelConfig.integration_id == integration_id,
            SlackChannelConfig.is_active == True,
        ).limit(1)
        result = await db.execute(stmt)
        return result.scalar_one_or_none()
    except SQLAlchemyError as e:
        logger.error(f"Database error getting Slack channel config for integration {integration_id}: {e}")
        return None


async def get_workspace_notification_channel(
    db: AsyncSession,
    workspace_id: str,
) -> str | None:
    """Get the default Slack channel ID for workspace notifications.

    Looks up the Slack integration and its first configured channel.

    Args:
        db: Database session.
        workspace_id: Workspace or organization ID.

    Returns:
        Slack channel ID or None if not configured.
    """
    integration = await get_slack_integration_for_workspace(db, workspace_id)
    if not integration:
        logger.warning(f"No Slack integration found for workspace/org {workspace_id}")
        return None

    config = await get_slack_channel_config(db, integration.id)
    if config:
        return config.channel_id

    return None


async def check_slack_channel_configured(
    db: AsyncSession,
    workspace_id: str,
) -> bool:
    """Check if Slack is connected with a channel configured for this workspace.

    Args:
        db: Database session.
        workspace_id: Workspace ID.

    Returns:
        True if Slack channel is configured, False otherwise.
    """
    integration = await get_slack_integration_for_workspace(db, workspace_id)
    if not integration:
        return False

    config = await get_slack_channel_config(db, integration.id)
    return config is not None

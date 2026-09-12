"""Platform Admin API endpoints for global system monitoring.

This module provides platform-level admin endpoints accessible only to users
whose email is in the ADMIN_EMAILS environment variable.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aexy.api.developers import get_current_developer_id
from aexy.core.config import get_settings
from aexy.core.database import get_db
from aexy.models.developer import Developer
from aexy.models.notification import EmailNotificationLog, Notification
from aexy.models.workspace import Workspace, WorkspaceMember, WorkspacePlanOverride
from aexy.models.billing import CustomerBilling, Invoice
from aexy.schemas.billing import (
    BillingBreakdownHistoryResponse,
    BillingBreakdownResponse,
    CreateManualInvoiceRequest,
    EffectivePlanResponse,
    InvoiceResponse,
    MarkInvoicePaidRequest,
    PlatformBillingSummaryResponse,
    PlatformBillingSummaryRow,
    PlatformBillingTotals,
    WorkspacePlanOverrideCreate,
    WorkspacePlanOverrideResponse,
)
from aexy.schemas.platform_stats import (
    AiSpendResponse,
    ModuleAdoptionResponse,
    PlatformAlertsResponse,
    PlatformKpi,
    PlatformOverviewResponse,
    PlatformSnapshotRefreshResponse,
    PlatformStatsPoint,
    PlatformStatsSeriesResponse,
    WorkspaceDetailResponse,
)
from aexy.services.developer_service import DeveloperService
from aexy.services.limits_service import LimitsService

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/platform-admin", tags=["platform-admin"])


# =============================================================================
# RESPONSE MODELS
# =============================================================================


class AdminCheckResponse(BaseModel):
    """Response for admin check endpoint."""

    is_admin: bool
    platform_org_id: str | None = None


class AdminDashboardStats(BaseModel):
    """Platform-wide statistics for admin dashboard."""

    total_workspaces: int
    total_users: int
    total_emails_sent: int
    total_notifications: int
    active_workspaces_30d: int
    email_delivery_rate: float
    emails_sent_today: int
    emails_sent_this_week: int
    emails_failed_today: int


class EmailLogDetailResponse(BaseModel):
    """Detailed email log response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    notification_id: str | None
    recipient_email: str
    subject: str
    template_name: str | None
    body_preview: str | None
    ses_message_id: str | None
    status: str
    error_message: str | None
    sent_at: datetime | None
    created_at: datetime
    # Additional metadata from notification
    workspace_id: str | None = None
    workspace_name: str | None = None
    notification_type: str | None = None


class PaginatedEmailLogs(BaseModel):
    """Paginated email log response."""

    items: list[EmailLogDetailResponse]
    total: int
    page: int
    per_page: int
    has_next: bool


class NotificationLogResponse(BaseModel):
    """Notification log response for admin."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    recipient_id: str
    recipient_email: str | None = None
    recipient_name: str | None = None
    event_type: str
    title: str
    body: str
    context: dict
    is_read: bool
    email_sent: bool
    created_at: datetime


class PaginatedNotifications(BaseModel):
    """Paginated notification response."""

    items: list[NotificationLogResponse]
    total: int
    page: int
    per_page: int
    has_next: bool


class WorkspaceAdminResponse(BaseModel):
    """Workspace response for admin view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    slug: str
    type: str
    description: str | None
    owner_id: str
    owner_email: str | None = None
    owner_name: str | None = None
    plan_tier: str | None = None
    member_count: int = 0
    is_active: bool
    created_at: datetime


class PaginatedWorkspaces(BaseModel):
    """Paginated workspace response."""

    items: list[WorkspaceAdminResponse]
    total: int
    page: int
    per_page: int
    has_next: bool


class UserAdminResponse(BaseModel):
    """User response for admin view."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    name: str | None
    avatar_url: str | None
    has_github: bool = False
    has_google: bool = False
    workspace_count: int = 0
    created_at: datetime


class PaginatedUsers(BaseModel):
    """Paginated user response."""

    items: list[UserAdminResponse]
    total: int
    page: int
    per_page: int
    has_next: bool


class ResendEmailResponse(BaseModel):
    """Response for email resend action."""

    success: bool
    message: str
    new_email_log_id: str | None = None


# =============================================================================
# DEPENDENCIES
# =============================================================================


async def get_current_developer(
    developer_id: str = Depends(get_current_developer_id),
    db: AsyncSession = Depends(get_db),
) -> Developer:
    """Get the current developer model."""
    service = DeveloperService(db)
    developer = await service.get_by_id(developer_id)
    if not developer:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Developer not found",
        )
    return developer


async def get_platform_admin(
    current_user: Developer = Depends(get_current_developer),
) -> Developer:
    """Verify user is a platform admin.

    Access is granted per-email via ADMIN_EMAILS. PLATFORM_ORG_ID is only
    used for signup-side seeding (CRM contact, onboarding emails) and does
    not gate admin access — admins don't need a seat in the platform org.
    """
    if current_user.email.lower() not in settings.admin_email_list:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )

    return current_user


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/check", response_model=AdminCheckResponse)
async def check_admin_status(
    current_user: Developer = Depends(get_current_developer),
) -> AdminCheckResponse:
    """Check if the current user is a platform admin.

    Admin access is per-email (ADMIN_EMAILS); platform org membership is
    not required. The org ID is still returned for frontend context.
    """
    return AdminCheckResponse(
        is_admin=current_user.email.lower() in settings.admin_email_list,
        platform_org_id=settings.platform_org_id or None,
    )


@router.get("/dashboard/stats", response_model=AdminDashboardStats)
async def get_dashboard_stats(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> AdminDashboardStats:
    """Get global platform statistics for admin dashboard."""
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=7)
    month_start = today_start - timedelta(days=30)

    # Total workspaces
    workspace_count = await db.scalar(select(func.count(Workspace.id)))

    # Total users
    user_count = await db.scalar(select(func.count(Developer.id)))

    # Active workspaces in last 30 days (has members who logged in)
    active_workspace_count = await db.scalar(
        select(func.count(func.distinct(WorkspaceMember.workspace_id))).where(
            WorkspaceMember.updated_at >= month_start
        )
    )

    # Total emails sent
    total_emails = await db.scalar(select(func.count(EmailNotificationLog.id)))

    # Emails sent today
    emails_today = await db.scalar(
        select(func.count(EmailNotificationLog.id)).where(
            EmailNotificationLog.created_at >= today_start
        )
    )

    # Emails sent this week
    emails_week = await db.scalar(
        select(func.count(EmailNotificationLog.id)).where(
            EmailNotificationLog.created_at >= week_start
        )
    )

    # Failed emails today
    failed_today = await db.scalar(
        select(func.count(EmailNotificationLog.id)).where(
            EmailNotificationLog.created_at >= today_start,
            EmailNotificationLog.status.in_(["failed", "bounced"]),
        )
    )

    # Total notifications
    total_notifications = await db.scalar(select(func.count(Notification.id)))

    # Email delivery rate (delivered / (delivered + failed + bounced))
    delivered_count = await db.scalar(
        select(func.count(EmailNotificationLog.id)).where(
            EmailNotificationLog.status.in_(["sent", "delivered"])
        )
    )
    failed_count = await db.scalar(
        select(func.count(EmailNotificationLog.id)).where(
            EmailNotificationLog.status.in_(["failed", "bounced"])
        )
    )
    total_processed = (delivered_count or 0) + (failed_count or 0)
    delivery_rate = (delivered_count or 0) / total_processed if total_processed > 0 else 1.0

    return AdminDashboardStats(
        total_workspaces=workspace_count or 0,
        total_users=user_count or 0,
        total_emails_sent=total_emails or 0,
        total_notifications=total_notifications or 0,
        active_workspaces_30d=active_workspace_count or 0,
        email_delivery_rate=delivery_rate,
        emails_sent_today=emails_today or 0,
        emails_sent_this_week=emails_week or 0,
        emails_failed_today=failed_today or 0,
    )


@router.get("/emails", response_model=PaginatedEmailLogs)
async def list_email_logs(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    status_filter: str | None = Query(None, description="Filter by status"),
    search: str | None = Query(None, description="Search by recipient email"),
    date_from: datetime | None = Query(None, description="Filter from date"),
    date_to: datetime | None = Query(None, description="Filter to date"),
) -> PaginatedEmailLogs:
    """Get paginated list of all email logs."""
    query = select(EmailNotificationLog).options(
        selectinload(EmailNotificationLog.notification)
    )

    # Apply filters
    if status_filter:
        query = query.where(EmailNotificationLog.status == status_filter)
    if search:
        query = query.where(EmailNotificationLog.recipient_email.ilike(f"%{search}%"))
    if date_from:
        query = query.where(EmailNotificationLog.created_at >= date_from)
    if date_to:
        query = query.where(EmailNotificationLog.created_at <= date_to)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination and ordering
    offset = (page - 1) * per_page
    query = query.order_by(EmailNotificationLog.created_at.desc())
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    logs = result.scalars().all()

    items = []
    for log in logs:
        notification = log.notification
        workspace_id = None
        workspace_name = None
        notification_type = None

        if notification:
            notification_type = notification.event_type
            context = notification.context or {}
            workspace_id = context.get("workspace_id")
            workspace_name = context.get("workspace_name")

        items.append(
            EmailLogDetailResponse(
                id=log.id,
                notification_id=log.notification_id,
                recipient_email=log.recipient_email,
                subject=log.subject,
                template_name=log.template_name,
                body_preview=None,  # Don't expose full body for security
                ses_message_id=log.ses_message_id,
                status=log.status,
                error_message=log.error_message,
                sent_at=log.sent_at,
                created_at=log.created_at,
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                notification_type=notification_type,
            )
        )

    return PaginatedEmailLogs(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        has_next=(page * per_page) < total,
    )


@router.get("/emails/{email_id}", response_model=EmailLogDetailResponse)
async def get_email_log(
    email_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> EmailLogDetailResponse:
    """Get detailed email log by ID."""
    query = (
        select(EmailNotificationLog)
        .options(selectinload(EmailNotificationLog.notification))
        .where(EmailNotificationLog.id == email_id)
    )
    result = await db.execute(query)
    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email log not found",
        )

    notification = log.notification
    workspace_id = None
    workspace_name = None
    notification_type = None

    if notification:
        notification_type = notification.event_type
        context = notification.context or {}
        workspace_id = context.get("workspace_id")
        workspace_name = context.get("workspace_name")

    return EmailLogDetailResponse(
        id=log.id,
        notification_id=log.notification_id,
        recipient_email=log.recipient_email,
        subject=log.subject,
        template_name=log.template_name,
        body_preview=None,
        ses_message_id=log.ses_message_id,
        status=log.status,
        error_message=log.error_message,
        sent_at=log.sent_at,
        created_at=log.created_at,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        notification_type=notification_type,
    )


@router.post("/emails/{email_id}/resend", response_model=ResendEmailResponse)
async def resend_email(
    email_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ResendEmailResponse:
    """Resend a failed email."""
    query = (
        select(EmailNotificationLog)
        .options(selectinload(EmailNotificationLog.notification))
        .where(EmailNotificationLog.id == email_id)
    )
    result = await db.execute(query)
    log = result.scalar_one_or_none()

    if not log:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email log not found",
        )

    if log.status not in ["failed", "bounced"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Can only resend failed or bounced emails",
        )

    # Try to resend the email
    try:
        from aexy.services.email_service import EmailService

        email_service = EmailService()

        # Create new email log for the retry
        new_log = EmailNotificationLog(
            notification_id=log.notification_id,
            recipient_email=log.recipient_email,
            subject=log.subject,
            template_name=log.template_name,
            status="pending",
        )
        db.add(new_log)
        await db.flush()

        # Send the email
        success = await email_service.send_raw_email(
            to_email=log.recipient_email,
            subject=log.subject,
            html_body=f"<p>This is a resent email. Original subject: {log.subject}</p>",
        )

        if success:
            new_log.status = "sent"
            new_log.sent_at = datetime.now(timezone.utc)
            await db.commit()
            return ResendEmailResponse(
                success=True,
                message="Email resent successfully",
                new_email_log_id=new_log.id,
            )
        else:
            new_log.status = "failed"
            new_log.error_message = "Failed to send email"
            await db.commit()
            return ResendEmailResponse(
                success=False,
                message="Failed to resend email",
                new_email_log_id=new_log.id,
            )

    except Exception as e:
        logger.error(f"Failed to resend email {email_id}: {e}")
        await db.rollback()
        return ResendEmailResponse(
            success=False,
            message="Error resending email. Check server logs for details.",
        )


@router.get("/notifications", response_model=PaginatedNotifications)
async def list_notifications(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    event_type: str | None = Query(None, description="Filter by event type"),
    search: str | None = Query(None, description="Search in title or body"),
) -> PaginatedNotifications:
    """Get paginated list of all notifications."""
    query = select(Notification).options(selectinload(Notification.recipient))

    # Apply filters
    if event_type:
        query = query.where(Notification.event_type == event_type)
    if search:
        query = query.where(
            Notification.title.ilike(f"%{search}%")
            | Notification.body.ilike(f"%{search}%")
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination and ordering
    offset = (page - 1) * per_page
    query = query.order_by(Notification.created_at.desc())
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    notifications = result.scalars().all()

    items = []
    for notification in notifications:
        recipient = notification.recipient
        items.append(
            NotificationLogResponse(
                id=notification.id,
                recipient_id=notification.recipient_id,
                recipient_email=recipient.email if recipient else None,
                recipient_name=recipient.name if recipient else None,
                event_type=notification.event_type,
                title=notification.title,
                body=notification.body,
                context=notification.context or {},
                is_read=notification.is_read,
                email_sent=notification.email_sent,
                created_at=notification.created_at,
            )
        )

    return PaginatedNotifications(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        has_next=(page * per_page) < total,
    )


@router.get("/workspaces", response_model=PaginatedWorkspaces)
async def list_workspaces(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: str | None = Query(None, description="Search by name or slug"),
    plan_tier: str | None = Query(None, description="Filter by plan tier"),
) -> PaginatedWorkspaces:
    """Get paginated list of all workspaces."""
    query = select(Workspace).options(
        selectinload(Workspace.owner),
        selectinload(Workspace.plan),
        selectinload(Workspace.members),
    )

    # Apply filters
    if search:
        query = query.where(
            Workspace.name.ilike(f"%{search}%") | Workspace.slug.ilike(f"%{search}%")
        )
    if plan_tier:
        from aexy.models.plan import Plan

        query = query.join(Workspace.plan).where(Plan.tier == plan_tier)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination and ordering
    offset = (page - 1) * per_page
    query = query.order_by(Workspace.created_at.desc())
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    workspaces = result.scalars().unique().all()

    items = []
    for workspace in workspaces:
        owner = workspace.owner
        plan = workspace.plan
        items.append(
            WorkspaceAdminResponse(
                id=workspace.id,
                name=workspace.name,
                slug=workspace.slug,
                type=workspace.type,
                description=workspace.description,
                owner_id=workspace.owner_id,
                owner_email=owner.email if owner else None,
                owner_name=owner.name if owner else None,
                plan_tier=plan.tier if plan else None,
                member_count=len(workspace.members) if workspace.members else 0,
                is_active=workspace.is_active,
                created_at=workspace.created_at,
            )
        )

    return PaginatedWorkspaces(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        has_next=(page * per_page) < total,
    )


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=100),
    search: str | None = Query(None, description="Search by email or name"),
) -> PaginatedUsers:
    """Get paginated list of all users."""
    query = select(Developer).options(
        selectinload(Developer.github_connection),
        selectinload(Developer.google_connection),
    )

    # Apply filters
    if search:
        query = query.where(
            Developer.email.ilike(f"%{search}%") | Developer.name.ilike(f"%{search}%")
        )

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = await db.scalar(count_query) or 0

    # Apply pagination and ordering
    offset = (page - 1) * per_page
    query = query.order_by(Developer.created_at.desc())
    query = query.offset(offset).limit(per_page)

    result = await db.execute(query)
    users = result.scalars().all()

    # Get workspace counts for users
    workspace_counts: dict[str, int] = {}
    if users:
        user_ids = [u.id for u in users]
        counts_query = (
            select(
                WorkspaceMember.developer_id,
                func.count(WorkspaceMember.workspace_id).label("count"),
            )
            .where(WorkspaceMember.developer_id.in_(user_ids))
            .group_by(WorkspaceMember.developer_id)
        )
        counts_result = await db.execute(counts_query)
        for row in counts_result:
            workspace_counts[row.developer_id] = row.count

    items = []
    for user in users:
        items.append(
            UserAdminResponse(
                id=user.id,
                email=user.email,
                name=user.name,
                avatar_url=user.avatar_url,
                has_github=user.github_connection is not None,
                has_google=user.google_connection is not None,
                workspace_count=workspace_counts.get(user.id, 0),
                created_at=user.created_at,
            )
        )

    return PaginatedUsers(
        items=items,
        total=total,
        page=page,
        per_page=per_page,
        has_next=(page * per_page) < total,
    )


# =============================================================================
# AI BENCHMARKING & FEEDBACK REVIEW
# =============================================================================


@router.get("/ai-benchmarking")
async def get_ai_benchmarking(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
    group_by: str = Query("day", pattern="^(hour|day|week|month)$"),
):
    """Get AI benchmarking dashboard data (admin only)."""
    from aexy.services.ai_feedback_service import AIFeedbackService

    service = AIFeedbackService(db)
    return await service.get_benchmarking(days=days, group_by=group_by)


@router.get("/ai-feedback")
async def list_ai_feedback(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    entity_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=100),
):
    """List all AI feedback for review (admin only)."""
    from aexy.services.ai_feedback_service import AIFeedbackService

    service = AIFeedbackService(db)
    result = await service.list_feedback(
        entity_type=entity_type,
        page=page,
        limit=limit,
    )
    return {
        "items": [
            {
                "id": str(fb.id),
                "entity_type": fb.entity_type,
                "entity_id": str(fb.entity_id),
                "workspace_id": str(fb.workspace_id),
                "developer_id": str(fb.developer_id),
                "rating": fb.rating,
                "comment": fb.comment,
                "tags": fb.tags,
                "created_at": fb.created_at.isoformat() if fb.created_at else None,
            }
            for fb in result["items"]
        ],
        "total": result["total"],
        "page": result["page"],
        "limit": result["limit"],
    }


# =============================================================================
# WORKSPACE PLAN OVERRIDE MANAGEMENT
# =============================================================================


@router.post(
    "/workspaces/{workspace_id}/plan-override",
    response_model=WorkspacePlanOverrideResponse,
    status_code=201,
)
async def create_or_update_plan_override(
    workspace_id: str,
    data: WorkspacePlanOverrideCreate,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanOverrideResponse:
    """Create or update a workspace plan override.

    If an override already exists for this workspace, it will be updated.
    Otherwise a new override is created.
    """
    # Verify workspace exists
    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Check for existing override
    stmt = select(WorkspacePlanOverride).where(
        WorkspacePlanOverride.workspace_id == workspace_id
    )
    result = await db.execute(stmt)
    override = result.scalar_one_or_none()

    update_fields = data.model_dump(exclude_unset=True)
    update_fields["configured_by"] = admin.email

    if override:
        # Update existing override
        for field, value in update_fields.items():
            setattr(override, field, value)
    else:
        # Create new override
        override = WorkspacePlanOverride(
            workspace_id=workspace_id,
            **update_fields,
        )
        db.add(override)

    await db.flush()
    await db.refresh(override)
    return WorkspacePlanOverrideResponse.model_validate(override)


@router.get(
    "/workspaces/{workspace_id}/plan-override",
    response_model=WorkspacePlanOverrideResponse,
)
async def get_plan_override(
    workspace_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkspacePlanOverrideResponse:
    """Get the current plan override for a workspace."""
    stmt = select(WorkspacePlanOverride).where(
        WorkspacePlanOverride.workspace_id == workspace_id
    )
    result = await db.execute(stmt)
    override = result.scalar_one_or_none()

    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No plan override found for this workspace",
        )

    return WorkspacePlanOverrideResponse.model_validate(override)


@router.delete("/workspaces/{workspace_id}/plan-override")
async def delete_plan_override(
    workspace_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Remove a workspace plan override, reverting to the base plan."""
    stmt = select(WorkspacePlanOverride).where(
        WorkspacePlanOverride.workspace_id == workspace_id
    )
    result = await db.execute(stmt)
    override = result.scalar_one_or_none()

    if not override:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No plan override found for this workspace",
        )

    await db.delete(override)
    await db.flush()
    return {"status": "deleted"}


@router.get(
    "/workspaces/{workspace_id}/effective-plan",
    response_model=EffectivePlanResponse,
)
async def get_effective_plan(
    workspace_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> EffectivePlanResponse:
    """Preview the effective plan for a workspace with overrides applied."""
    # Verify workspace exists and get its owner for plan resolution
    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    limits_service = LimitsService(db)
    effective = await limits_service.get_effective_plan(
        developer_id=workspace.owner_id,
        workspace_id=workspace_id,
    )

    response_fields = EffectivePlanResponse.model_fields.keys()
    return EffectivePlanResponse(**{k: v for k, v in vars(effective).items() if k in response_fields})


@router.get(
    "/plan-overrides",
    response_model=list[WorkspacePlanOverrideResponse],
)
async def list_plan_overrides(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> list[WorkspacePlanOverrideResponse]:
    """List all workspaces with plan overrides."""
    stmt = select(WorkspacePlanOverride).order_by(
        WorkspacePlanOverride.created_at.desc()
    )
    result = await db.execute(stmt)
    overrides = result.scalars().all()

    return [
        WorkspacePlanOverrideResponse.model_validate(override)
        for override in overrides
    ]


# =============================================================================
# INVOICE MANAGEMENT
# =============================================================================


@router.post("/invoices", response_model=InvoiceResponse, status_code=201)
async def create_manual_invoice(
    data: CreateManualInvoiceRequest,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    """Create a manual invoice for bank transfer or offline payment."""
    # Verify workspace exists and get its owner
    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == data.workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Look up or create CustomerBilling for the workspace owner
    cb_result = await db.execute(
        select(CustomerBilling).where(
            CustomerBilling.developer_id == workspace.owner_id
        )
    )
    customer = cb_result.scalar_one_or_none()

    if not customer:
        # Look up the owner to get their email for billing
        owner_result = await db.execute(
            select(Developer).where(Developer.id == workspace.owner_id)
        )
        owner = owner_result.scalar_one_or_none()

        customer = CustomerBilling(
            developer_id=workspace.owner_id,
            billing_email=owner.email if owner else None,
            billing_name=owner.name if owner else None,
        )
        db.add(customer)
        await db.flush()

    invoice = Invoice(
        workspace_id=data.workspace_id,
        customer_id=customer.id,
        stripe_invoice_id=None,
        status="open",
        subtotal_cents=data.amount_cents,
        tax_cents=0,
        total_cents=data.amount_cents,
        amount_paid_cents=0,
        amount_due_cents=data.amount_cents,
        payment_method=data.payment_method,
        description=data.description,
        due_date=data.due_date,
        currency=data.currency,
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)

    logger.info(
        f"Admin {admin.email} created manual invoice {invoice.id} "
        f"for workspace {data.workspace_id}: {data.amount_cents} cents"
    )

    return InvoiceResponse.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/mark-paid",
    response_model=InvoiceResponse,
)
async def mark_invoice_paid(
    invoice_id: str,
    data: MarkInvoicePaidRequest,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    """Mark an invoice as paid (manual reconciliation)."""
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found",
        )

    if invoice.status == "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice is already paid",
        )

    if invoice.status == "void":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot mark a voided invoice as paid",
        )

    invoice.status = "paid"
    invoice.amount_paid_cents = invoice.total_cents
    invoice.amount_due_cents = 0
    invoice.paid_at = data.payment_date or datetime.now(timezone.utc)
    invoice.bank_transfer_reference = data.bank_transfer_reference
    invoice.manual_payment_note = data.payment_note
    invoice.marked_paid_by = admin.email

    await db.flush()
    await db.refresh(invoice)

    logger.info(
        f"Admin {admin.email} marked invoice {invoice_id} as paid"
    )

    return InvoiceResponse.model_validate(invoice)


@router.post(
    "/invoices/{invoice_id}/void",
    response_model=InvoiceResponse,
)
async def void_invoice(
    invoice_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    """Void an invoice."""
    result = await db.execute(
        select(Invoice).where(Invoice.id == invoice_id)
    )
    invoice = result.scalar_one_or_none()

    if not invoice:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invoice not found",
        )

    if invoice.status == "paid":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot void a paid invoice",
        )

    if invoice.status == "void":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invoice is already voided",
        )

    invoice.status = "void"
    invoice.amount_due_cents = 0

    await db.flush()
    await db.refresh(invoice)

    logger.info(
        f"Admin {admin.email} voided invoice {invoice_id}"
    )

    return InvoiceResponse.model_validate(invoice)


@router.get("/invoices", response_model=list[InvoiceResponse])
async def list_invoices(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
    status_filter: str | None = Query(None, alias="status", description="Filter by status"),
    payment_method: str | None = Query(None, description="Filter by payment method"),
    workspace_id: str | None = Query(None, description="Filter by workspace ID"),
    limit: int = Query(50, ge=1, le=200),
) -> list[InvoiceResponse]:
    """List all invoices with optional filters."""
    query = select(Invoice)

    if status_filter:
        query = query.where(Invoice.status == status_filter)
    if payment_method:
        query = query.where(Invoice.payment_method == payment_method)
    if workspace_id:
        query = query.where(Invoice.workspace_id == workspace_id)

    query = query.order_by(Invoice.created_at.desc()).limit(limit)

    result = await db.execute(query)
    invoices = result.scalars().all()

    return [InvoiceResponse.model_validate(inv) for inv in invoices]


@router.post(
    "/workspaces/{workspace_id}/generate-invoice",
    response_model=InvoiceResponse,
    status_code=201,
)
async def generate_invoice_from_usage(
    workspace_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> InvoiceResponse:
    """Generate an invoice from workspace usage for the current billing period."""
    from aexy.models.workspace import WorkspaceSubscription
    from aexy.services.postpaid_billing_service import PostpaidBillingService

    # Verify workspace exists
    ws_result = await db.execute(
        select(Workspace).where(Workspace.id == workspace_id)
    )
    workspace = ws_result.scalar_one_or_none()
    if not workspace:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )

    # Determine billing period from WorkspaceSubscription, or default to current month
    sub_result = await db.execute(
        select(WorkspaceSubscription).where(
            WorkspaceSubscription.workspace_id == workspace_id
        )
    )
    sub = sub_result.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if sub and sub.current_period_start and sub.current_period_end:
        period_start = sub.current_period_start
        period_end = sub.current_period_end
    else:
        # Default to current calendar month
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Next month start
        if now.month == 12:
            period_end = period_start.replace(year=now.year + 1, month=1)
        else:
            period_end = period_start.replace(month=now.month + 1)

    # Calculate charges
    billing_service = PostpaidBillingService(db)
    charges = await billing_service.calculate_period_charges(
        workspace_id=workspace_id,
        period_start=period_start,
        period_end=period_end,
    )

    if "error" in charges:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=charges["error"],
        )

    total_cents = charges.get("total_cents", 0)
    if total_cents <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No charges to invoice for this period",
        )

    # Look up or create CustomerBilling for the workspace owner
    cb_result = await db.execute(
        select(CustomerBilling).where(
            CustomerBilling.developer_id == workspace.owner_id
        )
    )
    customer = cb_result.scalar_one_or_none()

    if not customer:
        owner_result = await db.execute(
            select(Developer).where(Developer.id == workspace.owner_id)
        )
        owner = owner_result.scalar_one_or_none()

        customer = CustomerBilling(
            developer_id=workspace.owner_id,
            billing_email=owner.email if owner else None,
            billing_name=owner.name if owner else None,
        )
        db.add(customer)
        await db.flush()

    # Build description from charge breakdown
    description_parts = [
        f"Usage invoice for {period_start.strftime('%Y-%m-%d')} to {period_end.strftime('%Y-%m-%d')}",
    ]
    if charges.get("seat_charges_cents", 0) > 0:
        description_parts.append(
            f"Seats: {charges['seat_count']} x ${charges['seat_charges_cents'] / 100:.2f}"
        )
    if charges.get("usage_charges_cents", 0) > 0:
        description_parts.append(
            f"Usage: ${charges['usage_charges_cents'] / 100:.2f}"
        )

    invoice = Invoice(
        workspace_id=workspace_id,
        customer_id=customer.id,
        stripe_invoice_id=None,
        status="open",
        subtotal_cents=total_cents,
        tax_cents=0,
        total_cents=total_cents,
        amount_paid_cents=0,
        amount_due_cents=total_cents,
        payment_method="bank_transfer",
        description="\n".join(description_parts),
        period_start=period_start,
        period_end=period_end,
        currency="usd",
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)

    logger.info(
        f"Admin {admin.email} generated usage invoice {invoice.id} "
        f"for workspace {workspace_id}: {total_cents} cents"
    )

    return InvoiceResponse.model_validate(invoice)


# =============================================================================
# PLATFORM BILLING (cross-workspace)
# =============================================================================


@router.get(
    "/billing/breakdown",
    response_model=BillingBreakdownResponse,
)
async def admin_get_breakdown(
    workspace_id: str,
    period: str = "current",
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> BillingBreakdownResponse:
    """Platform-admin breakdown for a chosen workspace. Includes margin."""
    from aexy.services.billing_breakdown_service import BillingBreakdownService

    period_start: datetime | None = None
    period_end: datetime | None = None
    if period and period != "current":
        if period == "previous":
            now = datetime.now(timezone.utc)
            this_start = now.replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            )
            if this_start.month == 1:
                period_start = this_start.replace(
                    year=this_start.year - 1, month=12
                )
            else:
                period_start = this_start.replace(month=this_start.month - 1)
            period_end = this_start
        else:
            try:
                year_str, month_str = period.split("-")
                year_int = int(year_str)
                month_int = int(month_str)
                period_start = datetime(
                    year_int, month_int, 1, tzinfo=timezone.utc
                )
                if month_int == 12:
                    period_end = datetime(
                        year_int + 1, 1, 1, tzinfo=timezone.utc
                    )
                else:
                    period_end = datetime(
                        year_int, month_int + 1, 1, tzinfo=timezone.utc
                    )
            except (ValueError, AttributeError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="period must be 'current', 'previous', or 'YYYY-MM'",
                )

    service = BillingBreakdownService(db, include_margin=True)
    try:
        result = await service.get_breakdown(
            workspace_id, period_start=period_start, period_end=period_end
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return BillingBreakdownResponse.model_validate(result)


@router.get(
    "/billing/breakdown/history",
    response_model=BillingBreakdownHistoryResponse,
)
async def admin_get_breakdown_history(
    workspace_id: str,
    months: int = 6,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> BillingBreakdownHistoryResponse:
    """Platform-admin: history for a chosen workspace, with margin."""
    from aexy.services.billing_breakdown_service import BillingBreakdownService

    if months < 1 or months > 24:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="months must be between 1 and 24",
        )

    service = BillingBreakdownService(db, include_margin=True)
    try:
        result = await service.get_history(workspace_id, months=months)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        )
    return BillingBreakdownHistoryResponse.model_validate(result)


@router.get(
    "/billing/summary",
    response_model=PlatformBillingSummaryResponse,
)
async def admin_get_billing_summary(
    page: int = 1,
    per_page: int = 25,
    plan_tier: str | None = None,
    billing_model: str | None = None,
    search: str | None = None,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformBillingSummaryResponse:
    """Cross-workspace billing summary table for the platform-admin page.

    Returns one row per workspace with current-period totals + margin.
    Filters: plan_tier, billing_model, search (workspace name).

    Filters are pushed into the SQL query so `total` and pagination both
    reflect the filtered set. plan_tier joins on `Workspace.plan_id → Plan.tier`
    (workspace plan overrides are not considered for filtering — they don't
    change the workspace's nominal tier in admin terms). billing_model joins
    on `WorkspaceSubscription.billing_model`; workspaces without an active
    subscription row are excluded when this filter is set.
    """
    from aexy.models.plan import Plan
    from aexy.models.workspace import WorkspaceSubscription
    from aexy.services.billing_breakdown_service import BillingBreakdownService

    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 25

    ws_stmt = select(Workspace).where(Workspace.is_active == True)  # noqa: E712
    if search:
        ws_stmt = ws_stmt.where(Workspace.name.ilike(f"%{search}%"))
    if plan_tier:
        ws_stmt = ws_stmt.join(Plan, Plan.id == Workspace.plan_id).where(
            Plan.tier == plan_tier
        )
    if billing_model:
        ws_stmt = ws_stmt.join(
            WorkspaceSubscription,
            WorkspaceSubscription.workspace_id == Workspace.id,
        ).where(WorkspaceSubscription.billing_model == billing_model)

    total_stmt = select(func.count()).select_from(ws_stmt.subquery())
    total = int((await db.scalar(total_stmt)) or 0)

    ws_stmt = (
        ws_stmt.order_by(Workspace.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    ws_result = await db.execute(ws_stmt)
    workspaces = list(ws_result.scalars().all())

    service = BillingBreakdownService(db, include_margin=True)
    rows: list[PlatformBillingSummaryRow] = []
    for ws in workspaces:
        try:
            breakdown = await service.get_breakdown(ws.id)
        except Exception:
            logger.exception("Breakdown failed for workspace %s", ws.id)
            continue

        margin = breakdown.get("margin") or {}
        rows.append(
            PlatformBillingSummaryRow(
                workspace_id=ws.id,
                workspace_name=ws.name,
                plan_tier=breakdown.get("plan_tier", ""),
                billing_model=breakdown.get("billing_model", ""),
                period_start=breakdown["period_start"],
                period_end=breakdown["period_end"],
                total_cents=breakdown.get("total_cents", 0.0),
                base_cost_cents=margin.get("base_cost_cents", 0.0),
                margin_cents=margin.get("margin_cents", 0.0),
                seat_count=int(
                    breakdown.get("info_counters", {}).get("seat_count", 0)
                ),
            )
        )

    return PlatformBillingSummaryResponse(
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
    )


async def _billing_totals_live(
    db: AsyncSession, period_start: datetime, period_end: datetime
) -> PlatformBillingTotals:
    """Price every active workspace, now.

    One `BillingBreakdownService` pass per workspace. This is what the
    endpoint used to do on every request; it is now the fallback for periods
    no snapshot covers, and what the nightly snapshot itself records.
    """
    from aexy.services.billing_breakdown_service import BillingBreakdownService

    ws_result = await db.execute(
        select(Workspace).where(Workspace.is_active.is_(True))
    )
    workspaces = list(ws_result.scalars().all())

    service = BillingBreakdownService(db, include_margin=True)
    total_revenue = 0.0
    total_base_cost = 0.0
    total_margin = 0.0
    by_tier: dict[str, float] = {}
    by_model: dict[str, float] = {}
    rows: list[PlatformBillingSummaryRow] = []

    for ws in workspaces:
        try:
            breakdown = await service.get_breakdown(
                ws.id, period_start=period_start, period_end=period_end
            )
        except Exception:
            logger.exception("Totals breakdown failed for workspace %s", ws.id)
            continue
        margin = breakdown.get("margin") or {}
        ws_total = float(breakdown.get("total_cents", 0.0))
        total_revenue += ws_total
        total_base_cost += float(margin.get("base_cost_cents", 0.0))
        total_margin += float(margin.get("margin_cents", 0.0))
        tier = breakdown.get("plan_tier") or "unknown"
        model = breakdown.get("billing_model") or "unknown"
        by_tier[tier] = by_tier.get(tier, 0.0) + ws_total
        by_model[model] = by_model.get(model, 0.0) + ws_total

        rows.append(
            PlatformBillingSummaryRow(
                workspace_id=ws.id,
                workspace_name=ws.name,
                plan_tier=tier,
                billing_model=model,
                period_start=breakdown["period_start"],
                period_end=breakdown["period_end"],
                total_cents=ws_total,
                base_cost_cents=float(margin.get("base_cost_cents", 0.0)),
                margin_cents=float(margin.get("margin_cents", 0.0)),
                seat_count=int(
                    breakdown.get("info_counters", {}).get("seat_count", 0)
                ),
            )
        )

    rows.sort(key=lambda r: r.total_cents, reverse=True)

    return PlatformBillingTotals(
        period_start=period_start,
        period_end=period_end,
        total_revenue_cents=total_revenue,
        total_base_cost_cents=total_base_cost,
        total_margin_cents=total_margin,
        workspace_count=len(rows),
        by_plan_tier=by_tier,
        by_billing_model=by_model,
        top_workspaces=rows[:10],
    )


@router.get(
    "/billing/totals",
    response_model=PlatformBillingTotals,
)
async def admin_get_billing_totals(
    period: str = "current",
    live: bool = False,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformBillingTotals:
    """Aggregate totals across all workspaces for the period.

    Served from last night's `platform_daily_stats` row for the current
    period. Computing it meant a full billing breakdown per workspace on
    every request, uncached — work that grows with the tenant count and that
    the nightly snapshot already does. `live=true` forces the slow path, and
    so does asking for a period the snapshot does not cover.
    """
    now = datetime.now(timezone.utc)
    if period == "previous":
        this_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if this_start.month == 1:
            period_start = this_start.replace(year=this_start.year - 1, month=12)
        else:
            period_start = this_start.replace(month=this_start.month - 1)
        period_end = this_start
    else:
        period_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if now.month == 12:
            period_end = period_start.replace(year=now.year + 1, month=1)
        else:
            period_end = period_start.replace(month=now.month + 1)

    if period != "previous" and not live:
        from aexy.services.platform_stats_service import PlatformStatsService

        snapshot = await PlatformStatsService(db).latest()
        # A snapshot from a previous month describes a period that has closed;
        # it cannot stand in for this one.
        if snapshot is not None and snapshot.day >= period_start.date():
            computed_at = snapshot.computed_at
            if computed_at is not None and computed_at.tzinfo is None:
                computed_at = computed_at.replace(tzinfo=timezone.utc)
            return PlatformBillingTotals(
                period_start=period_start,
                period_end=period_end,
                # Where the numbers came from and when. This endpoint used to
                # compute live on every call, so "current" was true by
                # construction; served from a snapshot it can be a month old
                # if the daily job has stopped, and the caller has no other
                # way to tell. `?live=true` forces the slow path.
                computed_at=computed_at,
                is_stale=(
                    computed_at is None
                    or datetime.now(timezone.utc) - computed_at > STALE_AFTER
                ),
                total_revenue_cents=snapshot.revenue_cents,
                total_base_cost_cents=snapshot.base_cost_cents,
                total_margin_cents=snapshot.margin_cents,
                workspace_count=snapshot.revenue_workspace_count,
                by_plan_tier=snapshot.revenue_by_plan_tier or {},
                by_billing_model=snapshot.revenue_by_billing_model or {},
                top_workspaces=[
                    PlatformBillingSummaryRow.model_validate(row)
                    for row in (snapshot.top_workspaces or [])
                ],
            )

    return await _billing_totals_live(db, period_start, period_end)


# =============================================================================
# PLATFORM STATISTICS (daily snapshots)
# =============================================================================
#
# Everything above computes live and so can only describe this instant. These
# read `platform_daily_stats`, which a daily Temporal job writes, because the
# questions worth asking — is MRR growing, are signups accelerating, how many
# workspaces cancelled — are about change over time and cannot be recovered
# from the live tables afterwards.

#: A snapshot older than this means the daily job is not running, and every
#: figure on the page is staler than its label suggests.
STALE_AFTER = timedelta(hours=36)


#: Fields a snapshot can only know on the day it describes. A backfilled row
#: stores zero for these because the source rows no longer say what they were,
#: not because they were zero — so they have nothing to compare against.
UNRECOVERABLE_FIELDS = frozenset(
    {
        "mrr_cents",
        "revenue_cents",
        "base_cost_cents",
        "margin_cents",
        "paying_workspaces",
        "trialing_workspaces",
        "billable_seats",
        "invoices_open",
        "invoices_open_cents",
        "invoices_overdue",
        "invoices_overdue_cents",
    }
)


def _kpi(current: Any, previous: Any, field: str) -> PlatformKpi:
    value = float(getattr(current, field, 0) or 0)
    # A partial day stores zero for what it could not recover. Comparing
    # against it reported the whole of MRR as growth since last month, which
    # is the exact mistake `is_partial` exists to prevent — the chart already
    # breaks its line there; the cards were still drawing one.
    if previous is None or (
        getattr(previous, "is_partial", False) and field in UNRECOVERABLE_FIELDS
    ):
        return PlatformKpi(value=value)
    before = float(getattr(previous, field, 0) or 0)
    delta = value - before
    # A move from zero has no meaningful percentage — "up 100%" from nothing
    # is noise, not growth.
    delta_pct = (delta / before * 100.0) if before else None
    return PlatformKpi(
        value=value, previous=before, delta=delta, delta_pct=delta_pct
    )


@router.get("/stats/overview", response_model=PlatformOverviewResponse)
async def admin_stats_overview(
    comparison_days: int = Query(30, ge=1, le=365),
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformOverviewResponse:
    """Headline platform numbers, each against what it was `comparison_days` ago."""
    from aexy.services.platform_stats_service import (
        PlatformStatsService,
        plan_tier_counts,
    )

    service = PlatformStatsService(db)
    current = await service.latest()
    tiers = await plan_tier_counts(db)

    if current is None:
        # Nothing written yet: a fresh install, or the job has never run. Say
        # so with empty KPIs rather than inventing zeros that look like data.
        empty = PlatformKpi(value=0.0)
        return PlatformOverviewResponse(
            is_stale=True,
            comparison_days=comparison_days,
            mrr_cents=empty,
            revenue_cents=empty,
            margin_cents=empty,
            base_cost_cents=empty,
            paying_workspaces=empty,
            trialing_workspaces=empty,
            workspaces_total=empty,
            workspaces_active_30d=empty,
            developers_total=empty,
            billable_seats=empty,
            llm_billed_cents=empty,
            workspaces_by_plan_tier=tiers,
            notes=[
                (
                    "No platform snapshot has been written yet. The daily job "
                    "fills this in; use Refresh to write one now."
                )
            ],
        )

    previous = await service.on_day(
        current.day - timedelta(days=comparison_days)
    )
    computed_at = current.computed_at
    if computed_at is not None and computed_at.tzinfo is None:
        computed_at = computed_at.replace(tzinfo=timezone.utc)
    is_stale = (
        computed_at is None
        or datetime.now(timezone.utc) - computed_at > STALE_AFTER
    )

    return PlatformOverviewResponse(
        as_of=current.day,
        computed_at=computed_at,
        is_stale=is_stale,
        comparison_days=comparison_days,
        mrr_cents=_kpi(current, previous, "mrr_cents"),
        revenue_cents=_kpi(current, previous, "revenue_cents"),
        margin_cents=_kpi(current, previous, "margin_cents"),
        base_cost_cents=_kpi(current, previous, "base_cost_cents"),
        paying_workspaces=_kpi(current, previous, "paying_workspaces"),
        trialing_workspaces=_kpi(current, previous, "trialing_workspaces"),
        workspaces_total=_kpi(current, previous, "workspaces_total"),
        workspaces_active_30d=_kpi(current, previous, "workspaces_active_30d"),
        developers_total=_kpi(current, previous, "developers_total"),
        billable_seats=_kpi(current, previous, "billable_seats"),
        llm_billed_cents=_kpi(current, previous, "llm_billed_cents"),
        subscriptions_by_status=current.subscriptions_by_status or {},
        revenue_by_plan_tier=current.revenue_by_plan_tier or {},
        revenue_by_billing_model=current.revenue_by_billing_model or {},
        workspaces_by_plan_tier=tiers,
        invoices_open=current.invoices_open,
        invoices_open_cents=current.invoices_open_cents,
        invoices_overdue=current.invoices_overdue,
        invoices_overdue_cents=current.invoices_overdue_cents,
        notes=list(current.notes or []),
    )


@router.get("/stats/series", response_model=PlatformStatsSeriesResponse)
async def admin_stats_series(
    days: int = Query(90, ge=7, le=730),
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformStatsSeriesResponse:
    """The daily series behind the growth and revenue charts, oldest first."""
    from aexy.services.platform_stats_service import PlatformStatsService

    rows = await PlatformStatsService(db).series(days)
    points = [
        PlatformStatsPoint(
            day=row.day,
            workspaces_total=row.workspaces_total,
            workspaces_created=row.workspaces_created,
            workspaces_active_30d=row.workspaces_active_30d,
            developers_total=row.developers_total,
            developers_created=row.developers_created,
            paying_workspaces=row.paying_workspaces,
            trialing_workspaces=row.trialing_workspaces,
            subscriptions_canceled=row.subscriptions_canceled,
            billable_seats=row.billable_seats,
            mrr_cents=row.mrr_cents,
            revenue_cents=row.revenue_cents,
            base_cost_cents=row.base_cost_cents,
            margin_cents=row.margin_cents,
            llm_requests=row.llm_requests,
            llm_tokens=row.llm_tokens,
            llm_billed_cents=row.llm_billed_cents,
            llm_base_cost_cents=row.llm_base_cost_cents,
            # A backfilled day could not recover its subscription and revenue
            # figures. The chart uses this to break the line instead of
            # drawing a drop to zero that never happened. A column, not a
            # phrase found inside `notes`: rewording a log message should not
            # quietly change what the chart draws.
            is_partial=row.is_partial,
        )
        for row in rows
    ]
    return PlatformStatsSeriesResponse(days=days, points=points)


@router.post("/stats/refresh", response_model=PlatformSnapshotRefreshResponse)
async def admin_stats_refresh(
    backfill_days: int = Query(0, ge=0, le=365),
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformSnapshotRefreshResponse:
    """Recompute today's snapshot now.

    The schedule writes one a day; this exists so the page is usable before
    the first run, and so an admin who has just changed a plan can see the
    effect without waiting until tomorrow. Today's row is computed inline —
    it is a handful of aggregates and a billing pass, and the caller is
    waiting to see the result.

    `backfill_days` is a different shape of work: a year is 365 of those
    passes, thousands of queries in one transaction that a proxy timeout or a
    closed tab would roll back in full, with nothing written and no way to
    tell how far it got. It goes on the queue, where it already has a
    30-minute budget and a retry policy, and the response says so.
    """
    from aexy.services.platform_stats_service import PlatformStatsService
    from aexy.temporal.activities.platform import SnapshotPlatformStatsInput
    from aexy.temporal.dispatch import dispatch
    from aexy.temporal.task_queues import TaskQueue

    queued = False
    if backfill_days:
        try:
            await dispatch(
                "snapshot_platform_stats",
                SnapshotPlatformStatsInput(backfill_days=backfill_days),
                task_queue=TaskQueue.ANALYSIS,
            )
            queued = True
        except Exception:
            # Temporal being unreachable should not cost the admin today's
            # snapshot, which is the part they were waiting for.
            logger.exception("Could not queue a platform stats backfill")

    service = PlatformStatsService(db)
    result = await service.compute_day()
    await db.commit()
    return PlatformSnapshotRefreshResponse(
        day=result.day,
        created=result.created,
        backfill_queued=queued,
        backfill_days=backfill_days if queued else 0,
        notes=result.notes,
    )


@router.get("/stats/adoption", response_model=ModuleAdoptionResponse)
async def admin_stats_adoption(
    days: int = Query(90, ge=7, le=365),
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ModuleAdoptionResponse:
    """Which modules are actually being used, day by day.

    The number that matters is a share: 3 of 40 workspaces touching the CRM
    means something different from 3 of 4, so the active workspace count comes
    back with it.
    """
    from aexy.services.platform_stats_service import (
        ACTIVITY_WINDOW_DAYS,
        MODULES_WITHOUT_SIGNAL,
        PlatformStatsService,
    )

    service = PlatformStatsService(db)
    rows = await service.module_adoption(days)

    # The denominator has to mean the same thing as the numerator. Each row
    # counts workspaces that did that module's work inside the trailing
    # window, so the share is against workspaces that did *anything* in that
    # window — not against every workspace that exists and has not been
    # switched off. Dividing by the second understated every module: three of
    # forty when thirty of them had been dormant for months reads as 8%
    # adoption where the honest figure is 30%.
    total = int(
        await db.scalar(
            select(func.count(Workspace.id)).where(Workspace.is_active.is_(True))
        )
        or 0
    )
    latest = await service.latest()
    # No snapshot yet, or a genuinely silent window: fall back to the live
    # count so the page shows a share rather than dividing by zero.
    active = (latest.workspaces_active_30d if latest is not None else 0) or total

    return ModuleAdoptionResponse(
        days=days,
        window_days=ACTIVITY_WINDOW_DAYS,
        active_workspaces=active,
        total_workspaces=total,
        points=[
            {
                "day": row.day,
                "module": row.module,
                "workspaces_active": row.workspaces_active,
                "events": row.events,
                "window_days": row.window_days,
            }
            for row in rows
        ],
        not_measured=list(MODULES_WITHOUT_SIGNAL),
    )


@router.get("/stats/ai-spend", response_model=AiSpendResponse)
async def admin_stats_ai_spend(
    days: int = Query(30, ge=7, le=365),
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> AiSpendResponse:
    """Where the AI money went: by day and provider, by workspace, by feature.

    Read live rather than from the snapshot — it is one window and three
    GROUP BYs, and a stale answer to "who is burning the budget right now"
    would be worse than a slightly slower one.
    """
    from aexy.services.platform_stats_service import ai_spend

    return AiSpendResponse.model_validate(await ai_spend(db, days))


@router.get("/stats/alerts", response_model=PlatformAlertsResponse)
async def admin_stats_alerts(
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> PlatformAlertsResponse:
    """What a platform admin should look at today. Usually nothing."""
    from aexy.services.platform_stats_service import platform_alerts

    return PlatformAlertsResponse(alerts=await platform_alerts(db))


@router.get(
    "/workspaces/{workspace_id}/detail", response_model=WorkspaceDetailResponse
)
async def admin_workspace_detail(
    workspace_id: str,
    admin: Developer = Depends(get_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> WorkspaceDetailResponse:
    """One customer, in one place: plan, subscription, seats, AI spend and the
    modules they actually use. Answering that meant three pages and a guess."""
    from aexy.services.platform_stats_service import workspace_detail

    detail = await workspace_detail(db, workspace_id)
    if detail is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workspace not found"
        )
    return WorkspaceDetailResponse.model_validate(detail)

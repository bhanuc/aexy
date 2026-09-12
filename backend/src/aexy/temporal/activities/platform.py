"""Temporal activities for platform-level signup handling."""

import logging
from dataclasses import dataclass
from typing import Any

from temporalio import activity

from aexy.core.database import async_session_maker

logger = logging.getLogger(__name__)


@dataclass
class HandleNewSignupInput:
    developer_id: str
    email: str
    name: str | None
    avatar_url: str | None
    signup_provider: str  # "github" or "google"


@activity.defn
async def handle_new_signup(input: HandleNewSignupInput) -> dict[str, Any]:
    """Create CRM contact and start onboarding flow for a new signup."""
    logger.info(f"Handling new signup for {input.email} (provider={input.signup_provider})")

    from aexy.services.platform_service import PlatformService

    async with async_session_maker() as db:
        service = PlatformService(db)

        # Safety net — ensure setup ran (idempotent)
        await service.ensure_platform_setup()

        contact = await service.create_signup_contact(
            developer_id=input.developer_id,
            email=input.email,
            name=input.name,
            avatar_url=input.avatar_url,
            signup_provider=input.signup_provider,
        )

        onboarding = await service.start_signup_onboarding(input.developer_id)

        await db.commit()

    return {
        "status": "success",
        "contact_id": contact.id if contact else None,
        "onboarding": onboarding,
    }


@dataclass
class SendFeedbackDigestInput:
    """Nothing to configure — the window is the schedule's own interval."""

    hours: int = 24


@activity.defn
async def send_feedback_digest(input: SendFeedbackDigestInput) -> dict[str, Any]:
    """Mail the platform admins what people told us since yesterday.

    In-app notices already fire per item; this is the safety net that does not
    depend on anybody logging in. It goes to the ADMIN_EMAILS addresses rather
    than to a hardcoded inbox, so the people who can act on it are the people
    who get it, and adding an admin does not mean editing this.

    Sends nothing when nothing arrived: a daily "no feedback today" is how a
    digest teaches people to filter it.
    """
    from datetime import datetime, timedelta, timezone

    from aexy.core.config import get_settings
    from aexy.services.email_service import EmailService
    from aexy.services.feedback_service import FeedbackService

    settings = get_settings()
    recipients = settings.admin_email_list
    if not recipients:
        logger.info("Feedback digest: ADMIN_EMAILS is empty, nothing to send")
        return {"sent": 0, "items": 0}

    since = datetime.now(timezone.utc) - timedelta(hours=input.hours)

    async with async_session_maker() as db:
        service = FeedbackService(db)
        new_items = await service.since(since)
        if not new_items:
            logger.info("Feedback digest: nothing new since %s", since.isoformat())
            return {"sent": 0, "items": 0}

        top = await service.top_open(limit=5)

        lines = [f"{len(new_items)} new since {since:%Y-%m-%d %H:%M} UTC", ""]
        for item in new_items:
            lines.append(f"[{item.kind}] {item.subject}  ({item.vote_count} votes)")
            body = (item.body or "").strip().splitlines()
            if body:
                lines.append(f"    {body[0][:160]}")
        lines += ["", "Most wanted, still open:"]
        for item in top:
            lines.append(f"  {item.vote_count:>3} — {item.subject}")
        lines += ["", f"{settings.frontend_url}/admin/feedback"]
        body_text = "\n".join(lines)

        sent = 0
        for recipient in recipients:
            try:
                await EmailService().send_templated_email(
                    db=db,
                    recipient_email=recipient,
                    subject=f"Aexy feedback: {len(new_items)} new",
                    body_text=body_text,
                    auto_generated=True,
                )
                sent += 1
            except Exception as exc:  # noqa: BLE001 — one bad address is not the batch
                logger.warning("Feedback digest to %s failed: %s", recipient, exc)

    return {"sent": sent, "items": len(new_items)}


@dataclass
class SnapshotPlatformStatsInput:
    #: Which day to describe. Defaults to today, which is the only day whose
    #: subscription, seat and revenue figures are knowable.
    day: str | None = None
    #: Fill in the days before this ran for the first time, as far as the
    #: source rows allow. Off by default: it is a one-off.
    backfill_days: int = 0


@activity.defn
async def snapshot_platform_stats(input: SnapshotPlatformStatsInput) -> dict[str, Any]:
    """Write today's row of `platform_daily_stats`.

    The admin area's platform figures were all live, and so could only ever
    describe this instant. This is what makes "is MRR growing?" and "how many
    workspaces cancelled last month?" answerable — the numbers are written
    down daily because they cannot be recovered afterwards.

    It also takes the cost off the request path: the revenue section is the
    per-workspace billing-breakdown loop that `/billing/totals` used to run on
    every page load.
    """
    from datetime import date, datetime, timedelta, timezone

    from aexy.services.platform_stats_service import PlatformStatsService

    day = date.fromisoformat(input.day) if input.day else None

    async with async_session_maker() as db:
        service = PlatformStatsService(db)
        filled = 0
        if input.backfill_days:
            filled = len(await service.backfill(input.backfill_days))

        # Finish yesterday before describing today. The schedule runs at 23:50
        # so that the day being written is essentially complete, but "23:50" is
        # not "midnight" and a worker that was down at 23:50 wrote nothing at
        # all. Coming back to yesterday picks up both: its dated figures —
        # signups, cancellations, AI spend — are recomputable in full, and a
        # day already written while it was current keeps the subscription and
        # revenue figures that cannot be recovered.
        if day is None:
            # UTC, like every other day boundary here — `date.today()`
            # would be the worker's local day.
            yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
            await service.compute_day(yesterday)

        result = await service.compute_day(day)
        await db.commit()
        logger.info(
            "Platform snapshot for %s (%s), %d day(s) backfilled",
            result.day,
            "created" if result.created else "updated",
            filled,
        )
        return {
            "day": result.day.isoformat(),
            "created": result.created,
            "backfilled": filled,
            "notes": result.notes,
        }

"""Alert ingestion: turn observability alerts into deduplicated tickets.

Pipeline (per delivered alert):

    normalize (provider adapter)
      -> compute fingerprint (the "single kind of error" key)
      -> evaluate routing rules (team / assignee / form / priority)
      -> dedup decision:
             open ticket with same fingerprint?  -> bump + (throttled) comment
             recently closed within window?       -> reopen
             recovery signal?                      -> resolve open ticket
             otherwise                             -> create a fully-populated ticket
      -> dispatch alert.ticket_created / alert.ticket_updated automations

The one-open-ticket-per-fingerprint invariant is backed by the partial unique
index ``uq_tickets_open_dedup`` (see migrate_alert_ticketing.sql); the create
path catches an IntegrityError from a concurrent delivery and falls back to
the update path.
"""

import fnmatch
import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import and_, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.integrations.alert_providers import AlertContext, get_adapter
from aexy.models.alerting import AlertEvent, AlertEventAction, AlertIntegration
from aexy.models.ticketing import (
    Ticket,
    TicketForm,
    TicketPriority,
    TicketResponse as TicketResponseModel,
    TicketSeverity,
    TicketStatus,
)
from aexy.services.automation_service import dispatch_automation_event

logger = logging.getLogger(__name__)

# Ordering used for severity escalation comparisons.
_SEVERITY_ORDER = {
    TicketSeverity.LOW.value: 0,
    TicketSeverity.MEDIUM.value: 1,
    TicketSeverity.HIGH.value: 2,
    TicketSeverity.CRITICAL.value: 3,
}

# Volatile tokens stripped when normalizing an alert name into a stable
# fingerprint. This is what makes "OOM in worker-7f9c" and "OOM in worker-2b1a"
# collapse to one fingerprint while keeping meaningful tokens like "5xx" or
# "sev2" distinct (see _normalize_name).
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_ISO_RE = re.compile(r"\d{4}-\d{2}-\d{2}[t\s]\d{2}:\d{2}:\d{2}\S*")
_TOKEN_SPLIT_RE = re.compile(r"[^a-z0-9]+")


class AlertIngestionService:
    """Routes and deduplicates alerts into tickets."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self._dispatch_automations = True

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------
    async def process_event(
        self, event: AlertEvent, *, dispatch_automations: bool = True
    ) -> AlertEvent:
        """Process a persisted :class:`AlertEvent`. Idempotent per event id.

        ``dispatch_automations=False`` runs the full routing/dedup/ticket
        pipeline but skips firing ``alert.ticket_*`` automations — used by the
        "send test alert" endpoint so verifying setup can't page on-call or
        trigger escalation side effects.
        """
        self._dispatch_automations = dispatch_automations
        integration = await self.db.get(AlertIntegration, event.integration_id)
        if integration is None or not integration.enabled:
            return await self._finish(event, AlertEventAction.DROPPED, error="integration missing or disabled")

        try:
            adapter = get_adapter(integration.provider)
            ctx = adapter.normalize(event.raw_payload)
        except ValueError as exc:
            return await self._finish(event, AlertEventAction.DROPPED, error=f"unparseable payload: {exc}")

        fingerprint = self._fingerprint(integration, ctx)
        event.fingerprint = fingerprint

        if ctx.is_recovery:
            return await self._handle_recovery(event, integration, ctx, fingerprint)

        existing = await self._find_open_ticket(integration.workspace_id, fingerprint)
        if existing is not None:
            return await self._bump_ticket(event, integration, ctx, existing)

        reopened = await self._maybe_reopen(integration, ctx, fingerprint)
        if reopened is not None:
            return await self._after_reopen(event, integration, ctx, reopened)

        return await self._create_ticket(event, integration, ctx, fingerprint)

    # ------------------------------------------------------------------
    # Fingerprinting
    # ------------------------------------------------------------------
    def _fingerprint(self, integration: AlertIntegration, ctx: AlertContext) -> str:
        template = integration.fingerprint_template
        if template:
            raw = template.format(
                provider=ctx.provider,
                service=ctx.service,
                alert_name=ctx.alert_name,
                environment=ctx.environment or "",
                severity=ctx.severity.value,
            )
        else:
            raw = f"{ctx.provider}:{ctx.service}:{self._normalize_name(ctx.alert_name)}"
        return hashlib.sha256(raw.lower().encode("utf-8")).hexdigest()[:32]

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Strip volatile identifiers so recurrences of one error collapse.

        Drops UUIDs, ISO timestamps, pure numbers, and hex-like id tokens
        (git shas, container/pod suffixes such as ``worker-7f9c``). Keeps
        tokens whose letters aren't all hex — so ``5xx``, ``4xx``, ``sev2``,
        ``http2`` stay distinct and don't over-merge unrelated alerts.
        """
        text = name.lower()
        text = _UUID_RE.sub(" ", text)
        text = _ISO_RE.sub(" ", text)
        kept: list[str] = []
        for token in _TOKEN_SPLIT_RE.split(text):
            if not token:
                continue
            if any(ch.isdigit() for ch in token):
                alpha = [ch for ch in token if ch.isalpha()]
                if all(ch in "abcdef" for ch in alpha):
                    # pure number or hex-like id -> volatile, drop it
                    continue
            kept.append(token)
        return " ".join(kept)

    # ------------------------------------------------------------------
    # Routing rules
    # ------------------------------------------------------------------
    def _match_rule(self, integration: AlertIntegration, ctx: AlertContext) -> dict:
        """First matching routing rule wins; returns {} when none match."""
        for rule in integration.routing_rules or []:
            match = rule.get("match", {}) if isinstance(rule, dict) else {}
            service_glob = match.get("service")
            if service_glob and not fnmatch.fnmatch(ctx.service, service_glob):
                continue
            sev_gte = match.get("severity_gte")
            if sev_gte and _SEVERITY_ORDER.get(ctx.severity.value, 0) < _SEVERITY_ORDER.get(sev_gte, 0):
                continue
            env = match.get("environment")
            if env and (ctx.environment or "") != env:
                continue
            return rule
        return {}

    # ------------------------------------------------------------------
    # Dedup queries
    # ------------------------------------------------------------------
    async def _find_open_ticket(self, workspace_id: str, fingerprint: str) -> Ticket | None:
        stmt = (
            select(Ticket)
            .where(
                and_(
                    Ticket.workspace_id == workspace_id,
                    Ticket.dedup_key == fingerprint,
                    Ticket.status.notin_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]),
                )
            )
            .order_by(Ticket.created_at.desc())
            .limit(1)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _maybe_reopen(
        self, integration: AlertIntegration, ctx: AlertContext, fingerprint: str
    ) -> Ticket | None:
        """Reopen a ticket that closed recently — flapping protection."""
        window_start = datetime.now(timezone.utc) - timedelta(minutes=integration.dedup_window_minutes)
        stmt = (
            select(Ticket)
            .where(
                and_(
                    Ticket.workspace_id == integration.workspace_id,
                    Ticket.dedup_key == fingerprint,
                    Ticket.status.in_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value]),
                    Ticket.closed_at.isnot(None),
                    Ticket.closed_at >= window_start,
                )
            )
            .order_by(Ticket.closed_at.desc())
            .limit(1)
        )
        ticket = (await self.db.execute(stmt)).scalar_one_or_none()
        if ticket is None:
            return None

        # Reopening flips the ticket back inside the partial-unique-index
        # predicate (status leaves resolved/closed). If a concurrent delivery
        # already opened a fresh ticket for this fingerprint, this UPDATE
        # collides with uq_tickets_open_dedup. Scope it to a SAVEPOINT so the
        # violation rolls back only the reopen (not the whole session) and
        # return None — process_event then falls through to _create_ticket,
        # whose own IntegrityError fallback detects the winner and bumps it.
        try:
            async with self.db.begin_nested():
                ticket.status = TicketStatus.IN_PROGRESS.value
                ticket.closed_at = None
                ticket.resolved_at = None
                ticket.occurrence_count += 1
                ticket.last_seen_at = datetime.now(timezone.utc)
                self._raise_severity(ticket, ctx.severity)
                await self._add_comment(
                    ticket,
                    f"Alert recurred after being closed — reopening.\n\n{self._occurrence_line(ctx)}",
                    old_status=TicketStatus.CLOSED.value,
                    new_status=TicketStatus.IN_PROGRESS.value,
                )
                await self.db.flush()
        except IntegrityError:
            return None
        return ticket

    # ------------------------------------------------------------------
    # Create / bump / recovery
    # ------------------------------------------------------------------
    async def _create_ticket(
        self, event: AlertEvent, integration: AlertIntegration, ctx: AlertContext, fingerprint: str
    ) -> AlertEvent:
        rule = self._match_rule(integration, ctx)
        form_id = rule.get("form_id") or integration.default_form_id
        form_id = await self._resolve_form_id(integration.workspace_id, form_id)
        if form_id is None:
            return await self._finish(event, AlertEventAction.DROPPED, error="no ticket form available")

        priority = rule.get("priority") or self._default_priority(ctx.severity)
        ticket_number = await self._next_ticket_number(integration.workspace_id)

        ticket = Ticket(
            id=str(uuid4()),
            form_id=form_id,
            workspace_id=integration.workspace_id,
            ticket_number=ticket_number,
            status=TicketStatus.NEW.value,
            priority=priority,
            severity=ctx.severity.value,
            team_id=rule.get("team_id"),
            assignee_id=rule.get("assignee_id"),
            source=ctx.provider,
            dedup_key=fingerprint,
            occurrence_count=1,
            last_seen_at=ctx.started_at,
            field_values=self._build_field_values(integration, ctx, fingerprint),
        )
        try:
            # Wrap the insert in a SAVEPOINT so a unique-violation from a
            # concurrent delivery rolls back only this insert — not the whole
            # session. A full rollback would expire every loaded object
            # (integration, event) and the next attribute access would raise
            # MissingGreenlet under async SQLAlchemy. Postgres also aborts the
            # entire transaction on error unless it's scoped to a savepoint.
            async with self.db.begin_nested():
                self.db.add(ticket)
                await self.db.flush()
        except IntegrityError:
            # A concurrent delivery for the *same* fingerprint won the dedup
            # race (uq_tickets_open_dedup): fall back to bumping that ticket.
            existing = await self._find_open_ticket(integration.workspace_id, fingerprint)
            if existing is not None:
                return await self._bump_ticket(event, integration, ctx, existing)
            # No same-fingerprint ticket surfaced, so this wasn't the dedup
            # index — most likely a uq_ticket_number collision with a concurrent
            # delivery for a *different* alert (both computed the same max()+1).
            # Re-raise so the Temporal activity retries; on retry the winner is
            # committed and _next_ticket_number yields a fresh number. Swallowing
            # it here would silently drop a legitimately distinct alert.
            raise

        # A response clock, if this workspace has a policy that matches. Applied
        # after the insert rather than before, so a dedup loser that falls
        # through to `_bump_ticket` above does not pay for a policy lookup it
        # will not use.
        #
        # The alert path never did this: `_apply_sla` was called from exactly
        # one place, the form-submission create. So a critical production alert
        # had no `sla_due_at` and could never breach, while a password-reset
        # form submission did. Best-effort — a missing clock is worth less than
        # a lost alert.
        try:
            from aexy.services.ticket_service import TicketService

            await TicketService(self.db).apply_sla(ticket)
            await self.db.flush()
        except Exception as exc:  # noqa: BLE001 — the ticket matters, the clock does not
            logger.warning(
                "Alert ticket %s created without an SLA due date (%s)", ticket.id, exc
            )

        event.ticket_id = ticket.id
        result = await self._finish(event, AlertEventAction.CREATED)
        await self._dispatch(integration, ticket, "alert.ticket_created", ctx)
        return result

    async def _bump_ticket(
        self, event: AlertEvent, integration: AlertIntegration, ctx: AlertContext, ticket: Ticket
    ) -> AlertEvent:
        ticket.occurrence_count += 1
        ticket.last_seen_at = datetime.now(timezone.utc)
        severity_raised = self._raise_severity(ticket, ctx.severity)

        # Throttle comments so an alert storm doesn't flood the thread; still
        # bump counters/severity every time.
        throttled = await self._recently_commented(ticket, integration.comment_throttle_minutes)
        action = AlertEventAction.THROTTLED
        if not throttled or severity_raised:
            await self._add_comment(ticket, f"Recurrence.\n\n{self._occurrence_line(ctx)}")
            action = AlertEventAction.UPDATED
        await self.db.flush()

        event.ticket_id = ticket.id
        result = await self._finish(event, action)
        await self._dispatch(integration, ticket, "alert.ticket_updated", ctx)
        return result

    async def _after_reopen(
        self, event: AlertEvent, integration: AlertIntegration, ctx: AlertContext, ticket: Ticket
    ) -> AlertEvent:
        event.ticket_id = ticket.id
        result = await self._finish(event, AlertEventAction.REOPENED)
        await self._dispatch(integration, ticket, "alert.ticket_updated", ctx)
        return result

    async def _handle_recovery(
        self, event: AlertEvent, integration: AlertIntegration, ctx: AlertContext, fingerprint: str
    ) -> AlertEvent:
        ticket = await self._find_open_ticket(integration.workspace_id, fingerprint)
        if ticket is None:
            return await self._finish(event, AlertEventAction.DROPPED, error="recovery with no open ticket")

        if integration.auto_resolve:
            now = datetime.now(timezone.utc)
            await self._add_comment(
                ticket,
                "Recovery alert received — service healthy again. Auto-resolving.",
                old_status=ticket.status,
                new_status=TicketStatus.RESOLVED.value,
            )
            ticket.status = TicketStatus.RESOLVED.value
            ticket.resolved_at = now
            await self.db.flush()
            event.ticket_id = ticket.id
            result = await self._finish(event, AlertEventAction.RESOLVED)
            await self._dispatch(integration, ticket, "alert.ticket_updated", ctx)
            return result

        await self._add_comment(ticket, "Recovery alert received — service healthy again.")
        await self.db.flush()
        event.ticket_id = ticket.id
        return await self._finish(event, AlertEventAction.UPDATED)

    # ------------------------------------------------------------------
    # Field population
    # ------------------------------------------------------------------
    def _build_field_values(
        self, integration: AlertIntegration, ctx: AlertContext, fingerprint: str
    ) -> dict:
        log_context = "\n".join(ctx.log_lines) if ctx.log_lines else ""
        values: dict = {
            "title": f"[{ctx.severity.value.upper()}] {ctx.service}: {ctx.alert_name}",
            "service_name": ctx.service,
            "severity": ctx.severity.value,
            "alert_name": ctx.alert_name,
            "log_context": log_context,
            "trace_ids": ctx.trace_ids,
            "trace_links": self._trace_links(integration, ctx),
            "alert_url": ctx.alert_url,
            "first_seen": ctx.started_at.isoformat(),
            "occurrence_count": 1,
            "fingerprint": fingerprint,
        }
        if ctx.environment:
            values["environment"] = ctx.environment
        values.update({k: v for k, v in ctx.extra.items() if v is not None})
        return values

    def _trace_links(self, integration: AlertIntegration, ctx: AlertContext) -> list[str]:
        base = (integration.base_url or "").rstrip("/")
        if not base or not ctx.trace_ids:
            return []
        return [f"{base}/web/traces?trace_id={tid}" for tid in ctx.trace_ids]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _occurrence_line(self, ctx: AlertContext) -> str:
        parts = [f"**Severity:** {ctx.severity.value}"]
        if ctx.environment:
            parts.append(f"**Environment:** {ctx.environment}")
        if ctx.alert_url:
            parts.append(f"**Source:** {ctx.alert_url}")
        if ctx.log_lines:
            excerpt = "\n".join(ctx.log_lines[:10])
            parts.append(f"**Log excerpt:**\n```\n{excerpt}\n```")
        return "\n".join(parts)

    def _raise_severity(self, ticket: Ticket, severity: TicketSeverity) -> bool:
        current = _SEVERITY_ORDER.get(ticket.severity or "", -1)
        incoming = _SEVERITY_ORDER.get(severity.value, 0)
        if incoming > current:
            ticket.severity = severity.value
            return True
        return False

    @staticmethod
    def _default_priority(severity: TicketSeverity) -> str:
        return {
            TicketSeverity.CRITICAL: TicketPriority.URGENT.value,
            TicketSeverity.HIGH: TicketPriority.HIGH.value,
            TicketSeverity.MEDIUM: TicketPriority.MEDIUM.value,
            TicketSeverity.LOW: TicketPriority.LOW.value,
        }.get(severity, TicketPriority.MEDIUM.value)

    async def _add_comment(
        self, ticket: Ticket, content: str, old_status: str | None = None, new_status: str | None = None
    ) -> None:
        self.db.add(
            TicketResponseModel(
                id=str(uuid4()),
                ticket_id=ticket.id,
                is_internal=True,
                content=content,
                old_status=old_status,
                new_status=new_status,
            )
        )

    async def _recently_commented(self, ticket: Ticket, throttle_minutes: int) -> bool:
        if throttle_minutes <= 0:
            return False
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=throttle_minutes)
        stmt = (
            select(func.count())
            .select_from(TicketResponseModel)
            .where(
                and_(
                    TicketResponseModel.ticket_id == ticket.id,
                    TicketResponseModel.is_internal.is_(True),
                    TicketResponseModel.created_at >= cutoff,
                )
            )
        )
        return ((await self.db.execute(stmt)).scalar() or 0) > 0

    async def _resolve_form_id(self, workspace_id: str, form_id: str | None) -> str | None:
        """Resolve the form for an alert ticket.

        Preference order: the explicitly-configured form → a workspace form
        seeded from the ``incident_auto`` template (its fields match the
        populated ``field_values`` so they render as structured UI) → the
        first active form as a safety net.
        """
        if form_id:
            stmt = select(TicketForm.id).where(
                and_(TicketForm.id == form_id, TicketForm.workspace_id == workspace_id)
            )
            if (await self.db.execute(stmt)).scalar_one_or_none():
                return form_id

        incident_stmt = (
            select(TicketForm.id)
            .where(
                and_(
                    TicketForm.workspace_id == workspace_id,
                    TicketForm.is_active.is_(True),
                    TicketForm.template_type == "incident_auto",
                )
            )
            .order_by(TicketForm.created_at)
            .limit(1)
        )
        incident_form = (await self.db.execute(incident_stmt)).scalar_one_or_none()
        if incident_form:
            return incident_form

        # Last resort: whichever form is oldest. It keeps the alert rather than
        # dropping it, but the ticket lands on a form with no field for any of
        # `service_name`, `severity`, `alert_name`, `log_context` or
        # `trace_links` — so every piece of context this service writes renders
        # as nothing, and the integration reads as broken when it is only
        # unconfigured. Said out loud for exactly that reason: the symptom is
        # invisible and the fix is one form.
        stmt = (
            select(TicketForm.id)
            .where(and_(TicketForm.workspace_id == workspace_id, TicketForm.is_active.is_(True)))
            .order_by(TicketForm.created_at)
            .limit(1)
        )
        fallback = (await self.db.execute(stmt)).scalar_one_or_none()
        if fallback is not None:
            logger.warning(
                "Workspace %s has no active 'incident_auto' ticket form, so alert tickets "
                "are landing on form %s and their alert context will not render. Create one "
                "from the Automated Incident template.",
                workspace_id,
                fallback,
            )
        return fallback

    async def _next_ticket_number(self, workspace_id: str) -> int:
        stmt = select(func.max(Ticket.ticket_number)).where(Ticket.workspace_id == workspace_id)
        return ((await self.db.execute(stmt)).scalar() or 0) + 1

    async def _dispatch(
        self, integration: AlertIntegration, ticket: Ticket, trigger_type: str, ctx: AlertContext
    ) -> None:
        if not self._dispatch_automations:
            return
        await dispatch_automation_event(
            db=self.db,
            workspace_id=integration.workspace_id,
            module="tickets",
            trigger_type=trigger_type,
            entity_id=ticket.id,
            trigger_data={
                "ticket_id": ticket.id,
                "ticket_number": ticket.ticket_number,
                "status": ticket.status,
                "priority": ticket.priority,
                "severity": ticket.severity,
                "source": ticket.source,
                "service": ctx.service,
                "alert_name": ctx.alert_name,
                "occurrence_count": ticket.occurrence_count,
                "dedup_key": ticket.dedup_key,
                "field_values": ticket.field_values,
                "workspace_id": integration.workspace_id,
            },
        )

    async def _finish(
        self, event: AlertEvent, action: AlertEventAction, error: str | None = None
    ) -> AlertEvent:
        event.action_taken = action.value
        event.error_message = error
        event.processed_at = datetime.now(timezone.utc)
        if error:
            logger.info("Alert event %s -> %s (%s)", event.id, action.value, error)
        await self.db.flush()
        return event

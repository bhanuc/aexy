"""CRUD + secret management for alert integrations."""

import logging
import secrets
from uuid import uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.core.encryption import decrypt_credentials, encrypt_credentials
from aexy.models.alerting import AlertEvent, AlertIntegration
from aexy.schemas.alerting import AlertIntegrationCreate, AlertIntegrationUpdate

logger = logging.getLogger(__name__)

# The form template whose field keys mirror what `AlertIngestionService` writes
# into `field_values`, so an alert ticket renders as structured fields instead
# of an opaque JSONB blob. Defined in `ticket_form_service.FORM_TEMPLATES`.
_INCIDENT_TEMPLATE = "incident_auto"


class AlertIntegrationService:
    """Manage alert integrations and their inbound tokens/secrets."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, workspace_id: str, data: AlertIntegrationCreate) -> tuple[AlertIntegration, str]:
        """Create an integration. Returns (integration, plaintext_signing_secret)."""
        signing_secret = secrets.token_urlsafe(32)
        integration = AlertIntegration(
            id=str(uuid4()),
            workspace_id=workspace_id,
            provider=data.provider,
            name=data.name,
            inbound_token=secrets.token_urlsafe(24),
            signing_secret=encrypt_credentials({"secret": signing_secret}),
            base_url=data.base_url,
            default_form_id=data.default_form_id,
            routing_rules=[r.model_dump() for r in data.routing_rules],
            fingerprint_template=data.fingerprint_template,
            dedup_window_minutes=data.dedup_window_minutes,
            comment_throttle_minutes=data.comment_throttle_minutes,
            auto_resolve=data.auto_resolve,
        )
        self.db.add(integration)
        await self.db.flush()

        # Give the workspace somewhere for alert tickets to land, and a clock to
        # be measured against, unless it already has them.
        #
        # `_resolve_form_id` looks for an `incident_auto` form and otherwise
        # falls back to *the oldest active form of any kind* — so on a workspace
        # that never created one, alert tickets landed on whatever form happened
        # to be oldest. On the desk this was found on that was the Service Desk
        # form, which has no field for `service_name`, `severity`, `alert_name`,
        # `log_context` or `trace_links`, so every piece of context the
        # ingestion writes rendered as nothing at all.
        #
        # Provisioned here rather than left to the admin because nothing in the
        # UI tells them it is needed, and the symptom — a ticket that exists and
        # says nothing — reads as the integration being broken.
        await self._ensure_incident_form(workspace_id, integration)
        await self.db.flush()
        await self.db.refresh(integration)
        return integration, signing_secret

    async def _ensure_incident_form(
        self, workspace_id: str, integration: AlertIntegration
    ) -> None:
        """Point this integration at an Automated Incident form, creating one if needed.

        Idempotent: a second integration in the same workspace reuses the first
        one's form rather than creating a duplicate, because two forms with the
        same fields would split one queue in half.

        Best-effort. A workspace that cannot get a form still gets its
        integration — `_resolve_form_id` will fall back as before, and a missing
        form is a worse-rendered ticket, not a lost alert.
        """
        from aexy.models.ticketing import TicketForm
        from aexy.services.ticket_form_service import TicketFormService

        if integration.default_form_id:
            return

        existing = (
            await self.db.execute(
                select(TicketForm.id)
                .where(
                    TicketForm.workspace_id == workspace_id,
                    TicketForm.template_type == _INCIDENT_TEMPLATE,
                    TicketForm.is_active.is_(True),
                )
                .order_by(TicketForm.created_at)
                .limit(1)
            )
        ).scalar_one_or_none()

        if existing is None:
            try:
                form = await TicketFormService(self.db).create_form_from_template(
                    workspace_id,
                    # Forms record who made them and nobody clicked this one into
                    # existence; the workspace owner is the honest answer and the
                    # column is not nullable.
                    created_by_id=await self._workspace_owner_id(workspace_id),
                    template_type=_INCIDENT_TEMPLATE,
                )
            except Exception as exc:  # noqa: BLE001 — the integration matters more
                logger.warning(
                    "Could not provision an Automated Incident form for workspace %s (%s); "
                    "alert tickets will fall back to whichever form is oldest",
                    workspace_id,
                    exc,
                )
                return
            existing = form.id
            await self._ensure_incident_sla(workspace_id, existing)

        integration.default_form_id = existing

    async def _workspace_owner_id(self, workspace_id: str) -> str:
        from aexy.models.workspace import Workspace

        return str(
            (
                await self.db.execute(
                    select(Workspace.owner_id).where(Workspace.id == workspace_id)
                )
            ).scalar_one()
        )

    async def _ensure_incident_sla(self, workspace_id: str, form_id: str) -> None:
        """Seed a first-response policy for incidents, if the workspace has none.

        An `sla_due_at` is only ever set by a *matching* policy, so wiring the
        alert path to `apply_sla` does nothing on its own — a workspace with no
        incident policy would still show an empty SLA column and never breach.

        The targets below are a starting point, not a commitment: 30 minutes for
        critical, 2 hours for high, 8 hours for medium. They are ordinary rows an
        admin can edit or delete in Settings, and they are seeded once — this
        never overwrites a policy somebody has tuned.
        """
        from aexy.models.ticketing import SLAPolicy

        already = (
            await self.db.execute(
                select(SLAPolicy.id).where(
                    SLAPolicy.workspace_id == workspace_id,
                    SLAPolicy.conditions["form_ids"].astext.contains(form_id),
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            return

        for name, severity, minutes, order in (
            ("Incident — critical", "critical", 30, 10),
            ("Incident — high", "high", 120, 20),
            ("Incident — medium", "medium", 480, 30),
        ):
            self.db.add(
                SLAPolicy(
                    id=str(uuid4()),
                    workspace_id=workspace_id,
                    name=name,
                    description=(
                        "Seeded when the alert integration was connected. "
                        "Adjust or delete it — these targets are a starting point."
                    ),
                    conditions={"form_ids": [form_id], "severities": [severity]},
                    first_response_target_minutes=minutes,
                    # Most specific first: critical must win over high on a
                    # ticket that somehow matches both.
                    priority_order=order,
                )
            )

    async def list_integrations(self, workspace_id: str) -> list[AlertIntegration]:
        stmt = (
            select(AlertIntegration)
            .where(AlertIntegration.workspace_id == workspace_id)
            .order_by(AlertIntegration.created_at.desc())
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def get(self, workspace_id: str, integration_id: str) -> AlertIntegration | None:
        stmt = select(AlertIntegration).where(
            and_(AlertIntegration.id == integration_id, AlertIntegration.workspace_id == workspace_id)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def get_by_token(self, inbound_token: str) -> AlertIntegration | None:
        stmt = select(AlertIntegration).where(AlertIntegration.inbound_token == inbound_token)
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def update(self, integration: AlertIntegration, data: AlertIntegrationUpdate) -> AlertIntegration:
        payload = data.model_dump(exclude_unset=True)
        if "routing_rules" in payload and payload["routing_rules"] is not None:
            payload["routing_rules"] = [
                r.model_dump() if hasattr(r, "model_dump") else r for r in data.routing_rules
            ]
        for key, value in payload.items():
            setattr(integration, key, value)
        await self.db.flush()
        await self.db.refresh(integration)
        return integration

    async def rotate_secret(self, integration: AlertIntegration) -> str:
        signing_secret = secrets.token_urlsafe(32)
        integration.signing_secret = encrypt_credentials({"secret": signing_secret})
        await self.db.flush()
        return signing_secret

    async def delete(self, integration: AlertIntegration) -> None:
        await self.db.delete(integration)
        await self.db.flush()

    async def list_events(
        self,
        workspace_id: str,
        integration_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        actions: list[str] | None = None,
        fingerprint: str | None = None,
        unresolved_only: bool = False,
    ) -> tuple[list[dict], int]:
        """One page of alert history, newest first.

        ``integration_id`` is optional now: a history screen shows a workspace's
        whole alert traffic, and asking per integration meant one request per
        integration and no way to see them interleaved.

        Returns dicts rather than ORM rows because the useful view joins two
        things the row does not carry — the integration's name and the ticket's
        number. Resolving those here is one query; leaving them to the caller is
        N+1 or a second round trip per row.

        ``unresolved_only`` surfaces the states worth chasing: a ``dropped`` or
        ``error`` event, or one still sitting with no action at all.
        ``AlertEventAction.ERROR`` is never actually assigned — a failure raises
        and Temporal retries — so an event that never completed has a null
        action and a null ``processed_at``, and that is a real stuck state
        rather than a rendering edge case.
        """
        from aexy.models.ticketing import Ticket

        conditions = [AlertEvent.workspace_id == workspace_id]
        if integration_id:
            conditions.append(AlertEvent.integration_id == integration_id)
        if actions:
            conditions.append(AlertEvent.action_taken.in_(actions))
        if fingerprint:
            # Prefix match: the UI shows a truncated fingerprint, so "click this
            # to see every event that shares it" has to work from the prefix.
            conditions.append(AlertEvent.fingerprint.startswith(fingerprint))
        if unresolved_only:
            conditions.append(
                or_(
                    AlertEvent.action_taken.is_(None),
                    AlertEvent.action_taken.in_(["dropped", "error"]),
                )
            )

        base = select(AlertEvent).where(and_(*conditions))
        total = (
            await self.db.execute(select(func.count()).select_from(base.subquery()))
        ).scalar() or 0

        rows = (
            await self.db.execute(
                select(AlertEvent, AlertIntegration.name, Ticket.ticket_number)
                .join(
                    AlertIntegration,
                    AlertIntegration.id == AlertEvent.integration_id,
                )
                # Outer, because a deleted ticket nulls the FK rather than
                # removing the event — the history outlives the tickets.
                .outerjoin(Ticket, Ticket.id == AlertEvent.ticket_id)
                .where(and_(*conditions))
                .order_by(AlertEvent.received_at.desc(), AlertEvent.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()

        return [
            {
                "id": event.id,
                "integration_id": event.integration_id,
                "integration_name": name,
                "fingerprint": event.fingerprint,
                "ticket_id": event.ticket_id,
                "ticket_number": ticket_number,
                "action_taken": event.action_taken,
                "error_message": event.error_message,
                "received_at": event.received_at,
                "processed_at": event.processed_at,
                "raw_payload": event.raw_payload,
            }
            for event, name, ticket_number in rows
        ], total

    @staticmethod
    def signing_secret_plaintext(integration: AlertIntegration) -> str | None:
        """Decrypt and return the stored signing secret."""
        return decrypt_credentials(integration.signing_secret or {}).get("secret")

"""Bimaplan Service Desk intake — turn an inbound email into a tracked ticket.

One entry point (``ingest``) is shared by both channels (provider inbound-parse
webhook and Gmail sync). It threads replies onto existing tickets, otherwise
runs domain-based auto-assignment (partner → insurer → internal → random KAM
fallback), creates the ``Ticket`` + ``ServiceDeskTicket`` + opens the first
``TicketPendingSegment``, then best-effort AI-classifies and sends the receipt.

See ``prds/BIMAPLAN_SERVICE_DESK_PLAN.md`` §5.
"""

import json
import logging
import re
import secrets
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.organization import Department, DepartmentMember
from aexy.models.service_desk import (
    MailboxChannel,
    PendingWith,
    RequestType,
    ServiceDeskIngestedMessage,
    ServiceDeskInsurer,
    ServiceDeskInsurerDomain,
    ServiceDeskLOB,
    ServiceDeskMailbox,
    ServiceDeskPartner,
    ServiceDeskPartnerDomain,
    ServiceDeskTicket,
    TicketOrigin,
    TicketPendingSegment,
)
from aexy.models.ticketing import Ticket, TicketForm, TicketResponse, TicketStatus
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import InboundEmail
from aexy.services.service_desk_mailer import OUTBOUND_MARKER_HEADER

logger = logging.getLogger(__name__)

SERVICE_DESK_FORM_SLUG = "service-desk"
TICKET_PREFIX = "BSD"
_BSD_RE = re.compile(rf"{TICKET_PREFIX}-(\d+)", re.IGNORECASE)
_TICKET_NUMBER_ATTEMPTS = 5
_MAX_ISSUES_PER_EMAIL = 5
# An email may only be auto-split into two tickets, and only when the model is
# this sure about both halves. Anything less certain stays one triage ticket —
# a human merging two tickets costs more than a human splitting one.
_SPLIT_MIN_CONFIDENCE = 0.85

# Headers that mean "a machine sent this". The X-Auto* ones only ever appear on
# auto-responders, so their presence is enough; Precedence needs a value check
# because ordinary mail carries it too.
_AUTO_RESPONSE_MARKER_HEADERS = ("x-autoreply", "x-autorespond")
_AUTO_RESPONSE_PRECEDENCE = {"auto_reply", "auto-reply", "bulk", "junk", "list"}
_AUTO_RESPONSE_SUBJECT_RE = re.compile(
    r"out of (the )?office|auto[\s-]?repl(y|ied)|automatic repl(y|ied)|"
    r"on (annual )?leave|vacation repl(y|ied)|away from (my |the )?(desk|office)",
    re.IGNORECASE,
)


def _domain_of(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None
    return email.rsplit("@", 1)[-1].strip().lower().rstrip(">")


def _address_of(email: str | None) -> str | None:
    """The bare sender address, lower-cased, display name and brackets stripped.

    Partner/insurer records may be keyed on a whole address as well as a domain,
    so several distinct companies can be tested from one real mailbox using
    plus-suffixes (`me+abcfinance@gmail.com`). A shared-domain provider like
    gmail.com cannot otherwise represent more than one company.
    """
    if not email or "@" not in email:
        return None
    addr = email.strip()
    if "<" in addr and ">" in addr:
        addr = addr[addr.rindex("<") + 1 : addr.rindex(">")]
    return addr.strip().lower()


async def ai_classification_enabled(db: AsyncSession, workspace_id: str) -> bool:
    """Whether this workspace has opted in to AI reading of its mail.

    Off by default, and the single gate for every AI-dependent behaviour in the
    desk: classification, LOB/request-type inference and auto-split. Module
    level because the Gmail sync must consult it too — attachment bytes are
    fetched only to feed the classifier, so with AI off no file is ever read.
    """
    ws = await db.get(Workspace, workspace_id)
    if ws is None:
        return False
    return bool(((ws.settings or {}).get("service_desk") or {}).get("ai_classification_enabled", False))


def is_aexy_generated(email: InboundEmail) -> bool:
    """True for mail this application sent (see ``OUTBOUND_MARKER_HEADER``)."""
    return bool((email.headers or {}).get(OUTBOUND_MARKER_HEADER.lower(), "").strip())


def is_automatic_response(email: InboundEmail) -> bool:
    """True for out-of-office replies, auto-responders and bulk machine mail.

    These carry no request: acknowledging them invites a reply loop, splitting
    them invents work, and reopening a closed ticket from one hides a closure
    the requester never disputed.
    """
    headers = email.headers or {}
    # RFC 3834: ordinary mail says "no"; every other value (often with
    # parameters, e.g. "auto-replied; owner-email=...") means automatic.
    auto_submitted = headers.get("auto-submitted", "").strip().lower()
    if auto_submitted and not auto_submitted.startswith("no"):
        return True
    if any(headers.get(name, "").strip() for name in _AUTO_RESPONSE_MARKER_HEADERS):
        return True
    if headers.get("precedence", "").strip().lower() in _AUTO_RESPONSE_PRECEDENCE:
        return True
    return bool(_AUTO_RESPONSE_SUBJECT_RE.search(email.subject or ""))


class ServiceDeskIntakeService:
    """Intake for one inbound message.

    Outbound acknowledgements are NOT sent inline: they are queued and sent by
    ``flush_notifications()``, which callers invoke *after* committing. Sending
    inline meant a requester could be acknowledged for a ticket whose
    transaction then rolled back.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._pending_notifications: list[dict] = []

    # ------------------------------------------------------------------ public

    async def ingest(
        self,
        email: InboundEmail,
        mailbox: ServiceDeskMailbox,
        source: str,
    ) -> Ticket | None:
        """Ingest one inbound email for a service-desk mailbox.

        Returns the created or updated ticket, or None if it was a duplicate.
        """
        workspace_id = mailbox.workspace_id

        # 0) Never ingest our own outbound. Checked before the message id is even
        #    claimed, so a receipt we sent leaves no trace on the way back in.
        if is_aexy_generated(email):
            logger.info("Service desk: skipped self-generated message %s", email.message_id)
            return None

        automatic = is_automatic_response(email)

        # 1) Idempotency — claim this message id first. The unique constraint on
        #    (workspace_id, message_id) is what actually makes this safe: two
        #    concurrent deliveries of the same message both pass a bare SELECT.
        #    Covers replies too, not just the first message of a thread.
        if email.message_id and not await self._claim_message(workspace_id, email.message_id):
            logger.info("Service desk: duplicate message %s ignored", email.message_id)
            return None

        # 2) Threading — append to an existing ticket if this is a reply
        existing = await self._find_thread_ticket(workspace_id, email)
        if existing is not None:
            await self._append_reply(workspace_id, existing, email, automatic=automatic)
            await self._link_message(workspace_id, email.message_id, existing.id)
            return existing

        # 3) New ticket
        ticket = await self._create_ticket(workspace_id, email, mailbox, source, automatic=automatic)
        await self._link_message(workspace_id, email.message_id, ticket.id)
        return ticket

    # --------------------------------------------------------------- idempotency

    async def _claim_message(self, workspace_id: str, message_id: str) -> bool:
        """Record a message id as processed. False if it was already claimed."""
        try:
            async with self.db.begin_nested():
                self.db.add(
                    ServiceDeskIngestedMessage(
                        id=str(uuid4()), workspace_id=workspace_id, message_id=message_id
                    )
                )
            return True
        except IntegrityError:
            return False

    async def _link_message(self, workspace_id: str, message_id: str | None, ticket_id: str) -> None:
        """Attach the claimed message row to the ticket it produced."""
        if not message_id:
            return
        row = (
            await self.db.execute(
                select(ServiceDeskIngestedMessage).where(
                    ServiceDeskIngestedMessage.workspace_id == workspace_id,
                    ServiceDeskIngestedMessage.message_id == message_id,
                )
            )
        ).scalar_one_or_none()
        if row is not None:
            row.ticket_id = ticket_id
            await self.db.flush()

    # --------------------------------------------------------------- threading

    async def _find_thread_ticket(self, workspace_id: str, email: InboundEmail) -> Ticket | None:
        thread_ref = email.thread_id or email.in_reply_to
        if thread_ref:
            sdt = (
                await self.db.execute(
                    select(ServiceDeskTicket).where(
                        ServiceDeskTicket.workspace_id == workspace_id,
                        ServiceDeskTicket.thread_ref == thread_ref,
                    )
                )
            ).scalar_one_or_none()
            if sdt is not None:
                return await self.db.get(Ticket, sdt.ticket_id)

        # subject carries BSD-<n>?
        #
        # ticket_number is shared with the GENERIC ticketing module, so this must
        # join service_desk_tickets. Matching on the number alone let anyone who
        # emailed the desk with "Re: BSD-7" post a public reply onto generic
        # ticket #7 (an HR helpdesk ticket, say) — and swallow their mail, since
        # no service desk ticket was created for it.
        m = _BSD_RE.search(email.subject or "")
        if m:
            number = int(m.group(1))
            return (
                await self.db.execute(
                    select(Ticket)
                    .join(ServiceDeskTicket, ServiceDeskTicket.ticket_id == Ticket.id)
                    .where(
                        Ticket.workspace_id == workspace_id,
                        Ticket.ticket_number == number,
                        ServiceDeskTicket.workspace_id == workspace_id,
                    )
                )
            ).scalar_one_or_none()
        return None

    async def _append_reply(
        self, workspace_id: str, ticket: Ticket, email: InboundEmail, automatic: bool = False
    ) -> None:
        response = TicketResponse(
            id=str(uuid4()),
            ticket_id=ticket.id,
            author_email=email.from_email,
            content=email.body_text or "",
            is_internal=False,
        )
        self.db.add(response)
        await self.db.flush()

        # A reply to a closed ticket must reopen it — otherwise the requester's
        # message lands silently: no stakeholder clock restarts and nobody is
        # notified, while the requester believes the thread is live again.
        # An out-of-office bounce is not the requester disputing the closure, so
        # it is kept as correspondence and the ticket stays closed.
        if automatic:
            return
        sd = (
            await self.db.execute(
                select(ServiceDeskTicket).where(
                    ServiceDeskTicket.ticket_id == ticket.id,
                    ServiceDeskTicket.workspace_id == workspace_id,
                )
            )
        ).scalar_one_or_none()
        if sd is not None and sd.pending_with == PendingWith.CLOSED.value:
            from aexy.services.service_desk_ticket_service import ServiceDeskTicketService

            await ServiceDeskTicketService(self.db).change_pending_with(
                workspace_id,
                ticket.id,
                PendingWith.KAM.value,
                note="Reopened by requester reply",
            )

    # ------------------------------------------------------------- new ticket

    async def _create_ticket(
        self,
        workspace_id: str,
        email: InboundEmail,
        mailbox: ServiceDeskMailbox | None,
        source: str,
        automatic: bool = False,
    ) -> Ticket:
        domain = _domain_of(email.from_email)
        address = _address_of(email.from_email)
        internal_domain = _domain_of(mailbox.address) if mailbox else None

        partner: ServiceDeskPartner | None = None
        insurer: ServiceDeskInsurer | None = None
        origin = TicketOrigin.EMAIL.value
        needs_triage = False
        assigned_kam_id: str | None = None

        if domain and internal_domain and domain == internal_domain:
            # Internal sender (@bimaplan.co) — partner must be confirmed by KAM
            origin = TicketOrigin.INTERNAL.value
            needs_triage = True
            assigned_kam_id = await self._random_kam(workspace_id)
        else:
            partner = await self._match_partner(workspace_id, domain, address)
            if partner is not None:
                assigned_kam_id = partner.assigned_kam_id or await self._random_kam(workspace_id)
            else:
                insurer = await self._match_insurer(workspace_id, domain, address)
                # insurer-originated or wholly unknown → triage + random KAM
                needs_triage = True
                assigned_kam_id = await self._random_kam(workspace_id)

        form_id = await self._ensure_form(workspace_id)

        ticket = await self._insert_ticket(
            workspace_id,
            form_id=form_id,
            submitter_email=email.from_email,
            submitter_name=email.from_name,
            email_verified=False,
            field_values={
                "subject": email.subject,
                "body": email.body_text,
                "partner": partner.name if partner else None,
                "insurer": insurer.name if insurer else None,
                "attachments": [
                    attachment.model_dump() for attachment in email.attachments
                ],
            },
            status=TicketStatus.NEW.value,
            assignee_id=assigned_kam_id,
            source=source,
        )
        await self.db.flush()

        sd = ServiceDeskTicket(
            id=str(uuid4()),
            ticket_id=ticket.id,
            workspace_id=workspace_id,
            partner_id=partner.id if partner else None,
            insurer_id=insurer.id if insurer else None,
            request_type=RequestType.QUERY.value,
            pending_with=PendingWith.KAM.value,
            origin=origin,
            needs_triage=needs_triage,
            mailbox_id=mailbox.id if mailbox is not None else None,
            thread_ref=email.thread_id or email.message_id,
            source_message_id=email.message_id,
        )
        self.db.add(sd)

        # open the first pending-with segment (the ledger starts here)
        self.db.add(
            TicketPendingSegment(
                id=str(uuid4()),
                workspace_id=workspace_id,
                ticket_id=ticket.id,
                pending_with=PendingWith.KAM.value,
                entered_at=datetime.now(timezone.utc),
                changed_by_id=assigned_kam_id,
                note="Ticket created",
            )
        )
        await self.db.flush()

        # best-effort enrichment + receipt (never block intake).
        # AI reading/categorisation is opt-in per workspace (default off), and an
        # automatic response carries no request to read — classifying one would
        # only invent a request type and an LOB for a machine's away message.
        issues: list[dict] = []
        overflow = False
        if automatic:
            sd.needs_triage = True
        elif await self._ai_enabled(workspace_id):
            issues, overflow = await self._classify(workspace_id, sd, email)
        else:
            # No AI: the ticket is still created, owned and clocked, but nobody
            # has set the LOB or confirmed the request type — it holds the
            # placeholder "query". Flag it so the owning KAM completes those
            # fields by hand rather than the desk silently reporting every
            # ticket as a Query with no product against it.
            sd.needs_triage = True

        children: list[Ticket] = []
        if len(issues) > 1 and not overflow:
            children = await self._auto_split(workspace_id, ticket, sd, email, issues, mailbox)
        if (len(issues) > 1 or overflow) and not children:
            # Everything we did not split cleanly stays one ticket for a human.
            sd.needs_triage = True
        await self.db.flush()

        # One acknowledgement per inbound message, listing every ticket it
        # produced. Children never send their own — the requester wrote once.
        if not automatic:
            await self._send_receipt(
                workspace_id, ticket, mailbox, thread_id=email.thread_id, children=children
            )

        logger.info("Service desk: created ticket %s-%s", TICKET_PREFIX, ticket.ticket_number)
        return ticket

    async def _insert_ticket(self, workspace_id: str, **fields) -> Ticket:
        """Add a ``Ticket``, retrying its number against concurrent intake.

        ticket_number is max()+1 against a real uq_ticket_number constraint, so
        two emails arriving together collide. Retry inside a savepoint instead of
        letting the IntegrityError escape — in the webhook path it was swallowed
        by the caller and the email was dropped.
        """
        for attempt in range(_TICKET_NUMBER_ATTEMPTS):
            candidate = Ticket(
                id=str(uuid4()),
                workspace_id=workspace_id,
                ticket_number=await self._next_ticket_number(workspace_id),
                **fields,
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(candidate)
                return candidate
            except IntegrityError:
                # The savepoint rollback already detached `candidate`; do not try
                # to expunge it (that raises "not present in this Session").
                if attempt == _TICKET_NUMBER_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable: the loop returns or re-raises")

    # ----------------------------------------------------------- auto-split

    @staticmethod
    def _is_splittable(issues: list[dict]) -> bool:
        """The whole auto-split contract, in one place.

        Exactly two candidates, materially different request types, and the
        model sure about both. Three candidates, a repeated request type or one
        shaky confidence all mean the email is ambiguous, and an ambiguous email
        becomes one ticket a human triages — never three tickets.
        """
        return (
            len(issues) == 2
            and issues[0]["request_type"] != issues[1]["request_type"]
            and all(issue["confidence"] >= _SPLIT_MIN_CONFIDENCE for issue in issues)
        )

    async def _auto_split(
        self,
        workspace_id: str,
        primary: Ticket,
        sd: ServiceDeskTicket,
        email: InboundEmail,
        issues: list[dict],
        mailbox: ServiceDeskMailbox | None,
    ) -> list[Ticket]:
        """Create the second ticket for ``issues[1]``. Returns [] if not split.

        The child is created inside a savepoint: if anything about it fails, the
        savepoint rolls back and the caller is left with exactly one intact
        primary ticket flagged for triage, never a half-created pair.
        """
        if not self._is_splittable(issues):
            return []
        if not await self._auto_split_enabled(workspace_id):
            return []

        try:
            async with self.db.begin_nested():
                child = await self._create_child_ticket(
                    workspace_id, primary, sd, email, issues[1], mailbox
                )
                child_number = child.ticket_number
        except Exception as exc:  # noqa: BLE001 — an unsplit email is still a ticket
            logger.warning("Service desk: auto-split rolled back (%s)", exc)
            return []

        primary_values = dict(primary.field_values or {})
        primary_values["split_children"] = [
            {"ticket_id": child.id, "display_id": f"{TICKET_PREFIX}-{child_number}"}
        ]
        primary.field_values = primary_values
        await self.db.flush()
        logger.info(
            "Service desk: auto-split %s-%s into child %s-%s",
            TICKET_PREFIX, primary.ticket_number, TICKET_PREFIX, child_number,
        )
        return [child]

    async def _create_child_ticket(
        self,
        workspace_id: str,
        primary: Ticket,
        sd: ServiceDeskTicket,
        email: InboundEmail,
        issue: dict,
        mailbox: ServiceDeskMailbox | None,
    ) -> Ticket:
        """The second request from one email, as its own tracked ticket."""
        primary_values = primary.field_values or {}
        child = await self._insert_ticket(
            workspace_id,
            form_id=primary.form_id,
            submitter_email=primary.submitter_email,
            submitter_name=primary.submitter_name,
            email_verified=False,
            field_values={
                "subject": issue["summary"],
                "body": primary_values.get("body"),
                "partner": primary_values.get("partner"),
                "insurer": primary_values.get("insurer"),
                "attachments": primary_values.get("attachments") or [],
                "email_subject": primary_values.get("subject"),
                "split_from_ticket_id": primary.id,
            },
            status=TicketStatus.NEW.value,
            # Same KAM as the primary: one email, one owner, and the child lands
            # in exactly the queue the requester's own ticket landed in.
            assignee_id=primary.assignee_id,
            source=primary.source,
        )
        await self.db.flush()

        self.db.add(
            ServiceDeskTicket(
                id=str(uuid4()),
                ticket_id=child.id,
                workspace_id=workspace_id,
                split_parent_ticket_id=primary.id,
                partner_id=sd.partner_id,
                insurer_id=sd.insurer_id,
                lob_id=await self._lob_id(workspace_id, issue.get("lob")),
                request_type=issue["request_type"],
                pending_with=PendingWith.KAM.value,
                origin=sd.origin,
                needs_triage=sd.needs_triage,
                ai_confidence=issue["confidence"],
                mailbox_id=mailbox.id if mailbox is not None else None,
                # No thread_ref: replies must thread onto the primary, and two
                # rows sharing one thread_ref would break that lookup outright.
                thread_ref=None,
                source_message_id=email.message_id,
            )
        )
        self.db.add(
            TicketPendingSegment(
                id=str(uuid4()),
                workspace_id=workspace_id,
                ticket_id=child.id,
                pending_with=PendingWith.KAM.value,
                entered_at=datetime.now(timezone.utc),
                changed_by_id=child.assignee_id,
                note="Created by auto-split",
            )
        )
        await self.db.flush()
        return child

    async def _lob_id(self, workspace_id: str, name: str | None) -> str | None:
        if not name:
            return None
        return (
            await self.db.execute(
                select(ServiceDeskLOB.id).where(
                    ServiceDeskLOB.workspace_id == workspace_id,
                    func.lower(ServiceDeskLOB.name) == name.strip().lower(),
                    ServiceDeskLOB.is_active.is_(True),
                )
            )
        ).scalars().first()

    # ------------------------------------------------------------- assignment

    async def _match_partner(
        self, workspace_id: str, domain: str | None, address: str | None = None
    ) -> ServiceDeskPartner | None:
        keys = [k for k in (address, domain) if k]
        if not keys:
            return None
        row = (
            await self.db.execute(
                select(ServiceDeskPartner)
                .join(ServiceDeskPartnerDomain, ServiceDeskPartnerDomain.partner_id == ServiceDeskPartner.id)
                .where(
                    ServiceDeskPartner.workspace_id == workspace_id,
                    ServiceDeskPartner.is_active.is_(True),
                    func.lower(ServiceDeskPartnerDomain.domain).in_(keys),
                )
                # A whole-address record is more specific than a domain record and
                # must win, otherwise one gmail.com partner would swallow every
                # plus-suffixed company keyed on the same domain.
                .order_by(
                    (func.lower(ServiceDeskPartnerDomain.domain) == (address or "")).desc(),
                    ServiceDeskPartner.created_at,
                    ServiceDeskPartner.id,
                )
            )
        ).scalars().first()
        return row

    async def _match_insurer(
        self, workspace_id: str, domain: str | None, address: str | None = None
    ) -> ServiceDeskInsurer | None:
        keys = [k for k in (address, domain) if k]
        if not keys:
            return None
        row = (
            await self.db.execute(
                select(ServiceDeskInsurer)
                .join(ServiceDeskInsurerDomain, ServiceDeskInsurerDomain.insurer_id == ServiceDeskInsurer.id)
                .where(
                    ServiceDeskInsurer.workspace_id == workspace_id,
                    ServiceDeskInsurer.is_active.is_(True),
                    func.lower(ServiceDeskInsurerDomain.domain).in_(keys),
                )
                .order_by(
                    (func.lower(ServiceDeskInsurerDomain.domain) == (address or "")).desc(),
                    ServiceDeskInsurer.created_at,
                    ServiceDeskInsurer.id,
                )
            )
        ).scalars().first()
        return row

    async def _random_kam(self, workspace_id: str) -> str | None:
        """Pick a random Ops/KAM department member who is still on the team.

        Department membership alone isn't enough: rows are not removed when
        someone leaves the workspace, so joining WorkspaceMember keeps tickets
        from being auto-assigned to a departed employee's dead queue.
        """
        rows = (
            await self.db.execute(
                select(DepartmentMember.developer_id)
                .join(Department, Department.id == DepartmentMember.department_id)
                .join(
                    WorkspaceMember,
                    (WorkspaceMember.developer_id == DepartmentMember.developer_id)
                    & (WorkspaceMember.workspace_id == workspace_id),
                )
                .where(
                    Department.workspace_id == workspace_id,
                    Department.function_key == "ops_kam",
                    Department.is_active.is_(True),
                    WorkspaceMember.status == "active",
                )
                .distinct()
            )
        ).scalars().all()
        if not rows:
            return None
        return secrets.choice(list(rows))

    # ------------------------------------------------------------- form/number

    async def _ensure_form(self, workspace_id: str) -> str:
        existing = (
            await self.db.execute(
                select(TicketForm.id).where(
                    TicketForm.workspace_id == workspace_id,
                    TicketForm.slug == SERVICE_DESK_FORM_SLUG,
                )
            )
        ).scalar_one_or_none()
        if existing:
            return existing

        owner_id = (
            await self.db.execute(select(Workspace.owner_id).where(Workspace.id == workspace_id))
        ).scalar_one_or_none()

        form = TicketForm(
            id=str(uuid4()),
            workspace_id=workspace_id,
            name="Bimaplan Service Desk",
            slug=SERVICE_DESK_FORM_SLUG,
            description="Auto-created intake form for email-originated service desk tickets.",
            created_by_id=owner_id,
        )
        try:
            async with self.db.begin_nested():
                self.db.add(form)
            return form.id
        except IntegrityError:
            # Concurrent intake created the form first — reuse it.
            existing = (
                await self.db.execute(
                    select(TicketForm.id).where(
                        TicketForm.workspace_id == workspace_id,
                        TicketForm.slug == SERVICE_DESK_FORM_SLUG,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                return existing
            raise

    async def _next_ticket_number(self, workspace_id: str) -> int:
        stmt = select(func.max(Ticket.ticket_number)).where(Ticket.workspace_id == workspace_id)
        return ((await self.db.execute(stmt)).scalar() or 0) + 1

    # ------------------------------------------------------- best-effort hooks

    async def _ai_enabled(self, workspace_id: str) -> bool:
        return await ai_classification_enabled(self.db, workspace_id)

    async def _auto_split_enabled(self, workspace_id: str) -> bool:
        """Whether intake may auto-create a second ticket. Off unless switched on."""
        ws = await self.db.get(Workspace, workspace_id)
        if ws is None:
            return False
        return bool(((ws.settings or {}).get("service_desk") or {}).get("auto_split_enabled", False))

    async def _classify(
        self, workspace_id: str, sd: ServiceDeskTicket, email: InboundEmail
    ) -> tuple[list[dict], bool]:
        """Persist bounded issue candidates on the primary ticket.

        Returns ``(issues, overflow)``. Creating tickets from them is the
        caller's decision — this method never splits.
        """
        try:
            from aexy.llm.gateway import get_llm_gateway

            lob_rows = (
                await self.db.execute(
                    select(ServiceDeskLOB.name, ServiceDeskLOB.id).where(
                        ServiceDeskLOB.workspace_id == workspace_id,
                        ServiceDeskLOB.is_active.is_(True),
                    )
                )
            ).all()
            lob_ids = {str(name).lower(): lob_id for name, lob_id in lob_rows}
            lob_list = ", ".join(name for name, _ in lob_rows) if lob_rows else "(none configured)"
            system = (
                "You classify insurance operations emails and detect independently actionable issues. "
                "Return one issue for a batch of rows requiring the same workflow. Split candidates "
                "only when requests need materially different workflows or outcomes. Reply with "
                'compact JSON: {"issues":[{"summary":"short action", "request_type": one of '
                '[query, policy_issuance, claims, payout], "lob": one provided LOB or null, '
                '"confidence":0..1, "split_reason":"why independent or null"}]}. '
                f"Return between one and {_MAX_ISSUES_PER_EMAIL} issues. JSON only."
            )
            attachment_context = "\n".join(
                "- "
                + attachment.filename
                + f" ({attachment.content_type or 'unknown type'}, "
                + f"{attachment.size_bytes or 0} bytes)"
                + (f": {attachment.preview}" if attachment.preview else "")
                for attachment in email.attachments[:3]
            ) or "(none)"
            user = (
                f"LOBs: {lob_list}\nSubject: {email.subject}\n\n"
                f"{(email.body_text or '')[:2000]}\n\n"
                "Attachment context (metadata and deliberately limited previews):\n"
                f"{attachment_context}"
            )
            gateway = get_llm_gateway()
            text, *_ = await gateway.call_llm(
                system,
                user,
                tokens_estimate=650,
                workspace_id=workspace_id,
            )

            match = re.search(r"\{.*\}", text, re.DOTALL)
            if not match:
                raise ValueError("classification response did not contain JSON")
            data = json.loads(match.group(0))
            raw_issues = data.get("issues")
            if not isinstance(raw_issues, list):
                raw_issues = [data]

            primary_ticket = await self.db.get(Ticket, sd.ticket_id)
            if primary_ticket is None:
                raise ValueError("primary ticket disappeared during classification")
            primary_values = dict(primary_ticket.field_values or {})
            issues_overflow = len(raw_issues) > _MAX_ISSUES_PER_EMAIL
            if issues_overflow:
                primary_values["issues_overflow"] = True
                primary_ticket.field_values = primary_values

            issues = self._normalise_issues(raw_issues)
            if not issues:
                raise ValueError("classification response contained no valid issues")

            self._apply_issue(sd, issues[0], lob_ids)
            primary_values["detected_issues"] = issues
            primary_ticket.field_values = primary_values
            await self.db.flush()
            return issues, issues_overflow
        except Exception as exc:  # noqa: BLE001 — classification is best-effort
            sd.needs_triage = True
            logger.info("Service desk: AI classification skipped (%s)", exc)
            return [], False

    @staticmethod
    def _normalise_issues(raw_issues: list[object]) -> list[dict]:
        """Validate, deduplicate, and hard-cap model-proposed issue candidates."""
        valid_types = {item.value for item in RequestType}
        issues: list[dict] = []
        seen: set[tuple[str, str, str]] = set()
        for raw in raw_issues[:_MAX_ISSUES_PER_EMAIL]:
            if not isinstance(raw, dict):
                continue
            summary = " ".join(str(raw.get("summary") or "").split())[:240]
            if not summary:
                continue
            request_type = str(raw.get("request_type") or "query").lower()
            if request_type not in valid_types:
                request_type = RequestType.QUERY.value
            lob = str(raw["lob"]).strip()[:255] if raw.get("lob") else None
            try:
                confidence = max(0.0, min(1.0, float(raw.get("confidence", 0))))
            except (TypeError, ValueError):
                confidence = 0.0
            fingerprint = (summary.lower(), request_type, (lob or "").lower())
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            issues.append(
                {
                    "summary": summary,
                    "request_type": request_type,
                    "lob": lob,
                    "confidence": confidence,
                    "split_reason": str(raw.get("split_reason") or "")[:300] or None,
                }
            )
        return issues

    @staticmethod
    def _apply_issue(sd: ServiceDeskTicket, issue: dict, lob_ids: dict[str, str]) -> None:
        """Apply only configured classification values to the primary ticket."""
        sd.request_type = issue["request_type"]
        sd.ai_confidence = issue["confidence"]
        if issue["confidence"] < 0.6:
            sd.needs_triage = True
        if issue.get("lob"):
            sd.lob_id = lob_ids.get(str(issue["lob"]).lower())

    async def _send_receipt(
        self,
        workspace_id: str,
        ticket: Ticket,
        mailbox: ServiceDeskMailbox | None,
        thread_id: str | None = None,
        children: list[Ticket] | None = None,
    ) -> None:
        """Queue the acknowledgement email; sent by ``flush_notifications()``.

        One message in means one acknowledgement out, naming every ticket it
        produced — the requester wrote once and should be told once.
        """
        if not ticket.submitter_email:
            return
        child_ids = [f"{TICKET_PREFIX}-{child.ticket_number}" for child in (children or [])]
        additional = ""
        if child_ids:
            additional = (
                "Your email covered more than one request, so we also logged "
                + ("Tickets " if len(child_ids) > 1 else "Ticket ")
                + ", ".join(f"#{display_id}" for display_id in child_ids)
                + "."
            )
        self._pending_notifications.append(
            {
                "workspace_id": workspace_id,
                "mailbox_id": mailbox.id if mailbox is not None else None,
                "to": ticket.submitter_email,
                "thread_id": thread_id,
                "vars": {
                    "display_id": f"{TICKET_PREFIX}-{ticket.ticket_number}",
                    "subject": (ticket.field_values or {}).get("subject") or "Your request",
                    "requester_name": ticket.submitter_name or "there",
                    "additional_tickets": additional,
                },
            }
        )

    async def flush_notifications(self) -> None:
        """Send queued acknowledgements. Call AFTER committing; never raises.

        Kept separate from ``ingest`` so a rolled-back transaction can't leave a
        requester holding a receipt for a ticket that does not exist.
        """
        pending, self._pending_notifications = self._pending_notifications, []
        if not pending:
            return
        from aexy.services.service_desk_mailer import send_service_desk_email
        from aexy.services.service_desk_templates import render_sd

        for item in pending:
            try:
                mailbox = (
                    await self.db.get(ServiceDeskMailbox, item["mailbox_id"])
                    if item["mailbox_id"]
                    else None
                )
                subject, body = await render_sd(self.db, item["workspace_id"], "receipt", item["vars"])
                await send_service_desk_email(
                    self.db, mailbox, item["to"], subject, body, thread_id=item["thread_id"]
                )
            except Exception as exc:  # noqa: BLE001 — acknowledgements are best-effort
                logger.warning("Service desk: receipt send skipped (%s)", exc)

    # ---------------------------------------------------------- mailbox lookup

    async def find_mailbox(self, workspace_id: str, address: str) -> ServiceDeskMailbox | None:
        return (
            await self.db.execute(
                select(ServiceDeskMailbox).where(
                    ServiceDeskMailbox.workspace_id == workspace_id,
                    func.lower(ServiceDeskMailbox.address) == address.lower(),
                    ServiceDeskMailbox.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()

    @staticmethod
    async def find_mailbox_by_address(db: AsyncSession, address: str) -> ServiceDeskMailbox | None:
        """Workspace-agnostic lookup used by inbound webhooks (to_email → mailbox).

        Addresses are only unique per workspace, so two workspaces may register
        the same one. Pick the oldest deterministically rather than raising
        MultipleResultsFound, which would 500 every inbound email.
        """
        return (
            await db.execute(
                select(ServiceDeskMailbox)
                .where(
                    func.lower(ServiceDeskMailbox.address) == address.lower(),
                    ServiceDeskMailbox.is_active.is_(True),
                )
                .order_by(ServiceDeskMailbox.created_at, ServiceDeskMailbox.id)
            )
        ).scalars().first()

    @staticmethod
    async def find_mailbox_by_integration(db: AsyncSession, integration_id: str) -> ServiceDeskMailbox | None:
        """Lookup used by the Gmail sync fan-out (integration → mailbox)."""
        mailbox = (
            await db.execute(
                select(ServiceDeskMailbox)
                .where(
                    ServiceDeskMailbox.integration_id == integration_id,
                    ServiceDeskMailbox.channel == MailboxChannel.GMAIL_SYNC.value,
                    ServiceDeskMailbox.is_active.is_(True),
                )
                .order_by(ServiceDeskMailbox.created_at, ServiceDeskMailbox.id)
            )
        ).scalars().first()
        if mailbox is not None:
            return mailbox

        # Older gmail_sync mailbox records were created before the integration
        # link was populated. Recover only when the mailbox address is exactly
        # the connected Google account, then persist the link for later syncs.
        from aexy.models.google_integration import GoogleIntegration

        mailbox = (
            await db.execute(
                select(ServiceDeskMailbox)
                .join(GoogleIntegration, GoogleIntegration.workspace_id == ServiceDeskMailbox.workspace_id)
                .where(
                    GoogleIntegration.id == integration_id,
                    func.lower(ServiceDeskMailbox.address) == func.lower(GoogleIntegration.google_email),
                    ServiceDeskMailbox.channel == MailboxChannel.GMAIL_SYNC.value,
                    ServiceDeskMailbox.is_active.is_(True),
                )
                .order_by(ServiceDeskMailbox.created_at, ServiceDeskMailbox.id)
            )
        ).scalars().first()
        if mailbox is not None:
            mailbox.integration_id = integration_id
            await db.flush()
        return mailbox

"""A delivery-failure notice must not become the ticket's reply-to address.

Reported as "she is not able to reply to the email". SD-313 on the Bimaplan desk
had been sent to a misspelling of the desk's own address, which bounced NXDOMAIN;
the bounce from ``mailer-daemon@googlemail.com`` was matched onto the ticket, and
the compose box then prefilled the daemon as **To** with the actual customer
demoted to **Cc**.

The cause was one misplaced call. ``_append_reply`` ran
``_absorb_participants`` *before* its own ``if automatic: return`` guard and
never passed the flag down, so a bounce correctly failed to reopen the ticket
while still being recorded as "the last person who wrote in". Every reply then
bounced, and every new bounce re-applied the same rule.

Both directions are pinned here: intake must stop storing such an address, and
the read path must stop trusting one that is already stored — tickets already
poisoned have to recover without a migration.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.service_desk import ServiceDeskMailbox
from aexy.models.ticketing import Ticket, TicketForm
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import InboundEmail
from aexy.services.service_desk_config import is_non_reply_address
from aexy.services.service_desk_intake_service import ServiceDeskIntakeService
from aexy.services.service_desk_ticket_service import ServiceDeskTicketService

DESK = "ops@desk.example"
CUSTOMER = "customer@partner.example"
DAEMON = "mailer-daemon@googlemail.com"

# What Gmail actually sends back, headers included. `Auto-Submitted` is the
# RFC 3834 marker that makes `is_automatic_response` true.
BOUNCE_HEADERS = {
    "auto-submitted": "auto-replied",
    "from": DAEMON,
    "to": DESK,
    "subject": "Delivery Status Notification (Failure)",
}
BOUNCE_BODY = (
    "** Address not found **\n\n"
    "Your message wasn't delivered to operations@bimapla.co because the domain "
    "bimapla.co couldn't be found.\n\n"
    "DNS Error: DNS type 'mx' lookup of bimapla.co responded with code NXDOMAIN"
)


class _Desk:
    ws: Workspace
    mailbox: ServiceDeskMailbox
    ticket: Ticket


async def _desk(db: AsyncSession, slug: str) -> _Desk:
    d = _Desk()
    owner = Developer(id=str(uuid4()), email=f"owner-{slug}@desk.example", name="Owner")
    db.add(owner)
    await db.flush()

    d.ws = Workspace(
        id=str(uuid4()), name=f"WS {slug}", slug=slug, owner_id=owner.id, settings={}
    )
    db.add(d.ws)
    await db.flush()
    db.add(
        WorkspaceMember(
            id=str(uuid4()), workspace_id=d.ws.id, developer_id=owner.id, role="member"
        )
    )

    d.mailbox = ServiceDeskMailbox(
        id=str(uuid4()), workspace_id=d.ws.id, address=DESK, channel="webhook"
    )
    form = TicketForm(
        id=str(uuid4()), workspace_id=d.ws.id, name="SD", slug="service-desk",
        created_by_id=owner.id,
    )
    db.add_all([d.mailbox, form])
    await db.flush()

    # A ticket mid-conversation with a real customer, which is the state a
    # bounce arrives into.
    d.ticket = Ticket(
        id=str(uuid4()),
        workspace_id=d.ws.id,
        form_id=form.id,
        ticket_number=41,
        title="Claim for a stolen power bank",
        submitter_email=CUSTOMER,
        submitter_name="Customer",
        status="new",
        field_values={
            "thread_reply_to": CUSTOMER,
            "thread_participants": [CUSTOMER],
        },
    )
    db.add(d.ticket)
    await db.commit()
    return d


# --------------------------------------------------------------- the predicate


@pytest.mark.parametrize(
    "address",
    [
        DAEMON,
        "MAILER-DAEMON@googlemail.com",
        "postmaster@partner.example",
        "no-reply@partner.example",
        "noreply@partner.example",
        "donotreply@partner.example",
        "bounces@partner.example",
        # VERP: the tag is stable, the id after it is generated per message.
        "bounces+1234-abc@partner.example",
    ],
)
def test_addresses_no_human_reads_are_recognised(address: str) -> None:
    assert is_non_reply_address(address) is True


@pytest.mark.parametrize(
    "address",
    [
        CUSTOMER,
        # A real person at a shared mailbox. Catching this would silence exactly
        # the correspondents a desk exists to answer, so the predicate stays
        # narrow on purpose.
        "support@partner.example",
        "operations@bimaplan.co",
        "reply@partner.example",
        "daemon.smith@partner.example",
        None,
        "",
        "not-an-address",
    ],
)
def test_real_correspondents_are_left_alone(address: str | None) -> None:
    assert is_non_reply_address(address) is False


# ------------------------------------------------------------------ the intake


@pytest.mark.asyncio
async def test_a_bounce_does_not_become_the_reply_to_address(
    db_session: AsyncSession,
) -> None:
    """The reported bug, at the point where it was introduced."""
    d = await _desk(db_session, "bounce-intake")
    intake = ServiceDeskIntakeService(db_session)

    await intake._append_reply(
        d.ws.id,
        d.ticket,
        InboundEmail(
            to=DESK,
            from_email=DAEMON,
            subject="Delivery Status Notification (Failure)",
            body_text=BOUNCE_BODY,
            headers=BOUNCE_HEADERS,
        ),
        d.mailbox,
        automatic=True,
    )
    await db_session.commit()

    values = d.ticket.field_values or {}
    assert values.get("thread_reply_to") == CUSTOMER
    assert DAEMON not in (values.get("thread_participants") or [])


@pytest.mark.asyncio
async def test_a_real_reply_still_becomes_the_reply_to_address(
    db_session: AsyncSession,
) -> None:
    """The guard must not cost the behaviour it sits next to.

    A thread that has moved on to an insurer's handler has to answer that
    handler, not the person who opened it — so a human reply still takes over
    ``thread_reply_to``.
    """
    d = await _desk(db_session, "bounce-human")
    intake = ServiceDeskIntakeService(db_session)
    handler = "handler@insurer.example"

    await intake._append_reply(
        d.ws.id,
        d.ticket,
        InboundEmail(
            to=DESK,
            from_email=handler,
            subject="Re: [SD-41] Claim for a stolen power bank",
            body_text="We need the police report.",
            headers={"from": handler, "to": DESK},
        ),
        d.mailbox,
        automatic=False,
    )
    await db_session.commit()

    values = d.ticket.field_values or {}
    assert values.get("thread_reply_to") == handler
    assert handler in (values.get("thread_participants") or [])


@pytest.mark.asyncio
async def test_a_daemon_address_is_refused_even_without_the_headers(
    db_session: AsyncSession,
) -> None:
    """Belt and braces: some providers send a bounce carrying no auto markers.

    ``automatic`` is then false, so the address itself has to be the thing that
    disqualifies it.
    """
    d = await _desk(db_session, "bounce-bare")
    intake = ServiceDeskIntakeService(db_session)

    await intake._append_reply(
        d.ws.id,
        d.ticket,
        InboundEmail(
            to=DESK,
            from_email=DAEMON,
            subject="Returned mail",
            body_text=BOUNCE_BODY,
            headers={"from": DAEMON, "to": DESK},
        ),
        d.mailbox,
        automatic=False,
    )
    await db_session.commit()

    values = d.ticket.field_values or {}
    assert values.get("thread_reply_to") == CUSTOMER
    assert DAEMON not in (values.get("thread_participants") or [])


# -------------------------------------------------------------- the read path


def test_a_ticket_already_poisoned_recovers_without_a_migration() -> None:
    """The tickets that already have a daemon stored have to answer somebody.

    Asked on read rather than migrated: this is what makes SD-313 answerable the
    moment the fix ships, and the requester is — on a bounced thread — exactly
    the person still waiting.
    """
    ticket = Ticket(
        id=str(uuid4()),
        workspace_id=str(uuid4()),
        ticket_number=313,
        submitter_email=CUSTOMER,
        field_values={
            "thread_reply_to": DAEMON,
            "thread_participants": [CUSTOMER, DAEMON],
        },
    )

    reply_all = ServiceDeskTicketService._reply_all(ticket, DESK)

    assert reply_all.to == CUSTOMER
    assert DAEMON not in reply_all.cc
    # And the customer is not left in Cc as well as To, which would read as a
    # mistake on the sent mail.
    assert reply_all.cc == []


def test_the_desk_is_still_excluded_from_its_own_reply() -> None:
    """A desk address in Cc comes back through the sync as new correspondence."""
    ticket = Ticket(
        id=str(uuid4()),
        workspace_id=str(uuid4()),
        ticket_number=42,
        submitter_email=CUSTOMER,
        field_values={
            "thread_reply_to": CUSTOMER,
            "thread_participants": [CUSTOMER, DESK, "broker@broker.example"],
        },
    )

    reply_all = ServiceDeskTicketService._reply_all(ticket, DESK)

    assert reply_all.to == CUSTOMER
    assert reply_all.cc == ["broker@broker.example"]


# ------------------------------------------- the two questions are not the same


def test_a_vendors_no_reply_notice_still_carries_a_request() -> None:
    """The regression this file's first fix nearly introduced.

    ``is_non_reply_address`` answers "can the desk write back?" and covers
    ``no-reply@``. ``is_automatic_response`` asks something else — "did this
    message carry a request?" — and a vendor emailing policy documents from
    ``no-reply@insurer.com`` carries the whole thing. Conflating the two would
    force every such ticket to triage, skip its classification, withhold its
    receipt and stop a reply reopening it, which is exactly what
    ``_sender_is_ignored`` refuses to infer from an address.
    """
    from aexy.services.service_desk_config import is_bounce_address
    from aexy.services.service_desk_intake_service import is_automatic_response

    notice = InboundEmail(
        to=DESK,
        from_email="no-reply@insurer.example",
        subject="Policy documents for BP-1029",
        body_text="Please find the certificate attached.",
        headers={"from": "no-reply@insurer.example", "to": DESK},
    )

    # Not writable-to...
    assert is_non_reply_address("no-reply@insurer.example") is True
    # ...but not a bounce, and not contentless.
    assert is_bounce_address("no-reply@insurer.example") is False
    assert is_automatic_response(notice) is False


def test_a_bounce_is_still_recognised_without_headers() -> None:
    """The case the address arm exists for."""
    from aexy.services.service_desk_intake_service import is_automatic_response

    assert is_automatic_response(
        InboundEmail(
            to=DESK,
            from_email=DAEMON,
            subject="Returned mail",
            body_text=BOUNCE_BODY,
            headers={"from": DAEMON, "to": DESK},
        )
    ) is True


def test_an_out_of_office_is_still_recognised_from_its_headers() -> None:
    """The header arm is untouched by the split."""
    from aexy.services.service_desk_intake_service import is_automatic_response

    assert is_automatic_response(
        InboundEmail(
            to=DESK,
            from_email="handler@insurer.example",
            subject="Out of office",
            body_text="Back Monday.",
            headers={"auto-submitted": "auto-replied"},
        )
    ) is True

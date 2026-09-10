"""Priority, internal notes, and splitting a merged thread.

Three gaps reported together, all in the same area of the ticket surface:

* **Priority** existed on ``Ticket`` and was used by the generic Tickets module,
  but nothing in Service Desk read, wrote, filtered or displayed it — so every
  ticket carried null and urgency was expressed only as TAT breach level, which
  is a clock rather than a severity.

* **Notes** had storage (``TicketResponse.is_internal``) that the desk already
  wrote its own audit trail into, no endpoint to add one, and a detail query
  that filtered them out — so a colleague's note *and* the system's account of
  what it did were both unreachable from the ticket.

* **Splitting messages** is the only thing that repairs a ticket which absorbed
  a second, unrelated request — which is what an unqualified provider thread-id
  match used to do on any long email chain.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.service_desk import ServiceDeskMailbox, ServiceDeskTicket
from aexy.models.ticketing import Ticket, TicketForm, TicketResponse
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import (
    MailboxResponse,
    TicketFieldsUpdate,
    TicketFilters,
)
from aexy.services.service_desk_service import ServiceDeskService
from aexy.services.service_desk_ticket_service import ServiceDeskTicketService
from tests.conftest import seed_service_desk_taxonomy

DESK = "ops@desk.example"


class _Desk:
    ws: Workspace
    mailbox: ServiceDeskMailbox
    ticket: Ticket
    sd: ServiceDeskTicket
    kam: Developer
    form: TicketForm


async def _desk(db: AsyncSession, slug: str, *, messages: int = 3) -> _Desk:
    d = _Desk()
    owner = Developer(id=str(uuid4()), email=f"owner-{slug}@d.example", name="Owner")
    d.kam = Developer(id=str(uuid4()), email=f"kam-{slug}@d.example", name="A KAM")
    db.add_all([owner, d.kam])
    await db.flush()

    d.ws = Workspace(
        id=str(uuid4()), name=f"WS {slug}", slug=slug, owner_id=owner.id, settings={}
    )
    db.add(d.ws)
    await db.flush()
    for dev in (owner, d.kam):
        db.add(
            WorkspaceMember(
                id=str(uuid4()), workspace_id=d.ws.id, developer_id=dev.id, role="member"
            )
        )
    d.form = TicketForm(
        id=str(uuid4()), workspace_id=d.ws.id, name="SD", slug="service-desk",
        created_by_id=owner.id,
    )
    d.mailbox = ServiceDeskMailbox(
        id=str(uuid4()), workspace_id=d.ws.id, address=DESK, channel="gmail_sync"
    )
    db.add_all([d.form, d.mailbox])
    await db.flush()

    d.ticket = Ticket(
        id=str(uuid4()),
        workspace_id=d.ws.id,
        form_id=d.form.id,
        ticket_number=41,
        title="EHF Onboarding",
        submitter_email="partner@d.example",
        submitter_name="Partner",
        status="new",
        assignee_id=d.kam.id,
        field_values={"subject": "EHF Onboarding"},
    )
    db.add(d.ticket)
    await db.flush()
    d.sd = ServiceDeskTicket(
        id=str(uuid4()),
        workspace_id=d.ws.id,
        ticket_id=d.ticket.id,
        mailbox_id=d.mailbox.id,
        request_type="query",
        pending_with="kam",
        origin="internal",
        thread_ref="thread-1",
    )
    db.add(d.sd)

    for i in range(messages):
        db.add(
            TicketResponse(
                id=str(uuid4()),
                ticket_id=d.ticket.id,
                author_email="partner@d.example",
                content=f"Subject: Message {i}\n\nBody of message {i}",
                is_internal=False,
            )
        )
    await seed_service_desk_taxonomy(db, d.ws.id)
    await db.commit()
    return d


# ==================================================================== priority


def test_priority_is_a_filter_and_a_sort() -> None:
    """Absent from `TicketFilters` entirely, so a queue could not be worked by it."""
    f = TicketFilters(priority="urgent", sort="priority", direction="desc")
    assert f.priority == "urgent"
    assert f.sort == "priority"


def test_an_unknown_priority_is_refused_at_the_wire() -> None:
    """Named exception, not bare `Exception`: the point is that Pydantic rejects
    it, and a test that accepts any error would also pass on a typo here."""
    with pytest.raises(ValidationError):
        TicketFilters(priority="catastrophic")


@pytest.mark.asyncio
async def test_priority_is_saved_and_returned(db_session: AsyncSession) -> None:
    """It lives on `Ticket`, not `ServiceDeskTicket`.

    Every other field in this payload writes to the service-desk row, so a
    naive loop over it would set an attribute that row does not have and drop
    the value in silence.
    """
    d = await _desk(db_session, "np-prio")
    service = ServiceDeskTicketService(db_session)

    detail = await service.update_fields(
        d.ws.id, d.ticket.id, TicketFieldsUpdate(priority="urgent")
    )
    await db_session.commit()

    assert detail.priority == "urgent"
    row = await db_session.get(Ticket, d.ticket.id)
    assert row is not None and row.priority == "urgent"


@pytest.mark.asyncio
async def test_priority_reaches_the_list_rows(db_session: AsyncSession) -> None:
    """The list is where a queue is actually worked, so the column has to be there."""
    d = await _desk(db_session, "np-prio-list")
    d.ticket.priority = "high"
    await db_session.commit()

    rows = await ServiceDeskService(db_session).list_tickets(d.ws.id)

    assert len(rows) == 1
    assert rows[0].priority == "high"


@pytest.mark.asyncio
async def test_an_unset_priority_stays_unset(db_session: AsyncSession) -> None:
    """"Nobody has said" is a different fact from "medium" and must survive.

    Defaulting it on read would report every one of the desk's existing tickets
    as deliberately triaged.
    """
    d = await _desk(db_session, "np-prio-null")

    rows = await ServiceDeskService(db_session).list_tickets(d.ws.id)

    assert rows[0].priority is None


# ======================================================================= notes


@pytest.mark.asyncio
async def test_a_note_can_be_added_and_read_back(db_session: AsyncSession) -> None:
    d = await _desk(db_session, "np-note")
    service = ServiceDeskTicketService(db_session)

    note = await service.add_note(
        d.ws.id, d.ticket.id, "Chased the insurer, waiting on a claim number.", d.kam.id
    )
    await db_session.commit()

    assert note.author_name == "A KAM"
    assert note.system is False

    notes = await service.list_notes(d.ws.id, d.ticket.id)
    assert [n.content for n in notes] == [
        "Chased the insurer, waiting on a claim number."
    ]


@pytest.mark.asyncio
async def test_a_note_is_not_correspondence(db_session: AsyncSession) -> None:
    """The distinction the whole design rests on.

    `correspondence` means "mail that left or arrived". A note has never been
    sent to anybody, and rendering the two in one stream is how somebody ends up
    believing a partner was told something.
    """
    d = await _desk(db_session, "np-note-apart", messages=1)
    service = ServiceDeskTicketService(db_session)

    await service.add_note(d.ws.id, d.ticket.id, "Internal only.", d.kam.id)
    await db_session.commit()

    detail = await service.get_detail(d.ws.id, d.ticket.id)

    assert [n.content for n in detail.notes] == ["Internal only."]
    assert all("Internal only." not in c.content for c in detail.correspondence)
    assert len(detail.correspondence) == 1


@pytest.mark.asyncio
async def test_the_desks_own_notes_are_returned_too(db_session: AsyncSession) -> None:
    """These already existed and were unreachable — transitions, splits, merges.

    Surfacing them is most of the value: until now nobody could read the desk's
    own explanation of what it had done.
    """
    d = await _desk(db_session, "np-note-system", messages=1)
    db_session.add(
        TicketResponse(
            id=str(uuid4()),
            ticket_id=d.ticket.id,
            author_id=None,
            content="Pending With changed from KAM to Insurer — emailed the insurer",
            is_internal=True,
        )
    )
    await db_session.commit()

    notes = await ServiceDeskTicketService(db_session).list_notes(d.ws.id, d.ticket.id)

    assert len(notes) == 1
    assert notes[0].system is True
    assert notes[0].author_name is None


@pytest.mark.asyncio
async def test_an_empty_note_is_refused(db_session: AsyncSession) -> None:
    d = await _desk(db_session, "np-note-empty")

    with pytest.raises(HTTPException) as exc:
        await ServiceDeskTicketService(db_session).add_note(
            d.ws.id, d.ticket.id, "   ", d.kam.id
        )
    assert exc.value.status_code == 422


# =============================================================== split messages


@pytest.mark.asyncio
async def test_messages_move_to_a_new_ticket(db_session: AsyncSession) -> None:
    """The repair for a merged thread."""
    d = await _desk(db_session, "np-split", messages=3)
    service = ServiceDeskTicketService(db_session)
    ids = (
        await db_session.execute(
            select(TicketResponse.id).where(TicketResponse.ticket_id == d.ticket.id)
        )
    ).scalars().all()
    moving = list(ids)[:2]

    result = await service.split_messages(
        d.ws.id, d.ticket.id, moving, actor_id=d.kam.id
    )
    await db_session.commit()

    assert result.moved == 2
    assert result.display_id.startswith("SD-")

    # They left the source and arrived on the target.
    left = (
        await db_session.execute(
            select(TicketResponse.ticket_id).where(TicketResponse.id.in_(moving))
        )
    ).scalars().all()
    assert set(left) == {result.ticket_id}


@pytest.mark.asyncio
async def test_the_new_ticket_inherits_the_partner_and_owner(
    db_session: AsyncSession,
) -> None:
    """A wrongly-merged message is nearly always the same partner.

    That similarity is *why* it merged, so inheriting is the useful default —
    and it is flagged for triage because the request type and product are
    inherited guesses.
    """
    d = await _desk(db_session, "np-split-inherit", messages=2)
    d.sd.account_id = None
    await db_session.commit()

    ids = (
        await db_session.execute(
            select(TicketResponse.id).where(TicketResponse.ticket_id == d.ticket.id)
        )
    ).scalars().all()

    result = await ServiceDeskTicketService(db_session).split_messages(
        d.ws.id, d.ticket.id, [next(iter(ids))], actor_id=d.kam.id
    )
    await db_session.commit()

    new_ticket = await db_session.get(Ticket, result.ticket_id)
    new_sd = (
        await db_session.execute(
            select(ServiceDeskTicket).where(
                ServiceDeskTicket.ticket_id == result.ticket_id
            )
        )
    ).scalar_one()

    assert new_ticket is not None
    assert new_ticket.assignee_id == d.kam.id
    assert new_ticket.submitter_email == "partner@d.example"
    assert new_sd.request_type == d.sd.request_type
    assert new_sd.needs_triage is True
    # Two rows sharing a thread_ref would break the very lookup that caused this.
    assert new_sd.thread_ref is None


@pytest.mark.asyncio
async def test_both_tickets_say_the_split_happened(db_session: AsyncSession) -> None:
    """Either ticket can be the one somebody is looking at when they wonder."""
    d = await _desk(db_session, "np-split-notes", messages=2)
    ids = (
        await db_session.execute(
            select(TicketResponse.id).where(TicketResponse.ticket_id == d.ticket.id)
        )
    ).scalars().all()

    result = await ServiceDeskTicketService(db_session).split_messages(
        d.ws.id, d.ticket.id, [next(iter(ids))], actor_id=d.kam.id
    )
    await db_session.commit()

    async def notes_on(ticket_id: str) -> list[str]:
        return list(
            (
                await db_session.execute(
                    select(TicketResponse.content).where(
                        TicketResponse.ticket_id == ticket_id,
                        TicketResponse.is_internal.is_(True),
                    )
                )
            ).scalars().all()
        )

    assert any("moved to" in n for n in await notes_on(d.ticket.id))
    assert any("Split from" in n for n in await notes_on(result.ticket_id))


@pytest.mark.asyncio
async def test_moving_everything_is_refused(db_session: AsyncSession) -> None:
    """That is a move, not a split — and the caller has the wrong ids."""
    d = await _desk(db_session, "np-split-all", messages=2)
    ids = (
        await db_session.execute(
            select(TicketResponse.id).where(TicketResponse.ticket_id == d.ticket.id)
        )
    ).scalars().all()

    with pytest.raises(HTTPException) as exc:
        await ServiceDeskTicketService(db_session).split_messages(
            d.ws.id, d.ticket.id, list(ids), actor_id=d.kam.id
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_a_note_cannot_be_split_off(db_session: AsyncSession) -> None:
    """Notes are commentary on *this* ticket's handling, not the requester's mail.

    Moving one would rewrite the history of the ticket it was written on.
    """
    d = await _desk(db_session, "np-split-note", messages=2)
    note = TicketResponse(
        id=str(uuid4()),
        ticket_id=d.ticket.id,
        author_id=d.kam.id,
        content="A note",
        is_internal=True,
    )
    db_session.add(note)
    await db_session.commit()

    with pytest.raises(HTTPException) as exc:
        await ServiceDeskTicketService(db_session).split_messages(
            d.ws.id, d.ticket.id, [note.id], actor_id=d.kam.id
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_a_message_from_another_ticket_is_refused(
    db_session: AsyncSession,
) -> None:
    """The ids come straight off a request body."""
    d = await _desk(db_session, "np-split-foreign", messages=2)

    with pytest.raises(HTTPException) as exc:
        await ServiceDeskTicketService(db_session).split_messages(
            d.ws.id, d.ticket.id, [str(uuid4())], actor_id=d.kam.id
        )
    assert exc.value.status_code == 404


# ===================================================== mailbox can_send (MAIL-2)


def test_a_webhook_mailbox_says_it_cannot_send() -> None:
    """Outbound needs a connected Gmail account.

    A webhook mailbox receives everything and can answer nothing, and the only
    sign of that used to be a RuntimeError at the moment somebody pressed Send
    on a ticket a customer was waiting on.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    gmail = MailboxResponse(
        id="1", workspace_id="w", address="a@b.co", channel="gmail_sync",
        integration_id="i", created_at=now,
    )
    webhook = MailboxResponse(
        id="2", workspace_id="w", address="c@d.co", channel="webhook", created_at=now,
    )
    unlinked = MailboxResponse(
        id="3", workspace_id="w", address="e@f.co", channel="gmail_sync",
        integration_id=None, created_at=now,
    )

    assert gmail.can_send is True
    assert webhook.can_send is False
    # Gmail channel with no integration is the same dead end, and used to look
    # identical to a working mailbox on the settings page.
    assert unlinked.can_send is False


@pytest.mark.asyncio
async def test_the_split_ticket_gets_a_number_that_does_not_collide(
    db_session: AsyncSession,
) -> None:
    """Routed through intake's `_insert_ticket`, which retries in a savepoint.

    `ticket_number` is max()+1 against a real `uq_ticket_number` constraint, so
    a split racing an inbound email collides. Allocating the number by hand and
    building the row skipped that protection — and an IntegrityError escaping
    here would not merely fail the split, it would leave the session needing
    rollback and turn the whole request into a 500.
    """
    d = await _desk(db_session, "np-split-number", messages=2)
    ids = (
        await db_session.execute(
            select(TicketResponse.id).where(TicketResponse.ticket_id == d.ticket.id)
        )
    ).scalars().all()

    result = await ServiceDeskTicketService(db_session).split_messages(
        d.ws.id, d.ticket.id, [next(iter(ids))], actor_id=d.kam.id
    )
    await db_session.commit()

    new_ticket = await db_session.get(Ticket, result.ticket_id)
    assert new_ticket is not None
    # A real, distinct number — and the display id agrees with it, which it did
    # not when the number was allocated separately from the insert.
    assert new_ticket.ticket_number != d.ticket.ticket_number
    assert result.display_id.endswith(str(new_ticket.ticket_number))

    numbers = (
        await db_session.execute(
            select(Ticket.ticket_number).where(Ticket.workspace_id == d.ws.id)
        )
    ).scalars().all()
    assert len(numbers) == len(set(numbers)), "ticket numbers must stay unique"


@pytest.mark.asyncio
async def test_the_split_announces_the_new_ticket(db_session: AsyncSession) -> None:
    """A split produces a real ticket with a real owner, so it fires the event.

    Without this the new owner had no signal until the next daily digest and an
    automation watching `service_desk.ticket_created` never ran for it.
    """
    d = await _desk(db_session, "np-split-event", messages=2)
    ids = (
        await db_session.execute(
            select(TicketResponse.id).where(TicketResponse.ticket_id == d.ticket.id)
        )
    ).scalars().all()

    service = ServiceDeskTicketService(db_session)
    seen: list[str] = []

    import aexy.services.service_desk_ticket_service as module

    original = module.dispatch_service_desk_event

    async def _spy(db, workspace_id, trigger_type, ticket, sd, **extra):
        seen.append(trigger_type)
        return await original(db, workspace_id, trigger_type, ticket, sd, **extra)

    module.dispatch_service_desk_event = _spy
    try:
        await service.split_messages(
            d.ws.id, d.ticket.id, [next(iter(ids))], actor_id=d.kam.id
        )
    finally:
        module.dispatch_service_desk_event = original
    await db_session.commit()

    assert "service_desk.ticket_created" in seen
    # No self-notification: the new ticket inherits the source's owner, who is
    # the person doing the splitting here. Telling them about a ticket they just
    # made is noise.
    assert not any(a["kind"] == "assigned" for a in service._pending_alerts)


@pytest.mark.asyncio
async def test_the_split_notifies_an_owner_who_is_not_the_splitter(
    db_session: AsyncSession,
) -> None:
    """Queued, not sent: the API layer commits after the handler returns.

    Sending inline would announce a ticket a rollback could still remove.
    """
    d = await _desk(db_session, "np-split-notify", messages=2)
    splitter = Developer(id=str(uuid4()), email="splitter@d.example", name="Splitter")
    db_session.add(splitter)
    await db_session.flush()
    db_session.add(
        WorkspaceMember(
            id=str(uuid4()), workspace_id=d.ws.id, developer_id=splitter.id, role="member"
        )
    )
    await db_session.commit()

    ids = (
        await db_session.execute(
            select(TicketResponse.id).where(TicketResponse.ticket_id == d.ticket.id)
        )
    ).scalars().all()

    service = ServiceDeskTicketService(db_session)
    await service.split_messages(
        d.ws.id, d.ticket.id, [next(iter(ids))], actor_id=splitter.id
    )
    await db_session.commit()

    alerts = [a for a in service._pending_alerts if a["kind"] == "assigned"]
    assert len(alerts) == 1
    assert alerts[0]["recipient_id"] == str(d.kam.id)

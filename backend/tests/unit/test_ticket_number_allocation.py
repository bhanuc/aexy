"""Every path that creates a ticket allocates its number the same way.

`migrate_atomic_issue_keys` moved ticket numbering onto a counter on the
workspace row, but only `TicketService` was moved onto it. Four other creation
paths kept doing `MAX(ticket_number) + 1`, which left them racy and — worse —
advanced the high-water mark without advancing the counter. Once those drift
apart it is the *fixed* path that breaks: `tickets` has a unique constraint on
(workspace_id, ticket_number), so the public form answered 500 on every
submission until the counter climbed back past the highest number in use.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.ticketing import Ticket, TicketForm, TicketStatus
from aexy.models.workspace import Workspace
from aexy.services.ticket_numbering import next_ticket_number


async def _workspace(db: AsyncSession, slug: str) -> Workspace:
    dev = Developer(name=f"Dev {slug}", email=f"{slug}@example.test")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.flush()
    return ws


async def _form(db: AsyncSession, ws: Workspace) -> TicketForm:
    form = TicketForm(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="Support",
        slug=f"support-{ws.slug}",
        public_url_token=f"tok-{ws.slug}",
        is_active=True,
        auth_mode="anonymous",
        require_email=False,
        theme={},
        destinations=[],
        conditional_rules=[],
    )
    db.add(form)
    await db.flush()
    return form


def _ticket(ws_id: str, form_id: str, number: int) -> Ticket:
    return Ticket(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        form_id=form_id,
        ticket_number=number,
        title=f"t{number}",
        status=TicketStatus.NEW.value,
        field_values={},
        attachments=[],
    )


@pytest.mark.asyncio
async def test_numbers_are_distinct_and_never_reused(db_session: AsyncSession):
    ws = await _workspace(db_session, "alloc-ws")
    issued = [await next_ticket_number(db_session, ws.id) for _ in range(5)]
    assert issued == [1, 2, 3, 4, 5]


@pytest.mark.asyncio
async def test_a_deleted_ticket_does_not_give_its_number_back(
    db_session: AsyncSession,
):
    """The counter, unlike MAX()+1, never reissues."""
    ws = await _workspace(db_session, "reuse-ws")
    form = await _form(db_session, ws)
    first = await next_ticket_number(db_session, ws.id)
    ticket = _ticket(ws.id, form.id, first)
    db_session.add(ticket)
    await db_session.flush()
    await db_session.delete(ticket)
    await db_session.flush()

    assert await next_ticket_number(db_session, ws.id) == first + 1


@pytest.mark.asyncio
async def test_a_counter_left_behind_would_collide(db_session: AsyncSession):
    """The exact production failure, reproduced through the constraint.

    A ticket inserted at a number the counter does not know about is what the
    counting paths used to do on every insert. Pinning it here so the
    consequence of regressing one of them is visible in the suite rather than
    on a public form.
    """
    ws = await _workspace(db_session, "drift-ws")
    form = await _form(db_session, ws)
    db_session.add(_ticket(ws.id, form.id, 7))  # as a counting path would have
    await db_session.flush()

    # The counter still believes #1 is free, and hands it out.
    assert await next_ticket_number(db_session, ws.id) == 1

    # Resyncing is what the migration does, and it steps clear of the row above.
    highest = (
        await db_session.execute(
            select(Ticket.ticket_number).where(Ticket.workspace_id == ws.id)
        )
    ).scalars().all()
    ws.next_ticket_number = max(max(highest) + 1, ws.next_ticket_number)
    await db_session.flush()

    assert await next_ticket_number(db_session, ws.id) == 8


@pytest.mark.asyncio
async def test_unknown_workspace_is_an_error_not_a_number(
    db_session: AsyncSession,
):
    with pytest.raises(ValueError):
        await next_ticket_number(db_session, str(uuid.uuid4()))


def test_no_creation_path_counts_its_own_numbers():
    """The regression guard: `MAX(ticket_number) + 1` must not come back.

    Five services create tickets. A new one that counts instead of allocating
    would not fail any test above — it would quietly desynchronise the counter
    and break the public form later, somewhere else entirely.
    """
    from aexy.services import (
        alert_ingestion_service,
        form_submission_handler,
        service_desk_intake_service,
        ticket_service,
        uptime_service,
    )

    for module in (
        alert_ingestion_service,
        form_submission_handler,
        service_desk_intake_service,
        ticket_service,
        uptime_service,
    ):
        source = inspect.getsource(module)
        assert "max(Ticket.ticket_number)" not in source, (
            f"{module.__name__} counts ticket numbers instead of calling "
            "ticket_numbering.next_ticket_number"
        )

"""Reuniting a stray stakeholder email with its ticket, when AI is enabled.

Deterministic matching (Gmail thread, then the BSD number in the subject) is the
only path with AI off. With AI on, a stakeholder who starts a fresh thread and
drops the ticket number can still be reunited — but only on a confident, single
candidate from a sender already known to master data. Everything less certain
opens a new ticket and asks a human, because attaching one claim's mail to
another partner's ticket is worse than one extra ticket.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.service_desk import (
    ServiceDeskInsurer,
    ServiceDeskInsurerDomain,
    ServiceDeskMailbox,
    ServiceDeskTicket,
)
from aexy.models.ticketing import Ticket, TicketForm, TicketResponse
from aexy.models.workspace import Workspace
from aexy.schemas.service_desk import InboundEmail
from aexy.services.service_desk_intake_service import ServiceDeskIntakeService


def _gateway(monkeypatch, payload: str, seen: list | None = None):
    class Gateway:
        async def call_llm(self, system, user, **kwargs):
            if seen is not None:
                seen.append(user)
            return (payload,)

    monkeypatch.setattr("aexy.llm.gateway.get_llm_gateway", lambda: Gateway())


@pytest.fixture
async def desk(db_session: AsyncSession):
    """AI-enabled workspace, a known insurer, and one open ticket with them."""
    owner = Developer(id=str(uuid4()), email=f"o-{uuid4().hex[:6]}@bimaplan.co", name="Owner")
    db_session.add(owner)
    await db_session.flush()
    ws = Workspace(id=str(uuid4()), name="BP", slug=f"bp-{uuid4().hex[:6]}", owner_id=owner.id)
    ws.settings = {"service_desk": {"ai_classification_enabled": True}}
    db_session.add(ws)
    await db_session.flush()

    mailbox = ServiceDeskMailbox(
        id=str(uuid4()), workspace_id=ws.id, address="ops@bimaplan.co", channel="webhook"
    )
    db_session.add(mailbox)
    insurer = ServiceDeskInsurer(id=str(uuid4()), workspace_id=ws.id, name="Insurer I1")
    db_session.add(insurer)
    await db_session.flush()
    db_session.add(
        ServiceDeskInsurerDomain(
            id=str(uuid4()), workspace_id=ws.id, insurer_id=insurer.id, domain="claims@i1.example"
        )
    )

    form = TicketForm(
        id=str(uuid4()), workspace_id=ws.id, name="SD", slug="service-desk", created_by_id=owner.id
    )
    db_session.add(form)
    await db_session.flush()
    ticket = Ticket(
        id=str(uuid4()),
        workspace_id=ws.id,
        form_id=form.id,
        ticket_number=7,
        submitter_email="rahul@partner.example",
        field_values={"subject": "Claim C-9 status", "body": "..."},
        status="new",
        source="service_desk_gmail",
    )
    db_session.add(ticket)
    await db_session.flush()
    db_session.add(
        ServiceDeskTicket(
            id=str(uuid4()),
            workspace_id=ws.id,
            ticket_id=ticket.id,
            insurer_id=insurer.id,
            request_type="claims",
            pending_with="insurer",
            origin="email",
            mailbox_id=mailbox.id,
            thread_ref="thread-original",
        )
    )
    await db_session.commit()
    return {"ws": ws, "mailbox": mailbox, "ticket": ticket}


def _stray(**over) -> InboundEmail:
    """A fresh thread from the insurer with no ticket number anywhere."""
    base = {
        "to": "ops@bimaplan.co",
        "from_email": "claims@i1.example",
        "subject": "Update on the C-9 matter",
        "body_text": "We have approved the claim discussed earlier.",
        "message_id": f"m-{uuid4().hex[:8]}",
        "thread_id": f"t-{uuid4().hex[:8]}",
    }
    base.update(over)
    return InboundEmail(**base)


@pytest.mark.asyncio
async def test_a_confident_single_match_merges_and_says_why(db_session, desk, monkeypatch):
    _gateway(monkeypatch, '{"ticket":"BSD-7","confidence":0.93,"reason":"Same claim C-9"}')

    result = await ServiceDeskIntakeService(db_session).ingest(
        _stray(), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()

    assert result.id == desk["ticket"].id
    tickets = (await db_session.execute(select(Ticket))).scalars().all()
    assert len(tickets) == 1, "a confident match must not also open a ticket"

    notes = (
        await db_session.execute(
            select(TicketResponse).where(TicketResponse.ticket_id == desk["ticket"].id)
        )
    ).scalars().all()
    merge_note = [n for n in notes if n.is_internal and "Matched to this ticket by AI" in n.content]
    assert len(merge_note) == 1
    assert "93%" in merge_note[0].content
    assert "Same claim C-9" in merge_note[0].content
    # The email body itself is still stored as external correspondence.
    assert any(not n.is_internal for n in notes)


@pytest.mark.asyncio
async def test_an_unsure_match_opens_a_ticket_and_asks_a_human(db_session, desk, monkeypatch):
    _gateway(monkeypatch, '{"ticket":"BSD-7","confidence":0.55,"reason":"Wording is similar"}')

    result = await ServiceDeskIntakeService(db_session).ingest(
        _stray(), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()

    assert result.id != desk["ticket"].id, "an unsure match must never merge"
    sd = (
        await db_session.execute(
            select(ServiceDeskTicket).where(ServiceDeskTicket.ticket_id == result.id)
        )
    ).scalar_one()
    assert sd.needs_triage is True

    notes = (
        await db_session.execute(
            select(TicketResponse).where(TicketResponse.ticket_id == result.id)
        )
    ).scalars().all()
    hint = [n for n in notes if n.is_internal and "may belong to BSD-7" in n.content]
    assert len(hint) == 1, "the near miss must be recorded, not silently dropped"
    assert "A human should confirm" in hint[0].content


@pytest.mark.asyncio
async def test_an_unknown_sender_is_never_merged(db_session, desk, monkeypatch):
    """Master data membership is the gate; a stranger cannot reach a claim."""
    called: list = []
    _gateway(monkeypatch, '{"ticket":"BSD-7","confidence":0.99,"reason":"x"}', seen=called)

    result = await ServiceDeskIntakeService(db_session).ingest(
        _stray(from_email="someone@nowhere.example"), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()

    assert result.id != desk["ticket"].id
    # Classification still runs on the new ticket; the *matcher* must not. Its
    # prompt is the only one that lists candidate tickets.
    assert not any("Open tickets for this company" in prompt for prompt in called)


@pytest.mark.asyncio
async def test_a_ticket_the_model_invented_is_ignored(db_session, desk, monkeypatch):
    """Only a candidate we actually offered may be chosen."""
    _gateway(monkeypatch, '{"ticket":"BSD-999","confidence":0.99,"reason":"made up"}')

    result = await ServiceDeskIntakeService(db_session).ingest(
        _stray(), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()
    assert result.id != desk["ticket"].id


@pytest.mark.asyncio
async def test_the_deterministic_paths_still_win_before_any_model_runs(
    db_session, desk, monkeypatch
):
    """A subject carrying the ticket number never reaches the model."""
    called: list = []
    _gateway(monkeypatch, '{"ticket":null,"confidence":0,"reason":"x"}', seen=called)

    result = await ServiceDeskIntakeService(db_session).ingest(
        _stray(subject="Re: BSD-7 claim update"), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()

    assert result.id == desk["ticket"].id
    assert not any("Open tickets for this company" in prompt for prompt in called)


# ----------------------------------------- a reply hands the ticket back


def _reply_from(sender: str, **over) -> InboundEmail:
    base = {
        "to": "ops@bimaplan.co",
        "from_email": sender,
        "subject": "Re: BSD-7 claim update",
        "body_text": "Still checking, will confirm tomorrow.",
        "message_id": f"m-{uuid4().hex[:8]}",
        "thread_id": "thread-original",
    }
    base.update(over)
    return InboundEmail(**base)


async def _stage(db, ticket_id: str) -> str:
    sd = (
        await db.execute(
            select(ServiceDeskTicket).where(ServiceDeskTicket.ticket_id == ticket_id)
        )
    ).scalar_one()
    return sd.pending_with


@pytest.mark.asyncio
async def test_a_reply_from_the_stakeholder_we_await_hands_it_back_to_the_kam(
    db_session, desk
):
    """A holding reply is still a reply: a human has to read it and decide."""
    await ServiceDeskIntakeService(db_session).ingest(
        _reply_from("claims@i1.example"), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()

    assert await _stage(db_session, desk["ticket"].id) == "kam"
    notes = (
        await db_session.execute(
            select(TicketResponse).where(TicketResponse.ticket_id == desk["ticket"].id)
        )
    ).scalars().all()
    assert any("Reply received from Insurer I1" in n.content for n in notes if n.is_internal)


@pytest.mark.asyncio
async def test_someone_else_chasing_does_not_let_the_insurer_off_the_hook(db_session, desk):
    """The insurer still owes an answer, so the ticket stays with the insurer."""
    await ServiceDeskIntakeService(db_session).ingest(
        _reply_from("rahul@partner.example"), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()

    assert await _stage(db_session, desk["ticket"].id) == "insurer"


@pytest.mark.asyncio
async def test_an_internal_queue_is_never_emptied_by_an_external_reply(db_session, desk):
    """Finance replying is not the same as Finance having finished."""
    sd = (
        await db_session.execute(
            select(ServiceDeskTicket).where(ServiceDeskTicket.ticket_id == desk["ticket"].id)
        )
    ).scalar_one()
    sd.pending_with = "finance"
    await db_session.commit()

    await ServiceDeskIntakeService(db_session).ingest(
        _reply_from("claims@i1.example"), desk["mailbox"], "service_desk_gmail"
    )
    await db_session.commit()

    assert await _stage(db_session, desk["ticket"].id) == "finance"

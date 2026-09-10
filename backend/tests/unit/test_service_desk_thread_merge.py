"""A ticket is not a Gmail conversation.

Reported with two real tickets: SD-256 (a Sep-26 booking run for EHF GHI) had
absorbed a COI recon sheet from a 31 Aug chain, and SD-200 (an API onboarding
question to one colleague) had absorbed a demo-call follow-up with portal
credentials to somebody else.

Neither was an AI match. ``_find_thread_ticket`` trusted the provider's thread id
with no other predicate at all — and Gmail's ``threadId`` is a *conversation*:
grouped partly by subject, running for months, indifferent to topic. On this desk
258 of 314 tickets come from colleagues who keep one rolling chain per partner
and raise whatever comes up inside it, so an unqualified match collapsed
unrelated requests into one ticket with one clock, one classification and one
closure.

Two conditions now qualify it, and both fail *towards a new ticket* — wrongly
rejecting a continuation opens a spare ticket somebody can merge, wrongly
accepting one buries a request where nobody will find it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.service_desk import ServiceDeskMailbox, ServiceDeskTicket
from aexy.models.ticketing import Ticket, TicketForm, TicketResponse
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import InboundEmail
from aexy.services.service_desk_config import normalise_subject
from aexy.services.service_desk_intake_service import ServiceDeskIntakeService
from tests.conftest import seed_service_desk_taxonomy

DESK = "ops@desk.example"
THREAD = "gmail-thread-0001"
SUBJECT = "EHF Onboarding"


class _Desk:
    ws: Workspace
    mailbox: ServiceDeskMailbox
    ticket: Ticket
    form: TicketForm


async def _desk(db: AsyncSession, slug: str, *, subject: str = SUBJECT) -> _Desk:
    d = _Desk()
    owner = Developer(id=str(uuid4()), email=f"owner-{slug}@d.example", name="Owner")
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
        ticket_number=200,
        title=subject,
        submitter_email="paramita@d.example",
        status="new",
        field_values={"subject": subject},
    )
    db.add(d.ticket)
    await db.flush()
    db.add(
        ServiceDeskTicket(
            id=str(uuid4()),
            workspace_id=d.ws.id,
            ticket_id=d.ticket.id,
            mailbox_id=d.mailbox.id,
            request_type="query",
            pending_with="kam",
            origin="internal",
            thread_ref=THREAD,
        )
    )
    await seed_service_desk_taxonomy(db, d.ws.id)
    await db.commit()
    return d


def _mail(subject: str, *, thread: str | None = THREAD, sent_at=None) -> InboundEmail:
    return InboundEmail(
        to=DESK,
        from_email="paramita@d.example",
        subject=subject,
        body_text="…",
        thread_id=thread,
        sent_at=sent_at,
        message_id=f"<{uuid4().hex}@d.example>",
    )


# ------------------------------------------------------------ subject normalising


def test_reply_and_forward_markers_come_off() -> None:
    assert normalise_subject("Re: EHF Onboarding") == "ehf onboarding"
    assert normalise_subject("Fwd: Re: EHF Onboarding") == "ehf onboarding"
    assert normalise_subject("RE: [EXTERNAL] EHF Onboarding") == "ehf onboarding"
    # Outlook's numbered form.
    assert normalise_subject("Re[2]: EHF Onboarding") == "ehf onboarding"


def test_punctuation_and_digits_are_kept() -> None:
    """A real desk subject differs from its siblings only in these.

    ``"Easy Home Finance GHI || 1 - 3 Sep'26"`` and the same partner's next run
    are the same words and different dates — stripping punctuation would make
    them compare equal, which is the bug this check exists to catch.
    """
    a = normalise_subject("Easy Home Finance GHI || 1 - 3 Sep'26")
    b = normalise_subject("Easy Home Finance GHI || 4 - 6 Sep'26")
    assert a != b
    assert a == "easy home finance ghi || 1 - 3 sep'26"


def test_case_and_whitespace_do_not_matter() -> None:
    assert normalise_subject("  EHF   ONBOARDING ") == normalise_subject("ehf onboarding")


def test_nothing_is_empty_not_an_error() -> None:
    assert normalise_subject(None) == ""
    assert normalise_subject("") == ""


# --------------------------------------------------------------- the matcher


@pytest.mark.asyncio
async def test_a_genuine_reply_still_appends(db_session: AsyncSession) -> None:
    """The behaviour being protected, asserted first."""
    d = await _desk(db_session, "tm-reply")

    found, note = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id, _mail("Re: EHF Onboarding")
    )

    assert found is not None
    assert found.id == d.ticket.id
    # And it says so, which a thread-id match never used to.
    assert note is not None
    assert "same email conversation" in note


@pytest.mark.asyncio
async def test_a_new_topic_in_the_same_chain_opens_its_own_ticket(
    db_session: AsyncSession,
) -> None:
    """The reported bug. Same Gmail conversation, different request."""
    d = await _desk(db_session, "tm-newtopic")

    found, note = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id, _mail("Easy Home Finance GHI || 1 - 3 Sep'26")
    )

    assert found is None
    assert note is None


@pytest.mark.asyncio
async def test_the_ticket_id_in_the_subject_beats_everything(
    db_session: AsyncSession,
) -> None:
    """The desk stamps ``[SD-n]`` into every subject it sends.

    A reply carrying one has told us the answer, so neither subject agreement nor
    staleness is consulted — including when the subject has been rewritten
    entirely, which is what a person forwarding a ticket does.
    """
    d = await _desk(db_session, "tm-byid")

    found, note = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id,
        _mail("SD-200 — completely different words", thread="some-other-thread"),
    )

    assert found is not None
    assert found.id == d.ticket.id
    # No note: an ordinary reply on the designed path is not worth annotating,
    # and a note on every one would bury the ones that matter.
    assert note is None


@pytest.mark.asyncio
async def test_a_chain_revived_after_the_cutoff_opens_its_own_ticket(
    db_session: AsyncSession,
) -> None:
    """Even with the subject matching, a months-old conversation is new work."""
    d = await _desk(db_session, "tm-stale")
    d.ticket.updated_at = datetime.now(timezone.utc) - timedelta(days=120)
    await db_session.commit()

    found, _ = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id, _mail("Re: EHF Onboarding", sent_at=datetime.now(timezone.utc))
    )

    assert found is None


@pytest.mark.asyncio
async def test_a_recent_chain_with_a_matching_subject_is_accepted(
    db_session: AsyncSession,
) -> None:
    """The other side of the window — a reply two days later is a reply."""
    d = await _desk(db_session, "tm-fresh")
    d.ticket.updated_at = datetime.now(timezone.utc) - timedelta(days=2)
    await db_session.commit()

    found, _ = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id, _mail("Re: EHF Onboarding", sent_at=datetime.now(timezone.utc))
    )

    assert found is not None


@pytest.mark.asyncio
async def test_an_unrelated_thread_id_matches_nothing(
    db_session: AsyncSession,
) -> None:
    d = await _desk(db_session, "tm-unknown")

    found, _ = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id, _mail("Re: EHF Onboarding", thread="not-a-thread-we-know")
    )

    assert found is None


@pytest.mark.asyncio
async def test_a_merge_is_written_to_the_timeline(db_session: AsyncSession) -> None:
    """The whole ingest path, so the note actually lands on the ticket.

    A thread-id match recorded nothing at all, so a ticket that had absorbed
    somebody else's request could not be explained from the ticket. Combined
    with internal notes being filtered out of the detail view, the merge was
    both silent and unexplainable.
    """
    d = await _desk(db_session, "tm-noted")

    ticket = await ServiceDeskIntakeService(db_session).ingest(
        _mail("Re: EHF Onboarding"), d.mailbox, source="test"
    )
    await db_session.commit()

    assert ticket is not None
    assert ticket.id == d.ticket.id

    notes = (
        await db_session.execute(
            __import__("sqlalchemy").select(TicketResponse.content).where(
                TicketResponse.ticket_id == d.ticket.id,
                TicketResponse.is_internal.is_(True),
            )
        )
    ).scalars().all()
    assert any("same email conversation" in (n or "") for n in notes)


@pytest.mark.asyncio
async def test_a_ticket_with_no_subject_does_not_absorb_the_conversation(
    db_session: AsyncSession,
) -> None:
    """"Nothing to agree with" is not agreement.

    The check used to be skipped when the ticket had neither a title nor a
    stored subject, so any topic in that Gmail conversation was accepted — the
    unsafe direction, on the tickets least able to show it had happened.
    """
    d = await _desk(db_session, "tm-nosubject", subject="")
    d.ticket.title = None
    d.ticket.field_values = {}
    await db_session.commit()

    found, _ = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id, _mail("A completely unrelated request")
    )

    assert found is None


@pytest.mark.asyncio
async def test_a_machine_reply_is_not_asked_to_match_the_subject(
    db_session: AsyncSession,
) -> None:
    """An out-of-office belongs on the thread it is answering.

    Its subject is chosen by the sender's mail system — "Automatic reply: …",
    "Delivery Status Notification (Failure)" — so subject agreement is the wrong
    question to ask of it. Asking anyway opened a fresh ticket for every
    auto-reply, which is the opposite of the intended behaviour: such a message
    is kept as correspondence and must not reopen or duplicate anything.

    The topic-drift this guard exists for is a *person* raising something new in
    an old chain.
    """
    d = await _desk(db_session, "tm-auto-subject")

    found, note = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id,
        _mail("Automatic reply: I am out of the office"),
        automatic=True,
    )

    assert found is not None
    assert found.id == d.ticket.id
    # And no note: annotating every auto-reply would bury the merges that matter.
    assert note is None


@pytest.mark.asyncio
async def test_a_person_is_still_asked_to_match_the_subject(
    db_session: AsyncSession,
) -> None:
    """The same message from a person, on the same thread, is still refused."""
    d = await _desk(db_session, "tm-human-subject")

    found, _ = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id,
        _mail("Automatic reply: I am out of the office"),
        automatic=False,
    )

    assert found is None


@pytest.mark.asyncio
async def test_staleness_still_applies_to_machine_mail(
    db_session: AsyncSession,
) -> None:
    """Only the subject check is waived, not the cut-off.

    A bounce arrives seconds after the send that failed, so this never fires in
    practice — but a stray notice against a conversation nobody has touched for
    months is noise, not correspondence.
    """
    d = await _desk(db_session, "tm-auto-stale")
    d.ticket.updated_at = datetime.now(timezone.utc) - timedelta(days=200)
    await db_session.commit()

    found, _ = await ServiceDeskIntakeService(db_session)._find_thread_ticket(
        d.ws.id,
        _mail("Automatic reply: out of office", sent_at=datetime.now(timezone.utc)),
        automatic=True,
    )

    assert found is None

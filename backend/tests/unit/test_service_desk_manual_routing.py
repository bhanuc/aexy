"""Routing a ticket to the partner's own KAM.

Reported by the ops head: "assignment based on Partner in Master Data is not
working — I have to move every ticket to the right KAM by hand."

Two distinct causes, both pinned here.

1. A *manual* ticket is created through intake, which decides the owner from the
   sender address. For a logged call that address is the literal
   ``manual@local``, so it matched no account and fell through to an arbitrary
   member of the desk. The account the operator picked in the dialog was applied
   afterwards and never touched the assignee — so choosing the partner did
   nothing at all.

2. When nothing matches, the desk now gets to say what should happen instead of
   always being handed a random owner, which is the option that hid the problem:
   an arbitrary assignment is indistinguishable from a deliberate one.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.organization import Department, DepartmentMember
from aexy.models.service_desk import (
    ServiceDeskAccount,
    ServiceDeskAccountDomain,
    ServiceDeskAccountProduct,
    ServiceDeskMailbox,
    ServiceDeskProduct,
)
from aexy.models.ticketing import Ticket, TicketResponse
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import InboundEmail, ManualTicketCreate
from aexy.services.service_desk_config import unmatched_assignment
from aexy.services.service_desk_intake_service import ServiceDeskIntakeService
from aexy.services.service_desk_service import ServiceDeskService
from tests.conftest import seed_service_desk_taxonomy


class _Desk:
    ws: Workspace
    mailbox: ServiceDeskMailbox
    ws_owner: Developer
    kam: Developer
    motor_kam: Developer
    desk_member: Developer
    head: Developer
    department: Department
    account: ServiceDeskAccount
    motor: ServiceDeskProduct


async def _member(db: AsyncSession, ws: Workspace, dev: Developer) -> None:
    db.add(
        WorkspaceMember(
            id=str(uuid4()), workspace_id=ws.id, developer_id=dev.id, role="member"
        )
    )


async def _desk(db: AsyncSession, slug: str, *, sd_settings: dict | None = None) -> _Desk:
    d = _Desk()
    d.ws_owner = Developer(id=str(uuid4()), email=f"wsowner-{slug}@desk.example", name="WS Owner")
    d.kam = Developer(id=str(uuid4()), email=f"kam-{slug}@desk.example", name="Partner KAM")
    d.motor_kam = Developer(id=str(uuid4()), email=f"motor-{slug}@desk.example", name="Motor KAM")
    d.desk_member = Developer(id=str(uuid4()), email=f"desk-{slug}@desk.example", name="Desk Member")
    d.head = Developer(id=str(uuid4()), email=f"head-{slug}@desk.example", name="Desk Head")
    db.add_all([d.ws_owner, d.kam, d.motor_kam, d.desk_member, d.head])
    await db.flush()

    d.ws = Workspace(
        id=str(uuid4()), name=f"WS {slug}", slug=slug, owner_id=d.ws_owner.id,
        settings={"service_desk": sd_settings} if sd_settings else {},
    )
    db.add(d.ws)
    await db.flush()
    for dev in (d.kam, d.motor_kam, d.desk_member, d.head):
        await _member(db, d.ws, dev)

    # The department that runs the desk. `_random_owner` picks from its active
    # members, so `desk_member` is the only candidate for a random fallback and
    # the assertions below can tell the fallback apart from a real answer.
    d.department = Department(
        id=str(uuid4()), workspace_id=d.ws.id, name="Operations", slug=f"ops-{slug}",
        function_key="operations", head_id=d.head.id,
    )
    db.add(d.department)
    await db.flush()
    db.add(
        DepartmentMember(
            id=str(uuid4()), workspace_id=d.ws.id, department_id=d.department.id,
            developer_id=d.desk_member.id,
        )
    )

    d.mailbox = ServiceDeskMailbox(
        id=str(uuid4()), workspace_id=d.ws.id, address="ops@desk.example", channel="webhook"
    )
    d.motor = ServiceDeskProduct(id=str(uuid4()), workspace_id=d.ws.id, name="Motor")
    d.account = ServiceDeskAccount(
        id=str(uuid4()), workspace_id=d.ws.id, name="Partner Co",
        assigned_owner_id=d.kam.id,
    )
    db.add_all([d.mailbox, d.motor, d.account])
    await db.flush()
    db.add(
        ServiceDeskAccountDomain(
            id=str(uuid4()), workspace_id=d.ws.id, account_id=d.account.id,
            domain="partner.example",
        )
    )
    await db.commit()

    settings = dict(d.ws.settings or {})
    settings["service_desk"] = {
        **(settings.get("service_desk") or {}),
        "desk_department_id": d.department.id,
    }
    d.ws.settings = settings
    await db.commit()

    await seed_service_desk_taxonomy(db, d.ws.id)
    return d


async def _ticket(db: AsyncSession, ticket_id: str) -> Ticket:
    return (await db.execute(select(Ticket).where(Ticket.id == ticket_id))).scalar_one()


async def _notes(db: AsyncSession, ticket_id: str) -> str:
    rows = (
        await db.execute(
            select(TicketResponse.content).where(TicketResponse.ticket_id == ticket_id)
        )
    ).scalars().all()
    return "\n".join(r or "" for r in rows)


# ── 1. the manual path honours the partner the operator picked ───────────


@pytest.mark.asyncio
async def test_logging_a_call_for_a_partner_reaches_that_partners_kam(
    db_session: AsyncSession,
) -> None:
    """The ops head's report, as a test.

    Nothing about `manual@local` can identify the partner, so before this the
    ticket went to whoever `_random_owner` happened to pick — and the account
    dropdown the operator had just used was applied to the ticket without ever
    reaching the assignee.
    """
    d = await _desk(db_session, "mr-partner")

    ticket_id = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id,
        ManualTicketCreate(subject="Partner rang about a renewal", account_id=d.account.id),
    )

    ticket = await _ticket(db_session, ticket_id)
    assert str(ticket.assignee_id) == str(d.kam.id), (
        "a manual ticket naming a partner must reach that partner's KAM"
    )


@pytest.mark.asyncio
async def test_the_product_pairing_beats_the_account_owner(
    db_session: AsyncSession,
) -> None:
    """The narrowest answer the desk has recorded wins."""
    d = await _desk(db_session, "mr-product")
    db_session.add(
        ServiceDeskAccountProduct(
            id=str(uuid4()), workspace_id=d.ws.id, account_id=d.account.id,
            product_id=d.motor.id, assigned_owner_id=d.motor_kam.id,
        )
    )
    await db_session.commit()

    ticket_id = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id,
        ManualTicketCreate(
            subject="Motor claim", account_id=d.account.id, product_id=d.motor.id
        ),
    )

    ticket = await _ticket(db_session, ticket_id)
    assert str(ticket.assignee_id) == str(d.motor_kam.id)


@pytest.mark.asyncio
async def test_a_pairing_with_no_owner_falls_back_to_the_account_owner(
    db_session: AsyncSession,
) -> None:
    """A product row exists but names nobody — the account's owner still answers."""
    d = await _desk(db_session, "mr-pair-empty")
    db_session.add(
        ServiceDeskAccountProduct(
            id=str(uuid4()), workspace_id=d.ws.id, account_id=d.account.id,
            product_id=d.motor.id, assigned_owner_id=None,
        )
    )
    await db_session.commit()

    ticket_id = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id,
        ManualTicketCreate(
            subject="Motor query", account_id=d.account.id, product_id=d.motor.id
        ),
    )
    ticket = await _ticket(db_session, ticket_id)
    assert str(ticket.assignee_id) == str(d.kam.id)


@pytest.mark.asyncio
async def test_an_unowned_partner_says_so_on_the_ticket(
    db_session: AsyncSession,
) -> None:
    """The assignee is still arbitrary here, and that is the case most in need of
    an explanation — it is indistinguishable from a deliberate assignment."""
    d = await _desk(db_session, "mr-unowned")
    d.account.assigned_owner_id = None
    await db_session.commit()

    ticket_id = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id,
        ManualTicketCreate(subject="Unowned partner rang", account_id=d.account.id),
    )

    notes = await _notes(db_session, ticket_id)
    assert "no assigned owner in Master Data" in notes
    assert "Partner Co" in notes


@pytest.mark.asyncio
async def test_no_partner_picked_leaves_the_intake_owner_alone(
    db_session: AsyncSession,
) -> None:
    """Nothing to route on, so nothing to override — and no note claiming a
    mapping problem that doesn't exist.

    Pinned to the pool: this test is about the *override* not firing, and the
    owner it lands on is incidental. Left on the default it would assert against
    whichever policy ships, which is a different question.
    """
    d = await _desk(
        db_session, "mr-noaccount", sd_settings={"unmatched_assignment": "random"}
    )

    ticket_id = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id, ManualTicketCreate(subject="Walk-in, partner unknown")
    )

    ticket = await _ticket(db_session, ticket_id)
    assert str(ticket.assignee_id) == str(d.desk_member.id)
    assert "no assigned owner in Master Data" not in await _notes(db_session, ticket_id)


# ── 2. what happens when nothing matches is the desk's choice ────────────


def test_the_default_is_the_accountable_owner() -> None:
    """Changed deliberately from "random", which was kept only so no desk
    changed on upgrade — the wrong thing to optimise for.

    Random assignment does not merely pick badly, it hides the picking: an
    arbitrary assignment is indistinguishable from a deliberate one. And where
    row visibility follows assignment, the coin toss decides who can *see* the
    ticket, so a wrong guess hides it rather than mislabelling it.
    """
    assert unmatched_assignment({}) == "desk_head"


def test_an_unrecognised_stored_value_does_not_break_intake() -> None:
    """Read on the mail path; refusing to route because a settings blob is odd
    would drop tickets on the floor."""
    assert unmatched_assignment({"unmatched_assignment": "nonsense"}) == "desk_head"


@pytest.mark.asyncio
async def test_unknown_sender_can_be_left_unassigned(db_session: AsyncSession) -> None:
    """With the policy set to "unassigned", an unroutable ticket stays visibly
    waiting — and must NOT be quietly handed to the workspace owner by the
    last-ditch fallback, which would undo the setting."""
    d = await _desk(
        db_session, "mr-unassigned", sd_settings={"unmatched_assignment": "unassigned"}
    )
    intake = ServiceDeskIntakeService(db_session)

    ticket = await intake.create_ticket(
        d.ws.id,
        InboundEmail(
            to="ops@desk.example", from_email="stranger@nobody.example",
            subject="Who are we?", body_text="hello",
        ),
        d.mailbox,
        source="service_desk_email",
    )
    await db_session.commit()

    assert ticket.assignee_id is None
    assert str(ticket.assignee_id or "") != str(d.ws_owner.id)
    notes = await _notes(db_session, ticket.id)
    assert "unassigned" in notes.lower()


@pytest.mark.asyncio
async def test_unknown_sender_can_go_to_the_desk_head(db_session: AsyncSession) -> None:
    d = await _desk(
        db_session, "mr-head", sd_settings={"unmatched_assignment": "desk_head"}
    )
    intake = ServiceDeskIntakeService(db_session)

    ticket = await intake.create_ticket(
        d.ws.id,
        InboundEmail(
            to="ops@desk.example", from_email="stranger@nobody.example",
            subject="Who are we?", body_text="hello",
        ),
        d.mailbox,
        source="service_desk_email",
    )
    await db_session.commit()

    assert str(ticket.assignee_id) == str(d.head.id)


@pytest.mark.asyncio
async def test_a_known_partner_is_unaffected_by_the_policy(
    db_session: AsyncSession,
) -> None:
    """The policy governs the *unmatched* case only. A matching domain must still
    reach its KAM whatever it is set to."""
    d = await _desk(
        db_session, "mr-known", sd_settings={"unmatched_assignment": "unassigned"}
    )
    intake = ServiceDeskIntakeService(db_session)

    ticket = await intake.create_ticket(
        d.ws.id,
        InboundEmail(
            to="ops@desk.example", from_email="someone@partner.example",
            subject="Renewal", body_text="hello",
        ),
        d.mailbox,
        source="service_desk_email",
    )
    await db_session.commit()

    assert str(ticket.assignee_id) == str(d.kam.id)


# ── 4. the operator keeps the ticket they logged ─────────────────────────


@pytest.mark.asyncio
async def test_whoever_logged_the_call_can_still_see_it(
    db_session: AsyncSession,
) -> None:
    """Reported as "Ticket logged, but finishing up failed: Ticket not found".

    Logging a call assigns the owner from Master Data, which is usually somebody
    else — and row visibility follows assignment, so the operator lost the ticket
    the instant it existed. The attachment upload is a second, scope-checked
    request, and it 404'd against the ticket the same person had just created:
    the file was silently left behind and the message named no ticket to open.
    """
    from aexy.services.service_desk_service import (
        can_edit_ticket,
        is_service_desk_ticket_visible,
    )

    d = await _desk(db_session, "mr-logger")
    # The operator is not the owner and holds no queue — the shape that broke.
    operator = Developer(
        id=str(uuid4()), email=f"operator-{uuid4().hex[:6]}@desk.example", name="Operator"
    )
    db_session.add(operator)
    await db_session.flush()
    await _member(db_session, d.ws, operator)
    await db_session.commit()

    ticket_id = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id,
        ManualTicketCreate(subject="Walk-in", account_id=d.account.id),
        logged_by_id=operator.id,
    )
    await db_session.commit()

    ticket = await _ticket(db_session, ticket_id)
    # Assignment is unchanged: Master Data still decides the owner.
    assert str(ticket.assignee_id) == str(d.kam.id)
    assert str(ticket.assignee_id) != str(operator.id)

    # But the operator can reach it, which is what the upload needed.
    assert await is_service_desk_ticket_visible(
        db_session, d.ws.id, ticket_id, str(operator.id)
    )
    assert await can_edit_ticket(
        db_session,
        d.ws.id,
        str(operator.id),
        assignee_id=ticket.assignee_id,
        pending_with="kam",
        logged_by_id=(ticket.field_values or {}).get("logged_by_id"),
    )


@pytest.mark.asyncio
async def test_logging_a_call_does_not_widen_anything_else(
    db_session: AsyncSession,
) -> None:
    """The clause admits exactly one ticket, not a queue.

    `logged_by_id` is stamped only by the manual path, so an email ticket — which
    has no such field — stays as restricted as it was.
    """
    from aexy.services.service_desk_service import is_service_desk_ticket_visible

    d = await _desk(db_session, "mr-logger-narrow")
    operator = Developer(
        id=str(uuid4()), email=f"op2-{uuid4().hex[:6]}@desk.example", name="Operator"
    )
    db_session.add(operator)
    await db_session.flush()
    await _member(db_session, d.ws, operator)
    await db_session.commit()

    mine = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id, ManualTicketCreate(subject="Mine"), logged_by_id=operator.id
    )
    theirs = await ServiceDeskService(db_session).create_manual_ticket(
        d.ws.id, ManualTicketCreate(subject="Somebody else's"), logged_by_id=d.kam.id
    )
    await db_session.commit()

    assert await is_service_desk_ticket_visible(db_session, d.ws.id, mine, str(operator.id))
    assert not await is_service_desk_ticket_visible(
        db_session, d.ws.id, theirs, str(operator.id)
    )

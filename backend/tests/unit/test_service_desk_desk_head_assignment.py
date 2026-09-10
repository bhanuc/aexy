"""Unmatched tickets go to the operations head, and never to a random person.

Asked for directly: "do not randomly assign people — it should go to operations
head". Three things stood between the setting and that behaviour.

1. The default was ``"random"``, kept so no workspace changed on upgrade. Random
   assignment does not merely pick badly, it *hides* the picking: an arbitrary
   assignment is indistinguishable from a deliberate one, and on a desk whose row
   visibility follows assignment the coin toss also decides who can see the
   ticket at all.

2. "Head of a department" is stored in two places that were never wired
   together — ``Department.head_id``, and the ``head`` membership role that the
   Organization → Departments screen actually writes. Reading only the column
   meant the Bimaplan desk, which plainly shows Chandan Tyagi as Head of
   Operations, resolved to no head at all.

3. With no head resolved, ``desk_head`` fell back to ``_random_owner`` — so a
   desk that had explicitly asked for one accountable owner was still
   distributing tickets by coin toss, and the only trace was a note nobody reads
   until they are already asking why.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.organization import Department, DepartmentMember, DepartmentMemberRole
from aexy.models.service_desk import ServiceDeskMailbox
from aexy.models.ticketing import Ticket
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import InboundEmail
from aexy.services.service_desk_config import unmatched_assignment
from aexy.services.service_desk_intake_service import ServiceDeskIntakeService
from aexy.services.service_desk_service import resolve_desk_head_id
from tests.conftest import seed_service_desk_taxonomy


class _Desk:
    ws: Workspace
    mailbox: ServiceDeskMailbox
    owner: Developer
    head: Developer
    grunt: Developer
    department: Department


async def _desk(
    db: AsyncSession,
    slug: str,
    *,
    sd_settings: dict | None = None,
    head_via_column: bool = False,
    head_via_role: bool = False,
) -> _Desk:
    """A desk whose Operations department records its head in neither, one, or both places."""
    d = _Desk()
    d.owner = Developer(id=str(uuid4()), email=f"owner-{slug}@d.example", name="WS Owner")
    d.head = Developer(id=str(uuid4()), email=f"head-{slug}@d.example", name="Ops Head")
    d.grunt = Developer(id=str(uuid4()), email=f"grunt-{slug}@d.example", name="Desk Member")
    db.add_all([d.owner, d.head, d.grunt])
    await db.flush()

    d.ws = Workspace(
        id=str(uuid4()), name=f"WS {slug}", slug=slug, owner_id=d.owner.id,
        settings={"service_desk": sd_settings} if sd_settings else {},
    )
    db.add(d.ws)
    await db.flush()
    for dev in (d.owner, d.head, d.grunt):
        db.add(
            WorkspaceMember(
                id=str(uuid4()), workspace_id=d.ws.id, developer_id=dev.id, role="member"
            )
        )

    d.department = Department(
        id=str(uuid4()), workspace_id=d.ws.id, name="Operations", slug=f"ops-{slug}",
        function_key="operations",
        head_id=d.head.id if head_via_column else None,
    )
    db.add(d.department)
    await db.flush()

    # The head is a member either way — being head of a department you are not in
    # is not a state the org chart can produce.
    db.add(
        DepartmentMember(
            id=str(uuid4()), workspace_id=d.ws.id, department_id=d.department.id,
            developer_id=d.head.id,
            role_in_department=(
                DepartmentMemberRole.HEAD.value
                if head_via_role
                else DepartmentMemberRole.MEMBER.value
            ),
        )
    )
    # A second member, so "picked the head" is distinguishable from "picked
    # whoever was in the department".
    db.add(
        DepartmentMember(
            id=str(uuid4()), workspace_id=d.ws.id, department_id=d.department.id,
            developer_id=d.grunt.id, role_in_department=DepartmentMemberRole.MEMBER.value,
        )
    )

    d.mailbox = ServiceDeskMailbox(
        id=str(uuid4()), workspace_id=d.ws.id, address="ops@d.example", channel="webhook"
    )
    db.add(d.mailbox)
    await seed_service_desk_taxonomy(db, d.ws.id)
    await db.commit()
    return d


# ------------------------------------------------------------------ the default


def test_the_default_is_the_accountable_owner_not_a_coin_toss() -> None:
    assert unmatched_assignment({}) == "desk_head"


def test_an_explicit_choice_is_still_honoured() -> None:
    """Including "random" — the option stays available, it just is not the default."""
    assert unmatched_assignment({"unmatched_assignment": "random"}) == "random"
    assert unmatched_assignment({"unmatched_assignment": "unassigned"}) == "unassigned"


def test_nonsense_falls_back_to_the_default_rather_than_raising() -> None:
    """Read on the intake path: refusing to route mail would drop tickets."""
    assert unmatched_assignment({"unmatched_assignment": "sideways"}) == "desk_head"


# ------------------------------------------------------- resolving "the head"


@pytest.mark.asyncio
async def test_the_head_is_found_from_the_membership_role(
    db_session: AsyncSession,
) -> None:
    """The case that was broken: the org chart names a head, the column is null.

    This is the Bimaplan shape exactly — Operations shows Chandan Tyagi as Head
    and ``head_id`` is null — and it resolved to nobody.
    """
    d = await _desk(db_session, "head-role", head_via_role=True)

    assert d.department.head_id is None
    assert await resolve_desk_head_id(db_session, d.ws.id) == d.head.id


@pytest.mark.asyncio
async def test_the_column_is_used_when_it_is_set(db_session: AsyncSession) -> None:
    d = await _desk(db_session, "head-col", head_via_column=True)

    assert await resolve_desk_head_id(db_session, d.ws.id) == d.head.id


@pytest.mark.asyncio
async def test_the_column_wins_over_the_membership_role(
    db_session: AsyncSession,
) -> None:
    """A desk that deliberately named a different head keeps it."""
    d = await _desk(db_session, "head-both", head_via_column=True, head_via_role=True)
    other = Developer(id=str(uuid4()), email="other@d.example", name="Named Head")
    db_session.add(other)
    await db_session.flush()
    db_session.add(
        WorkspaceMember(
            id=str(uuid4()), workspace_id=d.ws.id, developer_id=other.id, role="member"
        )
    )
    d.department.head_id = other.id
    await db_session.commit()

    assert await resolve_desk_head_id(db_session, d.ws.id) == other.id


@pytest.mark.asyncio
async def test_a_head_who_left_the_workspace_is_not_returned(
    db_session: AsyncSession,
) -> None:
    """Department rows outlive the people in them."""
    d = await _desk(db_session, "head-gone", head_via_role=True)
    member = (
        await db_session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == d.ws.id,
                WorkspaceMember.developer_id == d.head.id,
            )
        )
    ).scalar_one()
    member.status = "removed"
    await db_session.commit()

    assert await resolve_desk_head_id(db_session, d.ws.id) is None


# ----------------------------------------------------------------- the routing


@pytest.mark.asyncio
async def test_an_unmatched_sender_reaches_the_operations_head(
    db_session: AsyncSession,
) -> None:
    """The whole point: mail nothing matches lands on one accountable person."""
    d = await _desk(
        db_session,
        "route-head",
        sd_settings={"unmatched_assignment": "desk_head"},
        head_via_role=True,
    )

    ticket = await ServiceDeskIntakeService(db_session).create_ticket(
        d.ws.id,
        InboundEmail(
            to="ops@d.example",
            from_email="stranger@nowhere.example",
            from_name="Stranger",
            subject="Is this covered?",
            body_text="Asking about a policy.",
        ),
        d.mailbox,
        source="test",
        classify=False,
        send_receipt=False,
    )
    await db_session.commit()

    assert ticket.assignee_id == d.head.id
    assert ticket.assignee_id != d.grunt.id


@pytest.mark.asyncio
async def test_no_head_recorded_does_not_silently_become_random(
    db_session: AsyncSession,
) -> None:
    """It used to fall through to ``_random_owner``, undoing the setting.

    The ticket now reaches the workspace owner — accountable, and the note says
    the head is the thing to go and set.
    """
    d = await _desk(
        db_session,
        "route-nohead",
        sd_settings={"unmatched_assignment": "desk_head"},
    )

    ticket = await ServiceDeskIntakeService(db_session).create_ticket(
        d.ws.id,
        InboundEmail(
            to="ops@d.example",
            from_email="stranger@nowhere.example",
            subject="Is this covered?",
            body_text="Asking about a policy.",
        ),
        d.mailbox,
        source="test",
        classify=False,
        send_receipt=False,
    )
    await db_session.commit()

    assert ticket.assignee_id == d.owner.id
    assert ticket.assignee_id != d.grunt.id

    note = (ticket.field_values or {}).get("assignment_note") or ""
    assert "no head recorded" in note
    assert "Operations" in note


@pytest.mark.asyncio
async def test_the_dead_end_note_names_the_head_not_the_roster(
    db_session: AsyncSession,
) -> None:
    """The note used to assert "no active members" whatever the cause.

    Which is wrong and expensively so: it sends somebody to check the department
    roster when the department is full and the empty field is the head.
    """
    d = await _desk(
        db_session,
        "route-note",
        sd_settings={"unmatched_assignment": "desk_head"},
    )

    ticket = await ServiceDeskIntakeService(db_session).create_ticket(
        d.ws.id,
        InboundEmail(
            to="ops@d.example",
            from_email="stranger@nowhere.example",
            subject="Question",
            body_text="...",
        ),
        d.mailbox,
        source="test",
        classify=False,
        send_receipt=False,
    )
    await db_session.commit()

    note = (ticket.field_values or {}).get("assignment_note") or ""
    assert "no active members" not in note


@pytest.mark.asyncio
async def test_a_ticket_is_still_created_when_nobody_can_own_it(
    db_session: AsyncSession,
) -> None:
    """Routing is never allowed to cost the ticket."""
    d = await _desk(
        db_session,
        "route-exists",
        sd_settings={"unmatched_assignment": "desk_head"},
    )

    ticket = await ServiceDeskIntakeService(db_session).create_ticket(
        d.ws.id,
        InboundEmail(
            to="ops@d.example",
            from_email="stranger@nowhere.example",
            subject="Still a ticket",
            body_text="...",
        ),
        d.mailbox,
        source="test",
        classify=False,
        send_receipt=False,
    )
    await db_session.commit()

    assert isinstance(ticket, Ticket)
    assert ticket.ticket_number is not None

"""Who may change a Service Desk ticket, and the outbound stakeholder email.

Visibility and authority are separate questions. An Ops Lead holds
``can_view_all_service_desk`` so every row passes the scope clause; these tests
pin that seeing a ticket never implies being allowed to touch it, and that the
ticket-level email goes out only for the people who may act on the ticket.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from aexy.models.developer import Developer
from aexy.models.organization import Department, DepartmentMember
from aexy.models.google_integration import GoogleIntegration
from aexy.models.role import CustomRole
from aexy.models.service_desk import (
    ServiceDeskInsurer,
    ServiceDeskInsurerDomain,
    ServiceDeskMailbox,
    ServiceDeskPartner,
    ServiceDeskPartnerDomain,
    ServiceDeskTicket,
    TicketPendingSegment,
)
from aexy.models.ticketing import Ticket, TicketForm, TicketResponse
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import TicketFieldsUpdate
from aexy.services import service_desk_mailer
from aexy.services.service_desk_ticket_service import ServiceDeskTicketService

from fastapi import HTTPException


async def _member(db, ws_id: str, label: str, permissions: list[str]) -> str:
    dev = Developer(id=str(uuid4()), email=f"{label}-{uuid4().hex[:6]}@capbumpy.in", name=label)
    db.add(dev)
    await db.flush()
    role = CustomRole(
        id=str(uuid4()),
        workspace_id=ws_id,
        name=f"{label}-role",
        slug=f"{label}-{uuid4().hex[:6]}",
        permissions=permissions,
    )
    db.add(role)
    await db.flush()
    db.add(
        WorkspaceMember(
            workspace_id=ws_id, developer_id=dev.id, role="member", status="active", role_id=role.id
        )
    )
    await db.flush()
    return dev.id


async def _in_ops_kam(db, ws_id: str, developer_id: str) -> None:
    """Row scope is by department, so a KAM outside Operations-KAM sees nothing."""
    dept = (
        await db.execute(
            select(Department).where(
                Department.workspace_id == ws_id, Department.function_key == "ops_kam"
            )
        )
    ).scalar_one_or_none()
    if dept is None:
        dept = Department(
            id=str(uuid4()),
            workspace_id=ws_id,
            name="Operations-KAM",
            slug=f"ops-kam-{uuid4().hex[:6]}",
            function_key="ops_kam",
            path="/ops_kam/",
            depth=0,
        )
        db.add(dept)
        await db.flush()
    db.add(
        DepartmentMember(
            id=str(uuid4()), workspace_id=ws_id, department_id=dept.id, developer_id=developer_id
        )
    )
    await db.flush()


@pytest.fixture
async def desk(db_session):
    """One BSD ticket assigned to a KAM, with a Gmail-linked watched mailbox."""
    owner = Developer(id=str(uuid4()), email=f"august-{uuid4().hex[:6]}@capbumpy.in", name="August")
    db_session.add(owner)
    await db_session.flush()
    ws = Workspace(id=str(uuid4()), name="BP", slug=f"bp-{uuid4().hex[:6]}", owner_id=owner.id)
    db_session.add(ws)
    await db_session.flush()

    integration = GoogleIntegration(
        id=str(uuid4()),
        workspace_id=ws.id,
        connected_by_id=owner.id,
        google_email="august@capbumpy.in",
        access_token="t",
        refresh_token="r",
        token_expiry=datetime.now(timezone.utc) + timedelta(hours=1),
        gmail_sync_enabled=True,
    )
    db_session.add(integration)
    mailbox = ServiceDeskMailbox(
        id=str(uuid4()),
        workspace_id=ws.id,
        address="august@capbumpy.in",
        channel="gmail_sync",
        integration_id=integration.id,
    )
    db_session.add(mailbox)

    partner = ServiceDeskPartner(id=str(uuid4()), workspace_id=ws.id, name="Partner P1")
    db_session.add(partner)
    await db_session.flush()
    db_session.add(
        ServiceDeskPartnerDomain(
            id=str(uuid4()),
            workspace_id=ws.id,
            partner_id=partner.id,
            domain="paimonking@runbox.com",
        )
    )
    insurer = ServiceDeskInsurer(id=str(uuid4()), workspace_id=ws.id, name="Insurer I1")
    db_session.add(insurer)
    await db_session.flush()
    db_session.add(
        ServiceDeskInsurerDomain(
            id=str(uuid4()),
            workspace_id=ws.id,
            insurer_id=insurer.id,
            domain="claims@insurer-one.example",
        )
    )

    kam = await _member(db_session, ws.id, "paimon", ["can_view_service_desk"])
    other_kam = await _member(db_session, ws.id, "solomon", ["can_view_service_desk"])
    await _in_ops_kam(db_session, ws.id, kam)
    await _in_ops_kam(db_session, ws.id, other_kam)
    lead = await _member(
        db_session, ws.id, "chaos", ["can_view_service_desk", "can_view_all_service_desk"]
    )
    manager = await _member(
        db_session,
        ws.id,
        "abraxas",
        ["can_view_service_desk", "can_view_all_service_desk", "can_manage_service_desk"],
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
        ticket_number=1,
        submitter_email="paimonking@runbox.com",
        submitter_name="King Paimon",
        field_values={"subject": "Claim status", "body": "..."},
        status="new",
        assignee_id=kam,
        source="service_desk_gmail",
    )
    db_session.add(ticket)
    await db_session.flush()
    db_session.add(
        ServiceDeskTicket(
            id=str(uuid4()),
            workspace_id=ws.id,
            ticket_id=ticket.id,
            partner_id=partner.id,
            request_type="claims",
            pending_with="kam",
            origin="email",
            mailbox_id=mailbox.id,
            thread_ref="gmail-thread-1",
        )
    )
    db_session.add(
        TicketPendingSegment(
            id=str(uuid4()), workspace_id=ws.id, ticket_id=ticket.id, pending_with="kam"
        )
    )
    await db_session.commit()
    return {
        "ws": ws.id,
        "ticket": ticket.id,
        "kam": kam,
        "other_kam": other_kam,
        "lead": lead,
        "manager": manager,
    }


@pytest.fixture
def sent(monkeypatch):
    """Capture the Gmail send instead of making it, keeping the guard path real."""
    calls: list[dict] = []

    async def _capture(db, integration_id, from_address, to_email, subject, body_text, thread_id):
        calls.append(
            {
                "integration_id": integration_id,
                "from": from_address,
                "to": to_email,
                "subject": subject,
                "body": body_text,
                "thread_id": thread_id,
            }
        )

    monkeypatch.setattr(service_desk_mailer, "_send_via_gmail", _capture)
    return calls


# ------------------------------------------------------------------ authority


@pytest.mark.asyncio
async def test_view_all_does_not_grant_edit(db_session, desk):
    """The Ops Lead defect: every row visible, not one row editable."""
    svc = ServiceDeskTicketService(db_session)

    with pytest.raises(HTTPException) as moved:
        await svc.change_pending_with(
            desk["ws"], desk["ticket"], "insurer", scope_developer_id=desk["lead"]
        )
    assert moved.value.status_code == 403

    with pytest.raises(HTTPException) as edited:
        await svc.update_fields(
            desk["ws"],
            desk["ticket"],
            TicketFieldsUpdate(request_type="payout"),
            scope_developer_id=desk["lead"],
        )
    assert edited.value.status_code == 403

    # ...and reading it still works, which is the whole point of the role.
    detail = await svc.get_detail(desk["ws"], desk["ticket"], scope_developer_id=desk["lead"])
    assert detail.pending_with == "kam"
    assert detail.request_type == "claims"


@pytest.mark.asyncio
async def test_assigned_kam_may_triage_and_hand_off_their_own_ticket(db_session, desk):
    svc = ServiceDeskTicketService(db_session)

    edited = await svc.update_fields(
        desk["ws"],
        desk["ticket"],
        TicketFieldsUpdate(request_type="payout"),
        scope_developer_id=desk["kam"],
    )
    assert edited.request_type == "payout"

    moved = await svc.change_pending_with(
        desk["ws"], desk["ticket"], "insurer", scope_developer_id=desk["kam"]
    )
    assert moved.pending_with == "insurer"


@pytest.mark.asyncio
async def test_another_kam_cannot_even_see_it(db_session, desk):
    """Out of scope stays 404, so ids are not enumerable by probing for 403s."""
    svc = ServiceDeskTicketService(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.update_fields(
            desk["ws"],
            desk["ticket"],
            TicketFieldsUpdate(request_type="payout"),
            scope_developer_id=desk["other_kam"],
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_manager_may_act_on_a_ticket_assigned_to_someone_else(db_session, desk):
    svc = ServiceDeskTicketService(db_session)
    moved = await svc.change_pending_with(
        desk["ws"], desk["ticket"], "partner", scope_developer_id=desk["manager"]
    )
    assert moved.pending_with == "partner"


# ------------------------------------------------------------ outbound email


@pytest.mark.asyncio
async def test_email_goes_out_as_the_watched_mailbox_and_keeps_the_ticket_identity(
    db_session, desk, sent
):
    svc = ServiceDeskTicketService(db_session)
    detail = await svc.email_stakeholder(
        desk["ws"],
        desk["ticket"],
        "claims@insurer-one.example",
        "Please confirm the claim register",
        "Sharing the claim register for your confirmation.",
        sender_id=desk["kam"],
        scope_developer_id=desk["kam"],
    )
    await db_session.commit()

    assert len(sent) == 1
    # Sent as August, not as the KAM, and threaded onto the ticket's conversation.
    assert sent[0]["from"] == "august@capbumpy.in"
    assert sent[0]["to"] == "claims@insurer-one.example"
    assert sent[0]["thread_id"] == "gmail-thread-1"
    # The BSD number is what the deterministic inbound matcher reads.
    assert sent[0]["subject"].startswith("[BSD-1] ")

    outgoing = [c for c in detail.correspondence if c.direction == "outgoing"]
    assert len(outgoing) == 1
    assert outgoing[0].author_email == "august@capbumpy.in"
    assert "claims@insurer-one.example" in outgoing[0].content

    stored = (
        await db_session.execute(
            select(TicketResponse).where(TicketResponse.ticket_id == desk["ticket"])
        )
    ).scalars().all()
    assert [r.is_internal for r in stored] == [False]
    assert stored[0].author_id == desk["kam"]


@pytest.mark.asyncio
async def test_an_existing_bsd_subject_is_not_prefixed_twice(db_session, desk, sent):
    svc = ServiceDeskTicketService(db_session)
    await svc.email_stakeholder(
        desk["ws"],
        desk["ticket"],
        "paimonking@runbox.com",
        "Re: BSD-1 - claim update",
        "Update below.",
        sender_id=desk["kam"],
        scope_developer_id=desk["kam"],
    )
    assert sent[0]["subject"] == "Re: BSD-1 - claim update"


@pytest.mark.asyncio
async def test_recipient_must_be_configured_master_data(db_session, desk, sent):
    """The send leaves a real Gmail account, so the address list is a closed set."""
    svc = ServiceDeskTicketService(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.email_stakeholder(
            desk["ws"],
            desk["ticket"],
            "someone-else@example.com",
            "Hello",
            "Body",
            sender_id=desk["kam"],
            scope_developer_id=desk["kam"],
        )
    assert exc.value.status_code == 400
    assert sent == []


@pytest.mark.asyncio
async def test_ops_lead_cannot_email_from_a_ticket(db_session, desk, sent):
    svc = ServiceDeskTicketService(db_session)
    with pytest.raises(HTTPException) as exc:
        await svc.email_stakeholder(
            desk["ws"],
            desk["ticket"],
            "claims@insurer-one.example",
            "Hello",
            "Body",
            sender_id=desk["lead"],
            scope_developer_id=desk["lead"],
        )
    assert exc.value.status_code == 403
    assert sent == []


@pytest.mark.asyncio
async def test_recipients_offered_are_the_ticket_partner_insurers_and_requester(db_session, desk):
    detail = await ServiceDeskTicketService(db_session).get_detail(
        desk["ws"], desk["ticket"], scope_developer_id=desk["kam"]
    )
    assert {r.email for r in detail.email_recipients} == {
        "paimonking@runbox.com",
        "claims@insurer-one.example",
    }


@pytest.mark.asyncio
async def test_a_mailbox_without_a_gmail_link_refuses_rather_than_sending_from_the_system(
    db_session, desk
):
    """Falling back to the transactional sender would break the reply loop."""
    unlinked = ServiceDeskMailbox(
        id=str(uuid4()), workspace_id=desk["ws"], address="webhook@capbumpy.in", channel="webhook"
    )
    with pytest.raises(RuntimeError):
        await service_desk_mailer.send_stakeholder_email(
            db_session, unlinked, "claims@insurer-one.example", "s", "b"
        )
    with pytest.raises(RuntimeError):
        await service_desk_mailer.send_stakeholder_email(
            db_session, None, "claims@insurer-one.example", "s", "b"
        )

"""Priority ordering: stated priorities ranked, unset always last."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.service_desk import ServiceDeskTicket
from aexy.models.ticketing import Ticket, TicketForm
from aexy.models.workspace import Workspace, WorkspaceMember
from aexy.schemas.service_desk import TicketFilters
from aexy.services.service_desk_service import _ticket_order
from tests.conftest import seed_service_desk_taxonomy


async def _rows(db: AsyncSession, direction: str) -> list[str | None]:
    owner = Developer(id=str(uuid4()), email=f"o-{uuid4().hex[:6]}@d.example", name="O")
    db.add(owner)
    await db.flush()
    ws = Workspace(id=str(uuid4()), name="W", slug=f"w-{uuid4().hex[:6]}", owner_id=owner.id)
    db.add(ws)
    await db.flush()
    db.add(WorkspaceMember(workspace_id=ws.id, developer_id=owner.id, role="admin", status="active"))
    await seed_service_desk_taxonomy(db, ws.id)
    form = TicketForm(id=str(uuid4()), workspace_id=ws.id, name="SD", slug=f"sd-{uuid4().hex[:6]}", created_by_id=owner.id)
    db.add(form)
    await db.flush()
    # Inserted out of order on purpose, so the result cannot be insertion order.
    for n, prio in enumerate(["medium", None, "urgent", "low", "high"], start=1):
        t = Ticket(id=str(uuid4()), workspace_id=ws.id, form_id=form.id, ticket_number=n,
                   field_values={"subject": str(prio)}, status="new", priority=prio)
        db.add(t)
        await db.flush()
        db.add(ServiceDeskTicket(id=str(uuid4()), workspace_id=ws.id, ticket_id=t.id,
                                 request_type="claims", pending_with="kam", origin="manual"))
    await db.commit()

    q = (select(Ticket.priority)
         .join(ServiceDeskTicket, ServiceDeskTicket.ticket_id == Ticket.id)
         .where(Ticket.workspace_id == ws.id)
         .order_by(*_ticket_order(TicketFilters(sort="priority", direction=direction))))
    return list((await db.execute(q)).scalars().all())


@pytest.mark.asyncio
async def test_descending_leads_with_urgent_and_ends_with_unset(db_session):
    """The default direction. This used to open with every untriaged ticket."""
    assert await _rows(db_session, "desc") == ["urgent", "high", "medium", "low", None]


@pytest.mark.asyncio
async def test_ascending_leads_with_low_and_still_ends_with_unset(db_session):
    """Reversing the arrow reverses the stated priorities, not the absence of one."""
    assert await _rows(db_session, "asc") == ["low", "medium", "high", "urgent", None]

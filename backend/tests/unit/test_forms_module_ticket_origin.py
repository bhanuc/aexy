"""A ticket knows which of the two form systems it came from.

`tickets.form_id` is a foreign key to `ticket_forms` and was NOT NULL. The
Forms module's submission handler wrote its own `forms.id` into that column, so
`tickets_form_id_fkey` rejected the insert and every submission to a Forms
module form with `auto_create_ticket` enabled answered 500 — every time, for
the entire life of the feature.

`form_id` is now nullable with a sibling `forms_form_id`, and a CHECK keeps
exactly one of them set so the relaxed NOT NULL cannot become "belongs to no
form at all".
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from aexy.models.developer import Developer
from aexy.models.forms import Form, FormField
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


async def _forms_form(db: AsyncSession, ws: Workspace) -> Form:
    form = Form(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="Support Request",
        slug=f"support-{ws.slug}",
        public_url_token=f"tok-{ws.slug}",
        is_active=True,
        auth_mode="anonymous",
        require_email=True,
        theme={},
        thank_you_page={},
        auto_create_ticket=True,
        ticket_config={},
        ticket_assignment_mode="unassigned",
        ticket_field_mappings={},
        auto_create_record=False,
        crm_field_mappings={},
        auto_create_deal=False,
        deal_field_mappings={},
        link_deal_to_record=False,
        trigger_automations=False,
        automation_ids=[],
        destinations=[],
        conditional_rules=[],
        submission_count=0,
    )
    db.add(form)
    await db.flush()
    for position, (name, key, field_type) in enumerate(
        [("Subject", "title", "text"), ("Description", "description", "textarea")]
    ):
        db.add(
            FormField(
                id=str(uuid.uuid4()),
                form_id=form.id,
                name=name,
                field_key=key,
                field_type=field_type,
                is_required=False,
                validation_rules={},
                position=position,
                is_visible=True,
                width="full",
                external_mappings={},
            )
        )
    await db.flush()
    return form


async def _ticket_form(db: AsyncSession, ws: Workspace) -> TicketForm:
    form = TicketForm(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name="Desk",
        slug=f"desk-{ws.slug}",
        public_url_token=f"desk-tok-{ws.slug}",
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


def _ticket(ws_id: str, number: int, **origin) -> Ticket:
    return Ticket(
        id=str(uuid.uuid4()),
        workspace_id=ws_id,
        ticket_number=number,
        status=TicketStatus.NEW.value,
        field_values={},
        attachments=[],
        **origin,
    )


@pytest.mark.asyncio
async def test_a_forms_module_form_can_own_a_ticket(db_session: AsyncSession):
    """The insert the foreign key used to refuse."""
    ws = await _workspace(db_session, "forms-origin-ws")
    form = await _forms_form(db_session, ws)

    number = await next_ticket_number(db_session, ws.id)
    ticket = _ticket(ws.id, number, forms_form_id=form.id)
    db_session.add(ticket)
    await db_session.flush()

    assert ticket.form_id is None
    assert ticket.forms_form_id == form.id


@pytest.mark.asyncio
async def test_a_ticket_form_still_owns_its_tickets(db_session: AsyncSession):
    ws = await _workspace(db_session, "ticket-origin-ws")
    form = await _ticket_form(db_session, ws)

    number = await next_ticket_number(db_session, ws.id)
    ticket = _ticket(ws.id, number, form_id=form.id)
    db_session.add(ticket)
    await db_session.flush()

    assert ticket.form_id == form.id
    assert ticket.forms_form_id is None


@pytest.mark.asyncio
async def test_a_ticket_belonging_to_no_form_is_refused(db_session: AsyncSession):
    """Relaxing NOT NULL must not permit an orphan."""
    ws = await _workspace(db_session, "orphan-ws")
    number = await next_ticket_number(db_session, ws.id)
    db_session.add(_ticket(ws.id, number))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_ticket_claiming_both_forms_is_refused(db_session: AsyncSession):
    ws = await _workspace(db_session, "both-ws")
    forms_form = await _forms_form(db_session, ws)
    ticket_form = await _ticket_form(db_session, ws)
    number = await next_ticket_number(db_session, ws.id)

    db_session.add(
        _ticket(ws.id, number, form_id=ticket_form.id, forms_form_id=forms_form.id)
    )
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_a_forms_module_ticket_is_titled_from_the_submission(
    db_session: AsyncSession,
):
    """The title was computed and then never passed to the Ticket.

    Every ticket a Forms module form created carried a null title, so it read
    as untitled anywhere the read path could not reconstruct one.
    """
    from aexy.schemas.forms import PublicFormSubmission
    from aexy.services.form_submission_handler import FormSubmissionHandler

    ws = await _workspace(db_session, "titled-ws")
    form = await _forms_form(db_session, ws)

    # Reload with fields eager-loaded, the way the public endpoint gets it.
    form = (
        await db_session.execute(
            select(Form).options(selectinload(Form.fields)).where(Form.id == form.id)
        )
    ).scalars().one()

    handler = FormSubmissionHandler(db_session)
    await handler.process_submission(
        form=form,
        submission_data=PublicFormSubmission(
            email="someone@example.com",
            name="Someone",
            data={"title": "Cannot log in", "description": "since Tuesday"},
        ),
    )

    # Read the row back rather than the submission's lazy relationship.
    ticket = (
        await db_session.execute(
            select(Ticket).where(Ticket.forms_form_id == form.id)
        )
    ).scalars().first()
    assert ticket is not None, "auto_create_ticket is on; a ticket must exist"
    assert ticket.title == "Cannot log in"
    assert ticket.forms_form_id == form.id
    assert ticket.form_id is None


@pytest.mark.asyncio
async def test_deleting_a_form_that_raised_tickets_is_refused(db_session: AsyncSession):
    """`forms_form_id` cascaded, so one click could take support history with it.

    Nothing pointed at `forms.id` from `tickets` before, so the cascade reached
    nothing and the risk was theoretical. Now that these tickets exist it is
    not, and RESTRICT plus this check keeps the deletion from happening.
    """
    from aexy.services.forms_service import FormHasTicketsError, FormsService

    ws = await _workspace(db_session, "undeletable-ws")
    form = await _forms_form(db_session, ws)

    number = await next_ticket_number(db_session, ws.id)
    db_session.add(_ticket(ws.id, number, forms_form_id=form.id))
    await db_session.flush()

    with pytest.raises(FormHasTicketsError) as excinfo:
        await FormsService(db_session).delete_form(form.id)
    assert excinfo.value.ticket_count == 1
    assert "Support Request" in str(excinfo.value)

    # The row is still there.
    assert (
        await db_session.execute(select(Form).where(Form.id == form.id))
    ).scalars().first() is not None


@pytest.mark.asyncio
async def test_a_form_with_no_tickets_still_deletes(db_session: AsyncSession):
    """The guard must not turn into "forms can never be deleted"."""
    from aexy.services.forms_service import FormsService

    ws = await _workspace(db_session, "deletable-ws")
    form = await _forms_form(db_session, ws)

    assert await FormsService(db_session).delete_form(form.id) is True
    assert (
        await db_session.execute(select(Form).where(Form.id == form.id))
    ).scalars().first() is None


@pytest.mark.asyncio
async def test_the_public_view_reads_labels_from_a_forms_module_form(
    db_session: AsyncSession,
):
    """The share page read `ticket.form` only, which these tickets never have.

    Without this it fell back to humanising the stored keys — "field 4" for a
    question labelled "Phone Number" — and reported no form name at all.
    """
    from aexy.api.public_tickets import shared_ticket_to_response
    from aexy.services.ticket_service import TicketService

    ws = await _workspace(db_session, "public-view-ws")
    form = await _forms_form(db_session, ws)
    # `phone` is a Forms module type that `TicketFieldType` has no name for.
    db_session.add(
        FormField(
            id=str(uuid.uuid4()),
            form_id=form.id,
            name="Phone Number",
            field_key="field_4",
            field_type="phone",
            is_required=False,
            validation_rules={},
            position=2,
            is_visible=True,
            width="full",
            external_mappings={},
        )
    )
    number = await next_ticket_number(db_session, ws.id)
    ticket = _ticket(ws.id, number, forms_form_id=form.id)
    db_session.add(ticket)
    await db_session.flush()

    loaded = await TicketService(db_session).get_ticket(ticket.id)
    response = shared_ticket_to_response(loaded, can_reply=False)

    assert response.form_name == "Support Request"
    by_key = {field.field_key: field for field in response.fields}
    assert by_key["field_4"].name == "Phone Number"
    # Displayed as the nearest ticket-form type rather than failing the
    # response with a validation error the visitor would see as a 500.
    assert by_key["field_4"].field_type == "text"


@pytest.mark.asyncio
async def test_filtering_by_form_finds_tickets_from_either_system(
    db_session: AsyncSession,
):
    """`filters.form_id` only matched `form_id`, so these were unfilterable."""
    from aexy.schemas.ticketing import TicketFilters
    from aexy.services.ticket_service import TicketService

    ws = await _workspace(db_session, "filter-ws")
    forms_form = await _forms_form(db_session, ws)
    ticket_form = await _ticket_form(db_session, ws)

    db_session.add(
        _ticket(
            ws.id,
            await next_ticket_number(db_session, ws.id),
            forms_form_id=forms_form.id,
        )
    )
    db_session.add(
        _ticket(
            ws.id,
            await next_ticket_number(db_session, ws.id),
            form_id=ticket_form.id,
        )
    )
    await db_session.flush()

    service = TicketService(db_session)
    found, total = await service.list_tickets(
        ws.id, filters=TicketFilters(form_id=forms_form.id)
    )
    assert total == 1
    assert found[0].forms_form_id == forms_form.id

    found, total = await service.list_tickets(
        ws.id, filters=TicketFilters(form_id=ticket_form.id)
    )
    assert total == 1
    assert found[0].form_id == ticket_form.id

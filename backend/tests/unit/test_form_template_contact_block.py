"""Templates stopped asking for an email the form already asks for.

The public page renders a contact block — Your Name, Email Address — above the
designed fields. Every Forms module template also seeded its own "Email" field,
and the two CRM templates a "Full Name", so a support form created from a
template asked for an email twice, in two boxes, and stored the two answers in
two different places.

The fields are gone. What each template *meant* by them survives as the contact
block it asks for, and CRM mappings that name `name` or `email` still resolve —
now from the contact block rather than from a duplicate field.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.workspace import Workspace
from aexy.services.forms_service import FORM_TEMPLATES, FormsService

# What the contact block collects. A template field on either key is a
# duplicate of a box the public page already renders.
CONTACT_KEYS = {"name", "email"}


async def _workspace(db: AsyncSession) -> tuple[Workspace, Developer]:
    slug = f"tpl-{uuid.uuid4().hex[:8]}"
    dev = Developer(name="Tpl Dev", email=f"{slug}@example.test")
    db.add(dev)
    await db.flush()
    ws = Workspace(name="Tpl WS", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.flush()
    return ws, dev


@pytest.mark.parametrize("template_type", sorted(FORM_TEMPLATES))
def test_no_template_duplicates_the_contact_block(template_type: str):
    """The guard, over every template rather than the ones edited today."""
    keys = {f["field_key"] for f in FORM_TEMPLATES[template_type]["fields"]}
    assert not (keys & CONTACT_KEYS), (
        f"{template_type} seeds {keys & CONTACT_KEYS}, which the public page "
        "already asks for in the contact block"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("template_type", "require_name", "require_email"),
    [
        ("support", False, True),
        ("bug_report", False, True),
        ("contact", True, True),
        ("lead_capture", True, True),
        # Its email field was explicitly "Email (optional)".
        ("feedback", False, False),
    ],
)
async def test_a_template_asks_for_what_its_fields_used_to(
    db_session: AsyncSession,
    template_type: str,
    require_name: bool,
    require_email: bool,
):
    ws, dev = await _workspace(db_session)
    form = await FormsService(db_session).create_form_from_template(
        workspace_id=ws.id, created_by_id=dev.id, template_type=template_type
    )

    assert form.require_name is require_name
    assert form.require_email is require_email
    assert {f.field_key for f in form.fields} & CONTACT_KEYS == set()


@pytest.mark.asyncio
async def test_a_crm_mapping_still_resolves_the_contact_block(
    db_session: AsyncSession,
):
    """`contact` and `lead_capture` map a person into the CRM.

    Their `name` and `email` fields are gone, so a mapping naming those keys
    would resolve to nothing if it could only read the submitted field values.
    """
    from aexy.schemas.forms import PublicFormSubmission
    from aexy.services.form_submission_handler import FormSubmissionHandler
    from tests.conftest import seed_crm_object

    ws, dev = await _workspace(db_session)
    service = FormsService(db_session)
    form = await service.create_form_from_template(
        workspace_id=ws.id, created_by_id=dev.id, template_type="contact"
    )
    form.crm_object_id = await seed_crm_object(db_session, ws.id, "Person")
    form.auto_create_record = True
    form.crm_field_mappings = {"name": "full_name", "email": "email_address"}
    await db_session.flush()

    submission = await FormSubmissionHandler(db_session).process_submission(
        form=form,
        submission_data=PublicFormSubmission(
            email="dana@example.com",
            name="Dana Okafor",
            data={"message": "Please call me"},
        ),
    )

    assert submission.crm_record_id is not None
    from sqlalchemy import select

    from aexy.models.crm import CRMRecord

    record = (
        await db_session.execute(
            select(CRMRecord).where(CRMRecord.id == submission.crm_record_id)
        )
    ).scalars().one()
    assert record.values["full_name"] == "Dana Okafor"
    assert record.values["email_address"] == "dana@example.com"


@pytest.mark.asyncio
async def test_the_submission_itself_records_only_what_was_submitted(
    db_session: AsyncSession,
):
    """The contact block reaches mappings, not the stored answers.

    Copying it into `data` would put the submitter's email back into the
    ticket's `field_values`, showing it twice again — one box removed, one
    duplicate reintroduced.
    """
    from aexy.schemas.forms import PublicFormSubmission
    from aexy.services.form_submission_handler import FormSubmissionHandler

    ws, dev = await _workspace(db_session)
    form = await FormsService(db_session).create_form_from_template(
        workspace_id=ws.id, created_by_id=dev.id, template_type="support"
    )

    submission = await FormSubmissionHandler(db_session).process_submission(
        form=form,
        submission_data=PublicFormSubmission(
            email="sam@example.com",
            name="Sam",
            data={"title": "Cannot log in", "category": "account", "description": "since Tuesday"},
        ),
    )

    assert "email" not in submission.data
    assert "name" not in submission.data
    assert submission.email == "sam@example.com"

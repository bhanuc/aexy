"""The contact block is the form's decision, and some decisions are unsubmittable.

The public form page rendered "Your Name" and "Email Address" above the
designed fields unconditionally — a form with four fields in the builder showed
six on the page, and neither extra appeared anywhere in the designer. Making
those a setting introduced three ways to configure a form nobody can submit:

- required but never asked for, in either field;
- email verification on a form that never asks for an address, which accepts
  the submission and then tells the submitter to check an inbox it never
  collected.

All three are refused by CHECK constraints, and refused earlier here so the
caller gets a 400 naming the toggle rather than a 500 naming a constraint.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.workspace import Workspace
from aexy.schemas.forms import FormCreate, FormUpdate
from aexy.services.forms_service import FormsService, validate_contact_settings


async def _workspace(db: AsyncSession, slug: str) -> tuple[Workspace, Developer]:
    dev = Developer(name=f"Dev {slug}", email=f"{slug}@example.test")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.flush()
    return ws, dev


def test_a_name_cannot_be_required_without_being_asked_for():
    with pytest.raises(ValueError, match="never asks for"):
        validate_contact_settings(
            collect_name=False,
            require_name=True,
            collect_email=True,
            require_email=False,
            auth_mode="anonymous",
        )


def test_an_email_cannot_be_required_without_being_asked_for():
    with pytest.raises(ValueError, match="never asks for"):
        validate_contact_settings(
            collect_name=True,
            require_name=False,
            collect_email=False,
            require_email=True,
            auth_mode="anonymous",
        )


def test_email_verification_needs_an_address_to_verify():
    """The gap the contact CHECK did not cover.

    `require_email` and `collect_email` were tied together, but nothing tied
    `auth_mode`: the submission was accepted and the response reported
    `requires_email_verification` for an address never collected.
    """
    with pytest.raises(ValueError, match="verify"):
        validate_contact_settings(
            collect_name=True,
            require_name=False,
            collect_email=False,
            require_email=False,
            auth_mode="email_verification",
        )


def test_a_form_that_asks_for_nothing_is_allowed():
    """Only *unsubmittable* is refused. A form with no contact block is fine."""
    validate_contact_settings(
        collect_name=False,
        require_name=False,
        collect_email=False,
        require_email=False,
        auth_mode="anonymous",
    )


@pytest.mark.asyncio
async def test_create_form_persists_the_contact_settings(db_session: AsyncSession):
    """They were accepted by the schema and then dropped before the insert."""
    ws, dev = await _workspace(db_session, f"contact-{uuid.uuid4().hex[:8]}")

    form = await FormsService(db_session).create_form(
        workspace_id=ws.id,
        created_by_id=dev.id,
        form_data=FormCreate(
            name="Anonymous Feedback",
            collect_name=False,
            require_name=False,
            collect_email=False,
            require_email=False,
        ),
    )

    assert form.collect_name is False
    assert form.collect_email is False


@pytest.mark.asyncio
async def test_create_form_refuses_an_unsubmittable_contact_block(
    db_session: AsyncSession,
):
    ws, dev = await _workspace(db_session, f"refuse-{uuid.uuid4().hex[:8]}")

    with pytest.raises(ValueError):
        await FormsService(db_session).create_form(
            workspace_id=ws.id,
            created_by_id=dev.id,
            form_data=FormCreate(
                name="Broken",
                collect_email=False,
                require_email=True,
            ),
        )


@pytest.mark.asyncio
async def test_update_form_validates_the_merged_result(db_session: AsyncSession):
    """A patch is only unsubmittable in combination with what is already stored.

    `{"collect_email": false}` looks harmless on its own; against a form that
    already requires an email it is the refused combination.
    """
    ws, dev = await _workspace(db_session, f"merge-{uuid.uuid4().hex[:8]}")
    service = FormsService(db_session)
    form = await service.create_form(
        workspace_id=ws.id,
        created_by_id=dev.id,
        form_data=FormCreate(name="Support", require_email=True),
    )

    with pytest.raises(ValueError, match="never asks for"):
        await service.update_form(form.id, FormUpdate(collect_email=False))

    # Dropping both together is the coherent edit, and is allowed.
    updated = await service.update_form(
        form.id, FormUpdate(collect_email=False, require_email=False)
    )
    assert updated is not None
    assert updated.collect_email is False

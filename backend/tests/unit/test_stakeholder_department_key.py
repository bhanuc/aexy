"""A stakeholder may point at any department that exists.

Reported from `/settings/service-desk/stakeholders`: picking a department from
the page's own department picker was refused with

    'tech' is not a known function. Use one of: compliance, engineering, ... —
    or a custom key of your own prefixed with 'x_'

The picker is built from the workspace's departments, filtered only on having a
function key at all. A department whose key predates the function registry —
`tech`, say — therefore appears in the list and is then rejected on save, so the
admin is told to choose from a list that does not contain the thing they just
chose from a list.

The two halves disagreed. `canonical_or_grandfathered` keeps a *stored* value
editable, so the department itself stays fine on its own page; but a brand new
stakeholder has no stored value to grandfather, so it could never be pointed at
that department. The department was effectively unusable for desk routing, with
an error that blamed the spelling rather than saying so.

A stakeholder's function key is a *reference*, not a new value: it names a
department that already exists. So a key an active department in the workspace
actually carries is accepted as-is. Anything else still has to satisfy the
registry — the point of which is to stop new keys being invented that nothing
joins to.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.developer import Developer
from aexy.models.organization import Department
from aexy.models.workspace import Workspace
from aexy.services.service_desk_service import ServiceDeskService


async def _ws(db: AsyncSession, slug: str) -> Workspace:
    dev = Developer(name=f"U {slug}")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws


async def _department(
    db: AsyncSession, ws: Workspace, name: str, function_key: str | None
) -> Department:
    d = Department(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name=name,
        slug=name.lower(),
        function_key=function_key,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


@pytest.mark.asyncio
async def test_a_key_a_department_carries_is_accepted(db_session: AsyncSession):
    """The reported case: a legacy key the picker offers must be selectable."""
    ws = await _ws(db_session, "sd-legacy")
    await _department(db_session, ws, "Claims", "tech")

    service = ServiceDeskService(db_session)
    keys = await service._department_function_keys(str(ws.id))
    assert "tech" in keys

    assert (
        service._stakeholder_function(
            "internal", "tech", None, known_department_keys=keys
        )
        == "tech"
    )


@pytest.mark.asyncio
async def test_a_key_no_department_carries_is_still_refused(
    db_session: AsyncSession,
):
    """The registry still does its job — this is not a blanket bypass."""
    ws = await _ws(db_session, "sd-bogus")
    await _department(db_session, ws, "Claims", "tech")

    service = ServiceDeskService(db_session)
    keys = await service._department_function_keys(str(ws.id))

    with pytest.raises(HTTPException) as exc:
        service._stakeholder_function(
            "internal", "nonsense", None, known_department_keys=keys
        )
    assert exc.value.status_code == 422
    assert "not a known function" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_another_workspaces_key_does_not_leak(db_session: AsyncSession):
    """Keys are collected per workspace, so one tenant's legacy spelling cannot
    make itself valid in another."""
    mine = await _ws(db_session, "sd-mine")
    theirs = await _ws(db_session, "sd-theirs")
    await _department(db_session, theirs, "Claims", "tech")

    service = ServiceDeskService(db_session)
    assert await service._department_function_keys(str(mine.id)) == set()

    with pytest.raises(HTTPException):
        service._stakeholder_function(
            "internal",
            "tech",
            None,
            known_department_keys=await service._department_function_keys(str(mine.id)),
        )


@pytest.mark.asyncio
async def test_an_inactive_departments_key_is_not_offered(db_session: AsyncSession):
    """The picker lists active departments; the guard should agree with it
    rather than keep a retired department's key alive."""
    ws = await _ws(db_session, "sd-inactive")
    dept = await _department(db_session, ws, "Claims", "tech")
    dept.is_active = False
    await db_session.commit()

    service = ServiceDeskService(db_session)
    assert await service._department_function_keys(str(ws.id)) == set()


@pytest.mark.asyncio
async def test_registry_keys_still_canonicalise(db_session: AsyncSession):
    """A retired spelling of a *known* function still resolves forward, rather
    than being passed through untouched because some department holds it."""
    ws = await _ws(db_session, "sd-canon")
    await _department(db_session, ws, "Ops", "operations")

    service = ServiceDeskService(db_session)
    keys = await service._department_function_keys(str(ws.id))
    assert (
        service._stakeholder_function(
            "internal", "ops_kam", None, known_department_keys=keys
        )
        == "operations"
    )


@pytest.mark.asyncio
async def test_a_retired_spelling_on_a_department_still_canonicalises(
    db_session: AsyncSession,
):
    """The order of the two checks matters.

    Accepting any key a department carries, *before* consulting the registry,
    would let a department still storing `ops_kam` pin a stakeholder to that
    spelling. Departments rewrite theirs on their next save — the registry
    resolves retired spellings forward — and the stakeholder would be left
    pointing at a key nothing holds any more. `canonical_or_grandfathered`'s own
    docstring calls that out: a stakeholder saved under a spelling a department
    would have canonicalised "silently joins to nothing, which is
    indistinguishable from 'routing is off'".
    """
    ws = await _ws(db_session, "sd-retired")
    await _department(db_session, ws, "Ops", "ops_kam")

    service = ServiceDeskService(db_session)
    keys = await service._department_function_keys(str(ws.id))
    assert keys == {"ops_kam"}

    stored = service._stakeholder_function(
        "internal", "ops_kam", None, known_department_keys=keys
    )
    assert stored == "operations", (
        "a retired spelling was pinned to the department's stale value instead "
        "of resolving forward"
    )


@pytest.mark.asyncio
async def test_a_case_variant_of_a_department_key_is_accepted(
    db_session: AsyncSession,
):
    """Every other comparison in this area goes through `clean_function_key`,
    so this one has to as well — a caller that is not the settings page (a
    seeder, an import, a script) should not be refused over capitalisation.

    The department's own spelling is what gets stored, so the two rows stay
    byte-identical and every comparison between them holds.
    """
    ws = await _ws(db_session, "sd-case")
    await _department(db_session, ws, "Claims", "tech")

    service = ServiceDeskService(db_session)
    keys = await service._department_function_keys(str(ws.id))

    assert (
        service._stakeholder_function(
            "internal", "Tech", None, known_department_keys=keys
        )
        == "tech"
    )
    assert (
        service._stakeholder_function(
            "internal", "  tech  ", None, known_department_keys=keys
        )
        == "tech"
    )


@pytest.mark.asyncio
async def test_external_buckets_still_carry_no_function(db_session: AsyncSession):
    ws = await _ws(db_session, "sd-ext")
    await _department(db_session, ws, "Claims", "tech")
    service = ServiceDeskService(db_session)
    keys = await service._department_function_keys(str(ws.id))
    assert (
        service._stakeholder_function(
            "external", "tech", None, known_department_keys=keys
        )
        is None
    )

"""Every form endpoint answers with a body the schema accepts.

`form_to_response` builds `FormResponse` field by field, so a field added to
the schema and not to the builder is a 500 on *every* endpoint that returns a
form — create, read, update, duplicate, from-template. That is exactly what
adding the contact-block settings did: `collect_name`, `require_name` and
`collect_email` were required by the schema and never passed, and nothing
caught it because the tests around them all called the service directly.

These go over HTTP so the response model is actually applied.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from aexy.api import access_guard
from aexy.api.developers import get_current_developer
from aexy.core.database import get_db
from aexy.main import app
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace

CONTACT_FIELDS = ("collect_name", "require_name", "collect_email", "require_email")


@pytest.fixture
async def workspace(db_session):
    dev = Developer(name="Forms Dev", email=f"forms-{uuid.uuid4().hex[:8]}@example.test")
    db_session.add(dev)
    await db_session.flush()
    ws = Workspace(name="Forms WS", slug=f"forms-{uuid.uuid4().hex[:8]}", owner_id=dev.id)
    db_session.add(ws)
    await db_session.flush()
    return ws, dev


@pytest.fixture
def api(db_session, workspace, monkeypatch):
    """An authenticated client that owns the workspace."""
    _ws, dev = workspace

    async def _ok(*_args, **_kwargs):
        return None

    async def _yes(self, workspace_id, developer_id, role):
        return True

    monkeypatch.setattr(access_guard, "ensure_app_enabled", _ok)
    monkeypatch.setattr(access_guard, "ensure_member_app_access", _ok)
    monkeypatch.setattr(
        "aexy.services.workspace_service.WorkspaceService.check_permission", _yes
    )

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_developer] = lambda: dev

    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")

    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_every_form_endpoint_returns_a_valid_body(api, workspace):
    """Create, from-template, read, update and duplicate, over HTTP.

    A response model that cannot be built raises inside FastAPI *after* the
    handler returned, so the failure is a 500 with the row already written —
    the form exists and the caller is told the server broke.
    """
    ws, _dev = workspace
    base = f"/api/v1/workspaces/{ws.id}/forms"

    created = await api.post(base, json={"name": "Alpha"})
    assert created.status_code == 200, created.text
    form_id = created.json()["id"]
    for key in CONTACT_FIELDS:
        assert key in created.json(), f"create response is missing {key}"

    from_template = await api.post(f"{base}/from-template/support", params={"name": "Beta"})
    assert from_template.status_code == 200, from_template.text
    for key in CONTACT_FIELDS:
        assert key in from_template.json(), f"from-template response is missing {key}"

    read = await api.get(f"{base}/{form_id}")
    assert read.status_code == 200, read.text

    updated = await api.patch(f"{base}/{form_id}", json={"collect_name": False})
    assert updated.status_code == 200, updated.text
    assert updated.json()["collect_name"] is False

    duplicated = await api.post(
        f"{base}/{form_id}/duplicate", json={"name": "Alpha copy"}
    )
    assert duplicated.status_code == 200, duplicated.text
    # The contact block is part of the design being copied, and `collect_name`
    # was turned off on the original just above.
    assert duplicated.json()["collect_name"] is False


@pytest.mark.asyncio
async def test_an_unsubmittable_contact_block_is_a_400_not_a_500(api, workspace):
    """The refusal is written for a person; it must arrive as one."""
    ws, _dev = workspace
    base = f"/api/v1/workspaces/{ws.id}/forms"

    created = await api.post(base, json={"name": "Gamma", "require_email": True})
    form_id = created.json()["id"]

    refused = await api.patch(f"{base}/{form_id}", json={"collect_email": False})
    assert refused.status_code == 400, refused.text
    assert "never asks for" in refused.json()["detail"]

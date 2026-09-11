"""The table audit trail actually records.

Everything needed for an audit trail existed and nothing wrote to it: the
`TableAuditLog` model, the migrated `table_audit_log` table, a
`TableAuditService.log()` that honours a per-table on/off switch and retention,
a `GET /{table_id}/audit-log` endpoint, a toggle in the table's settings UI,
and even a field-level diff computed by `DataTableService.update_record` and
handed back on `_changes` with the comment "for callers that need them (events,
activity logging)".

The only reference to `TableAuditService` outside its own module was the
reader. So the read endpoint always returned an empty list, and an operator who
switched auditing on, waited, and then opened the log saw "nothing happened"
rather than "this is not recorded" — worse than having no audit log at all,
because it invites the wrong conclusion.

These tests pin the writer, and in particular that:
  * the switch is honoured, so turning auditing on is a real choice and off
    costs nothing;
  * an edit records the field-level diff, which is what makes the trail worth
    keeping — the table view's inline editing goes through this path;
  * a deletion records what was removed, since afterwards the row cannot say.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.crm import CRMObject, TableAuditLog
from aexy.models.developer import Developer
from aexy.models.workspace import Workspace
from aexy.services.data_table_service import DataTableService
from aexy.services.table_audit_service import TableAuditService


async def _ws(db: AsyncSession, slug: str) -> tuple[Workspace, Developer]:
    dev = Developer(name=f"U {slug}")
    db.add(dev)
    await db.flush()
    ws = Workspace(name=f"WS {slug}", slug=slug, owner_id=dev.id)
    db.add(ws)
    await db.commit()
    await db.refresh(ws)
    return ws, dev


async def _table(
    db: AsyncSession,
    ws: Workspace,
    *,
    audit: bool,
    slug: str,
    created_by_id: str | None = None,
) -> CRMObject:
    table = CRMObject(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        name=f"T {slug}",
        slug=slug,
        plural_name=f"T {slug}s",
        scope="standalone",
        # The creator is what `auth.check_access` grants management rights to,
        # so the HTTP tests below have to own the table they edit.
        created_by_id=created_by_id,
        visibility="workspace",
        audit_config={"enabled": audit, "retention_days": 90},
    )
    db.add(table)
    await db.commit()
    await db.refresh(table)
    return table


async def _entries(db: AsyncSession, table_id: str) -> list[TableAuditLog]:
    rows = await db.execute(
        select(TableAuditLog)
        .where(TableAuditLog.table_id == table_id)
        .order_by(TableAuditLog.created_at)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_nothing_is_recorded_while_auditing_is_off(db_session: AsyncSession):
    """Off is the default, and must cost nothing — the call is a no-op rather
    than something callers have to guard."""
    ws, dev = await _ws(db_session, "aud-off")
    table = await _table(db_session, ws, audit=False, slug="aud-off-t")

    entry = await TableAuditService(db_session).log(
        table_id=str(table.id),
        actor_id=str(dev.id),
        action="record_updated",
        record_id=str(uuid.uuid4()),
        changes={"fields": [{"field": "title", "old": "a", "new": "b"}]},
    )
    await db_session.commit()

    assert entry is None
    assert await _entries(db_session, str(table.id)) == []


@pytest.mark.asyncio
async def test_an_edit_records_the_field_level_diff(db_session: AsyncSession):
    """The diff is the point. `update_record` computes it; before this it was
    thrown away, so the trail could say a record changed but not how."""
    ws, dev = await _ws(db_session, "aud-diff")
    table = await _table(db_session, ws, audit=True, slug="aud-diff-t")

    service = DataTableService(db_session)
    record = await service.create_record(
        table_id=str(table.id),
        workspace_id=str(ws.id),
        values={"title": "before", "untouched": "same"},
        created_by_id=str(dev.id),
    )
    await db_session.commit()

    updated = await service.update_record(
        record_id=str(record.id), values={"title": "after"}
    )
    changes = getattr(updated, "_changes", None)
    assert changes == [{"field": "title", "old": "before", "new": "after"}], (
        "update_record stopped reporting its diff — the audit entry depends on it"
    )

    await TableAuditService(db_session).log(
        table_id=str(table.id),
        actor_id=str(dev.id),
        action="record_updated",
        record_id=str(record.id),
        changes={"fields": changes},
        ip_address="203.0.113.7",
    )
    await db_session.commit()

    entries = await _entries(db_session, str(table.id))
    assert len(entries) == 1
    logged = entries[0]
    assert logged.action == "record_updated"
    assert str(logged.actor_id) == str(dev.id)
    assert str(logged.record_id) == str(record.id)
    assert logged.ip_address == "203.0.113.7"
    assert logged.changes["fields"] == [
        {"field": "title", "old": "before", "new": "after"}
    ]
    # A field nobody touched must not appear, or every entry becomes noise.
    assert "untouched" not in str(logged.changes)


@pytest.mark.asyncio
async def test_a_deletion_records_what_was_removed(db_session: AsyncSession):
    """After the delete the row cannot answer, so the values are snapshotted
    before it happens."""
    ws, dev = await _ws(db_session, "aud-del")
    table = await _table(db_session, ws, audit=True, slug="aud-del-t")

    service = DataTableService(db_session)
    record = await service.create_record(
        table_id=str(table.id),
        workspace_id=str(ws.id),
        values={"title": "irreplaceable"},
        created_by_id=str(dev.id),
    )
    await db_session.commit()

    removed = dict(record.values or {})
    assert await service.delete_record(str(record.id), False)
    await TableAuditService(db_session).log(
        table_id=str(table.id),
        actor_id=str(dev.id),
        action="record_deleted",
        record_id=str(record.id),
        changes={"permanent": False, "values": removed},
    )
    await db_session.commit()

    entries = await _entries(db_session, str(table.id))
    assert [e.action for e in entries] == ["record_deleted"]
    assert entries[0].changes["values"] == {"title": "irreplaceable"}


@pytest.mark.asyncio
async def test_the_reader_returns_newest_first_and_filters_by_action(
    db_session: AsyncSession,
):
    ws, dev = await _ws(db_session, "aud-read")
    table = await _table(db_session, ws, audit=True, slug="aud-read-t")
    audit = TableAuditService(db_session)

    # Timestamps are assigned explicitly rather than relied upon: the test
    # database is SQLite, whose CURRENT_TIMESTAMP has second precision, so
    # three entries written in the same second are indistinguishable by time
    # however they are committed. The ordering contract is what is under test
    # here, not the clock.
    ordered = ("record_created", "record_updated", "field_deleted")
    for i, action in enumerate(ordered):
        entry = await audit.log(
            table_id=str(table.id), actor_id=str(dev.id), action=action
        )
        assert entry is not None
        entry.created_at = datetime(2026, 1, 1, 12, i, tzinfo=timezone.utc)
    await db_session.commit()

    entries, total = await audit.get_table_log(str(table.id))
    assert total == 3
    assert entries[0].action == "field_deleted", "newest entry should come first"

    only, count = await audit.get_table_log(
        str(table.id), action_filter="record_updated"
    )
    assert count == 1 and only[0].action == "record_updated"


@pytest.mark.asyncio
async def test_paging_is_stable_across_entries_sharing_a_timestamp(
    db_session: AsyncSession,
):
    """A bulk delete writes one entry per record in a single transaction, so
    they all carry the same `created_at`. Ordering on the timestamp alone left
    that order arbitrary between queries, which for a paged reader means a row
    can show up on two pages while another shows up on none."""
    ws, dev = await _ws(db_session, "aud-page")
    table = await _table(db_session, ws, audit=True, slug="aud-page-t")
    audit = TableAuditService(db_session)

    for _ in range(6):
        await audit.log(
            table_id=str(table.id),
            actor_id=str(dev.id),
            action="record_deleted",
            record_id=str(uuid.uuid4()),
        )
    await db_session.commit()  # one transaction: identical timestamps

    first, total = await audit.get_table_log(str(table.id), limit=3, offset=0)
    second, _ = await audit.get_table_log(str(table.id), limit=3, offset=3)
    assert total == 6
    ids = [str(e.id) for e in first] + [str(e.id) for e in second]
    assert len(set(ids)) == 6, (
        "paging returned the same entry twice and skipped another — the reader "
        "needs a deterministic tiebreak, not just created_at"
    )

    # And repeating the same query gives the same page.
    again, _ = await audit.get_table_log(str(table.id), limit=3, offset=0)
    assert [str(e.id) for e in again] == [str(e.id) for e in first]


# ─── The wiring itself ──────────────────────────────────────────────────
#
# The tests above pin the service's contract. These drive the HTTP endpoints,
# which is where the defect actually was: every piece of the audit trail
# existed and no endpoint called the writer, so the log stayed empty no matter
# what was done to a table.


@pytest_asyncio.fixture
async def api(db_session: AsyncSession, request):
    """Client with the workspace-permission and auth gates overridden.

    Those gates have their own tests; what is under test here is whether a
    successful mutation leaves an audit entry behind.
    """
    from httpx import ASGITransport, AsyncClient

    from aexy.api import tables as tables_api
    from aexy.api.developers import get_current_developer
    from aexy.core.database import get_db
    from aexy.main import app

    dev = Developer(name="Auditor")
    db_session.add(dev)
    await db_session.commit()
    await db_session.refresh(dev)

    async def _db():
        yield db_session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_developer] = lambda: dev

    original = tables_api.check_workspace_permission

    async def _allow(*_args, **_kwargs):
        return True

    tables_api.check_workspace_permission = _allow

    # The tables router is mounted behind `require_app_access("tables")`, whose
    # dependency is a closure created at include time — so it cannot be reached
    # through `dependency_overrides`. Patch the two checks it delegates to
    # instead. Both have their own tests; this fixture is about the audit trail.
    from aexy.api import access_guard

    guard_originals = (
        access_guard.ensure_app_enabled,
        access_guard.ensure_member_app_access,
    )
    access_guard.ensure_app_enabled = _allow
    access_guard.ensure_member_app_access = _allow

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, dev

    tables_api.check_workspace_permission = original
    access_guard.ensure_app_enabled, access_guard.ensure_member_app_access = (
        guard_originals
    )
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_editing_a_record_over_http_leaves_an_audit_entry(
    db_session: AsyncSession, api
):
    """The inline edit the table view and the document embed both perform."""
    client, dev = api
    ws, _ = await _ws(db_session, "aud-http")
    table = await _table(
        db_session, ws, audit=True, slug="aud-http-t", created_by_id=str(dev.id)
    )

    service = DataTableService(db_session)
    record = await service.create_record(
        table_id=str(table.id),
        workspace_id=str(ws.id),
        values={"title": "before"},
        created_by_id=str(dev.id),
    )
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record.id}",
        json={"values": {"title": "after"}},
    )
    assert resp.status_code == 200, resp.text

    entries = await _entries(db_session, str(table.id))
    assert [e.action for e in entries] == ["record_updated"], (
        "editing a record over HTTP recorded nothing — the endpoint is not "
        "calling the audit writer"
    )
    assert entries[0].changes["fields"] == [
        {"field": "title", "old": "before", "new": "after"}
    ]
    assert str(entries[0].record_id) == str(record.id)


@pytest.mark.asyncio
async def test_deleting_a_column_over_http_leaves_an_audit_entry(
    db_session: AsyncSession, api
):
    """Dropping a column takes every value in it, so it is the single most
    important table-view action to be able to attribute."""
    client, dev = api
    ws, _ = await _ws(db_session, "aud-col")
    table = await _table(
        db_session, ws, audit=True, slug="aud-col-t", created_by_id=str(dev.id)
    )

    field = await DataTableService(db_session).add_field(
        table_id=str(table.id), name="Doomed", field_type="text"
    )
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/fields/{field.id}"
    )
    assert resp.status_code == 204, resp.text

    entries = await _entries(db_session, str(table.id))
    assert [e.action for e in entries] == ["field_deleted"], (
        "deleting a column recorded nothing"
    )
    assert entries[0].changes["field_id"] == str(field.id)


@pytest.mark.asyncio
async def test_http_mutations_record_nothing_while_auditing_is_off(
    db_session: AsyncSession, api
):
    """Off has to stay genuinely off — the endpoints must not start writing
    rows for every workspace that never asked for a trail."""
    client, dev = api
    ws, _ = await _ws(db_session, "aud-http-off")
    table = await _table(
        db_session, ws, audit=False, slug="aud-http-off-t", created_by_id=str(dev.id)
    )

    service = DataTableService(db_session)
    record = await service.create_record(
        table_id=str(table.id),
        workspace_id=str(ws.id),
        values={"title": "x"},
        created_by_id=str(dev.id),
    )
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record.id}",
        json={"values": {"title": "y"}},
    )
    assert resp.status_code == 200, resp.text
    assert await _entries(db_session, str(table.id)) == []


@pytest.mark.asyncio
async def test_a_permanent_delete_over_http_does_not_blow_up(
    db_session: AsyncSession, api
):
    """`table_audit_log.record_id` references `crm_records`, so it can only name
    a row that still exists. An archive keeps the row; a permanent delete does
    not — and writing the id anyway makes the audit insert violate the foreign
    key and takes the request down with a 500.

    That is what shipped in 0.37.6: with auditing switched on,
    `DELETE /records/{id}?permanent=true` and every bulk delete (which is always
    permanent) returned 500. It went unnoticed because the soft delete is the
    default, and the default is what got tested.
    """
    client, dev = api
    ws, _ = await _ws(db_session, "aud-perm")
    table = await _table(
        db_session, ws, audit=True, slug="aud-perm-t", created_by_id=str(dev.id)
    )

    service = DataTableService(db_session)
    record = await service.create_record(
        table_id=str(table.id),
        workspace_id=str(ws.id),
        values={"title": "gone for good"},
        created_by_id=str(dev.id),
    )
    await db_session.commit()
    record_id = str(record.id)

    resp = await client.delete(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record_id}"
        "?permanent=true"
    )
    assert resp.status_code == 204, resp.text

    entries = await _entries(db_session, str(table.id))
    deleted = [e for e in entries if e.action == "record_deleted"]
    assert len(deleted) == 1
    # The column has to be empty — the row it would reference is gone — so the
    # id lives in the payload instead, where it still answers "which record".
    assert deleted[0].record_id is None
    assert deleted[0].changes["record_id"] == record_id
    assert deleted[0].changes["values"] == {"title": "gone for good"}
    assert deleted[0].changes["permanent"] is True


@pytest.mark.asyncio
async def test_an_archive_keeps_the_record_reference(
    db_session: AsyncSession, api
):
    """The soft delete leaves the row in place, so the column can still point at
    it and `?record_id=` filtering keeps working."""
    client, dev = api
    ws, _ = await _ws(db_session, "aud-arch")
    table = await _table(
        db_session, ws, audit=True, slug="aud-arch-t", created_by_id=str(dev.id)
    )

    service = DataTableService(db_session)
    record = await service.create_record(
        table_id=str(table.id),
        workspace_id=str(ws.id),
        values={"title": "archived"},
        created_by_id=str(dev.id),
    )
    await db_session.commit()

    resp = await client.delete(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/{record.id}"
    )
    assert resp.status_code == 204, resp.text

    deleted = [
        e for e in await _entries(db_session, str(table.id))
        if e.action == "record_deleted"
    ]
    assert len(deleted) == 1
    assert str(deleted[0].record_id) == str(record.id)


@pytest.mark.asyncio
async def test_bulk_delete_records_what_each_row_held(
    db_session: AsyncSession, api
):
    """Bulk delete is a hard delete, so these rows are the ones whose contents
    cannot be read back by any other means — and they were the ones the trail
    said nothing about. One entry per record, each carrying its own values."""
    client, dev = api
    ws, _ = await _ws(db_session, "aud-bulk")
    table = await _table(
        db_session, ws, audit=True, slug="aud-bulk-t", created_by_id=str(dev.id)
    )

    service = DataTableService(db_session)
    ids = []
    for title in ("first", "second", "third"):
        rec = await service.create_record(
            table_id=str(table.id),
            workspace_id=str(ws.id),
            values={"title": title},
            created_by_id=str(dev.id),
        )
        ids.append(str(rec.id))
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/workspaces/{ws.id}/tables/{table.id}/records/bulk-delete",
        json={"record_ids": ids, "permanent": True},
    )
    assert resp.status_code == 200, resp.text

    deleted = [
        e for e in await _entries(db_session, str(table.id))
        if e.action == "record_deleted"
    ]
    assert len(deleted) == 3, "a trail has to say which rows went, not just how many"
    by_id = {e.changes["record_id"]: e.changes for e in deleted}
    assert set(by_id) == set(ids)
    assert {c["values"]["title"] for c in by_id.values()} == {
        "first", "second", "third",
    }
    assert all(e.record_id is None for e in deleted)

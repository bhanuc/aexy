"""Content sync between a moved task and its original, and a ticket and its task.

The contract (services/content_sync_service.py):
  * "keep" leaves the original untouched — open, same board, same text.
  * With sync on, the link is flagged, no breadcrumb is written on either side,
    and the source's attachments appear on the copy as rows sharing the object.
  * Description edits on either task land on the other, with a history row.
  * Comments and progress updates are read through, not copied.
  * Deleting an attachment removes every mirror; the stored object is only
    released when nothing else points at it.
  * A ticket note becomes a comment on its synced task and vice versa; a
    ticket upload appears on the task; the switch stops all of it.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.dependency import TaskDependency
from aexy.models.developer import Developer
from aexy.models.project import Project
from aexy.models.sprint import SprintTask, TaskActivity, TaskAttachment
from aexy.models.team import Team
from aexy.models.ticketing import Ticket, TicketForm, TicketResponse, TicketStatus
from aexy.models.workspace import Workspace
from aexy.services import content_sync_service as sync
from aexy.services.sprint_task_service import SprintTaskService
from aexy.services.task_attachment_service import attachment_object_still_referenced
from aexy.services.task_config_service import TaskConfigService
from aexy.services.work_update_service import WorkUpdateService


async def _workspace(db: AsyncSession) -> tuple[Workspace, Developer]:
    dev = Developer(id=str(uuid.uuid4()), name="Dev", email=f"d-{uuid.uuid4().hex[:6]}@x.test")
    db.add(dev)
    await db.flush()
    ws = Workspace(id=str(uuid.uuid4()), name="WS", slug=f"ws-{uuid.uuid4().hex[:6]}", owner_id=dev.id)
    db.add(ws)
    await db.flush()
    await TaskConfigService(db).seed_default_statuses(ws.id)
    return ws, dev


async def _project(db: AsyncSession, ws: Workspace, name: str) -> Project:
    slug = f"{name.lower()}-{uuid.uuid4().hex[:6]}"
    p = Project(id=str(uuid.uuid4()), workspace_id=ws.id, name=name, slug=slug)
    db.add(p)
    # SprintTask.team_id FKs to teams.id and holds the project id; the two rows
    # share one id, as ProjectService.create_project arranges.
    db.add(Team(id=p.id, workspace_id=ws.id, name=name, slug=slug))
    await db.flush()
    return p


async def _task(db: AsyncSession, ws: Workspace, project: Project, **kw) -> SprintTask:
    task = SprintTask(
        id=str(uuid.uuid4()),
        workspace_id=ws.id,
        team_id=project.id,
        sprint_id=None,
        title=kw.pop("title", "Fix the login redirect"),
        description=kw.pop("description", "Users bounce to /"),
        description_json=kw.pop("description_json", {"type": "doc", "content": []}),
        status="todo",
        source_type="manual",
        source_id=str(uuid.uuid4()),
        priority="medium",
        labels=[],
        **kw,
    )
    db.add(task)
    await db.flush()
    return task


async def _attach(db: AsyncSession, task: SprintTask, name: str = "spec.pdf") -> TaskAttachment:
    row = TaskAttachment(
        id=str(uuid.uuid4()),
        task_id=task.id,
        file_name=name,
        file_url=f"http://storage/{name}",
        storage_key=f"task-attachments/{task.id}/{uuid.uuid4().hex}_{name}",
        file_size=12,
        content_type="application/pdf",
    )
    db.add(row)
    await db.flush()
    return row


async def _move(db: AsyncSession, task: SprintTask, target: Project, dev: Developer, **kw) -> SprintTask:
    return await SprintTaskService(db).move_to_project(
        task_id=task.id,
        target_project_id=target.id,
        source_action=kw.pop("source_action", "keep"),
        actor_id=dev.id,
        sync_content=kw.pop("sync_content", True),
        **kw,
    )


async def _fresh(db: AsyncSession, task_id: str) -> SprintTask:
    return (
        await db.execute(
            select(SprintTask).where(SprintTask.id == task_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


# ── keep ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keep_leaves_the_original_exactly_as_it_was(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src, description="Users bounce to /")

    copy = await _move(db_session, task, dst, dev, source_action="keep", sync_content=False)
    await db_session.commit()

    original = await _fresh(db_session, task.id)
    assert original.is_archived is False
    assert original.status == "todo"
    assert original.team_id == src.id
    assert original.description == "Users bounce to /", "keep must not write a breadcrumb"
    assert copy.team_id == dst.id
    # …but the copy, not synced, still says where it came from.
    assert "Moved from" in (copy.description or "")


@pytest.mark.asyncio
async def test_keep_rejects_nothing_new_but_unknown_actions_still_fail(db_session: AsyncSession) -> None:
    from aexy.services.sprint_task_service import TaskValidationError

    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    with pytest.raises(TaskValidationError) as exc:
        await _move(db_session, task, dst, dev, source_action="leave")
    assert exc.value.code == "invalid_source_action"


# ── the link and what it carries ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_flags_the_link_and_writes_no_breadcrumbs(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "same"}]}]}
    task = await _task(db_session, ws, src, description="same", description_json=doc)

    copy = await _move(db_session, task, dst, dev, source_action="mark_done", sync_content=True)
    await db_session.commit()

    link = (
        await db_session.execute(
            select(TaskDependency).where(TaskDependency.dependent_task_id == copy.id)
        )
    ).scalar_one()
    assert link.dependency_type == "duplicates"
    assert link.sync_content is True

    original = await _fresh(db_session, task.id)
    # Closed, but still on the board — which is why sync is allowed here.
    assert original.is_archived is False
    assert original.completed_at is not None
    # Both descriptions are the same text — no "Moved to" / "Moved from".
    assert original.description == "same"
    assert copy.description == "same"
    assert copy.description_json == doc
    assert await sync.synced_task_peers(db_session, task.id) == [copy.id]
    assert await sync.synced_task_peers(db_session, copy.id) == [task.id]


@pytest.mark.asyncio
async def test_unsynced_move_keeps_the_old_breadcrumbs(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src, description="body")
    copy = await _move(db_session, task, dst, dev, source_action="archive", sync_content=False)
    await db_session.commit()
    assert (await _fresh(db_session, task.id)).description.startswith("Moved to")
    assert copy.description.startswith("Moved from")
    assert await sync.synced_task_peers(db_session, task.id) == []


@pytest.mark.asyncio
async def test_sync_copies_attachments_as_rows_on_the_same_object(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    original_row = await _attach(db_session, task)

    copy = await _move(db_session, task, dst, dev)
    await db_session.commit()

    rows = (
        await db_session.execute(select(TaskAttachment).where(TaskAttachment.task_id == copy.id))
    ).scalars().all()
    assert [r.storage_key for r in rows] == [original_row.storage_key]
    assert rows[0].file_name == "spec.pdf"
    assert rows[0].id != original_row.id


@pytest.mark.asyncio
async def test_peers_are_transitive_and_bounded(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    a = await _project(db_session, ws, "A")
    b = await _project(db_session, ws, "B")
    c = await _project(db_session, ws, "C")
    task = await _task(db_session, ws, a)
    second = await _move(db_session, task, b, dev)
    third = await _move(db_session, second, c, dev)
    await db_session.commit()
    assert set(await sync.synced_task_peers(db_session, task.id)) == {second.id, third.id}
    assert set(await sync.synced_task_peers(db_session, third.id)) == {task.id, second.id}


@pytest.mark.asyncio
async def test_an_archived_task_is_not_a_peer(db_session: AsyncSession) -> None:
    """Archiving is the other half of the rule the move dialog states.

    The dialog refuses "archive the original" together with "keep in sync",
    but a task can be archived at any time afterwards. Left in the group it
    would collect mirrored comments and files where nobody can read them, and
    deleting an attachment on the live side would reach into the archive.
    """
    ws, dev = await _workspace(db_session)
    a = await _project(db_session, ws, "A")
    b = await _project(db_session, ws, "B")
    task = await _task(db_session, ws, a)
    second = await _move(db_session, task, b, dev)
    await db_session.commit()
    assert await sync.synced_task_peers(db_session, task.id) == [second.id]

    await SprintTaskService(db_session).archive_task(second.id, actor_id=dev.id)
    await db_session.commit()
    assert await sync.synced_task_peers(db_session, task.id) == []


@pytest.mark.asyncio
async def test_unarchiving_puts_the_task_back_in_the_group(db_session: AsyncSession) -> None:
    """The link row is untouched by archiving, so the pair resumes rather than
    needing to be relinked by hand."""
    ws, dev = await _workspace(db_session)
    a = await _project(db_session, ws, "A")
    b = await _project(db_session, ws, "B")
    task = await _task(db_session, ws, a)
    second = await _move(db_session, task, b, dev)
    service = SprintTaskService(db_session)
    await service.archive_task(second.id, actor_id=dev.id)
    await db_session.commit()
    assert await sync.synced_task_peers(db_session, task.id) == []

    await service.unarchive_task(second.id, actor_id=dev.id)
    await db_session.commit()
    assert await sync.synced_task_peers(db_session, task.id) == [second.id]


@pytest.mark.asyncio
async def test_the_walk_passes_through_an_archived_middle(db_session: AsyncSession) -> None:
    """A moved twice with sync on is a group of three. Archiving the middle
    one leaves two live tasks that were deliberately linked, so they stay in
    sync with each other — only the archived member drops out."""
    ws, dev = await _workspace(db_session)
    a = await _project(db_session, ws, "A")
    b = await _project(db_session, ws, "B")
    c = await _project(db_session, ws, "C")
    task = await _task(db_session, ws, a)
    second = await _move(db_session, task, b, dev)
    third = await _move(db_session, second, c, dev)
    await SprintTaskService(db_session).archive_task(second.id, actor_id=dev.id)
    await db_session.commit()

    assert await sync.synced_task_peers(db_session, task.id) == [third.id]
    assert await sync.synced_task_peers(db_session, third.id) == [task.id]


# ── description ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_description_edit_lands_on_the_peer_with_a_history_row(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    copy = await _move(db_session, task, dst, dev)
    await db_session.commit()

    new_doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "rewritten"}]}]}
    await SprintTaskService(db_session).update_task(
        task_id=copy.id, description="rewritten", description_json=new_doc, actor_id=dev.id
    )
    await db_session.commit()

    original = await _fresh(db_session, task.id)
    assert original.description == "rewritten"
    assert original.description_json == new_doc

    rows = (
        await db_session.execute(
            select(TaskActivity).where(
                TaskActivity.task_id == task.id, TaskActivity.action == "description_synced"
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].activity_metadata["source_task_id"] == copy.id

    # Nothing else crossed.
    await SprintTaskService(db_session).update_task(task_id=copy.id, priority="high", actor_id=dev.id)
    await db_session.commit()
    assert (await _fresh(db_session, task.id)).priority == "medium"


@pytest.mark.asyncio
async def test_description_edit_without_sync_stays_put(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    copy = await _move(db_session, task, dst, dev, sync_content=False)
    await db_session.commit()
    await SprintTaskService(db_session).update_task(task_id=copy.id, description="only here", actor_id=dev.id)
    await db_session.commit()
    assert "only here" not in ((await _fresh(db_session, task.id)).description or "")


# ── comments & updates: read through ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_comments_read_through_but_other_history_does_not(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    copy = await _move(db_session, task, dst, dev)
    await db_session.commit()

    service = SprintTaskService(db_session)
    await service.add_comment(task_id=copy.id, comment="done on tech side", actor_id=dev.id)
    await service.update_task(task_id=copy.id, priority="high", actor_id=dev.id)
    await db_session.commit()

    activities, total = await service.get_task_activities(task.id)
    comments = [a for a in activities if a.action == "comment"]
    assert [c.comment for c in comments] == ["done on tech side"]
    assert comments[0].task_id == copy.id, "the row stays where it was written"
    assert not any(a.action == "priority_changed" and a.task_id == copy.id for a in activities)
    assert total == len(activities)


@pytest.mark.asyncio
async def test_work_updates_read_through_with_an_origin_label(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    copy = await _move(db_session, task, dst, dev)
    await db_session.commit()

    updates = WorkUpdateService(db_session)
    theirs = await updates.create_update(ws.id, "task", copy.id, dev.id, "API done")
    mine = await updates.create_update(ws.id, "task", task.id, dev.id, "waiting on vendor")
    await db_session.commit()

    rows, origins = await updates.list_updates_with_origin(ws.id, "task", task.id)
    assert {r.id for r in rows} == {theirs.id, mine.id}
    assert mine.id not in origins
    assert origins[theirs.id] == f"#{copy.task_key}"


# ── attachments: one object, several rows ────────────────────────────────────


@pytest.mark.asyncio
async def test_new_attachment_is_mirrored_and_delete_removes_every_mirror(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    copy = await _move(db_session, task, dst, dev)
    await db_session.commit()

    service = SprintTaskService(db_session)
    row = await service.add_attachment(
        task_id=copy.id, file_name="log.txt", file_url="http://s/log.txt",
        storage_key=f"task-attachments/{copy.id}/log.txt", file_size=3,
        content_type="text/plain", uploaded_by_id=dev.id,
    )
    await db_session.commit()
    mirrors = (
        await db_session.execute(select(TaskAttachment).where(TaskAttachment.task_id == task.id))
    ).scalars().all()
    assert [m.storage_key for m in mirrors] == [row.storage_key]

    # Nothing outside the pair uses the object, so it may go with the rows.
    assert await attachment_object_still_referenced(db_session, row) is False
    await service.delete_attachment(row.id, actor_id=dev.id)
    await db_session.commit()
    left = (
        await db_session.execute(select(TaskAttachment).where(TaskAttachment.storage_key == row.storage_key))
    ).scalars().all()
    assert left == []


@pytest.mark.asyncio
async def test_object_is_kept_while_an_unsynced_task_still_points_at_it(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    dst = await _project(db_session, ws, "Tech")
    other = await _project(db_session, ws, "Elsewhere")
    task = await _task(db_session, ws, src)
    row = await _attach(db_session, task)
    # A plain fork (no sync) made earlier holds a row for the same key.
    stray = await _task(db_session, ws, other)
    db_session.add(TaskAttachment(
        id=str(uuid.uuid4()), task_id=stray.id, file_name=row.file_name,
        file_url=row.file_url, storage_key=row.storage_key,
    ))
    await _move(db_session, task, dst, dev)
    await db_session.commit()
    assert await attachment_object_still_referenced(db_session, row) is True


# ── ticket ↔ task ────────────────────────────────────────────────────────────


async def _ticket(db: AsyncSession, ws: Workspace, task: SprintTask, *, synced: bool = True) -> Ticket:
    form = TicketForm(
        id=str(uuid.uuid4()), workspace_id=ws.id, name="Support",
        slug=f"f-{uuid.uuid4().hex[:6]}", public_url_token=f"t-{uuid.uuid4().hex[:6]}",
    )
    db.add(form)
    await db.flush()
    ticket = Ticket(
        id=str(uuid.uuid4()), form_id=form.id, workspace_id=ws.id, ticket_number=7,
        status=TicketStatus.IN_PROGRESS.value, field_values={"subject": "Cannot log in"},
        linked_task_id=task.id, sync_content_with_task=synced, attachments=[],
    )
    db.add(ticket)
    await db.flush()
    return ticket


@pytest.mark.asyncio
async def test_task_comment_becomes_an_internal_note_on_the_synced_ticket(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    await db_session.commit()

    await SprintTaskService(db_session).add_comment(task_id=task.id, comment="root cause found", actor_id=dev.id)
    await db_session.commit()

    notes = (
        await db_session.execute(select(TicketResponse).where(TicketResponse.ticket_id == ticket.id))
    ).scalars().all()
    assert len(notes) == 1
    assert notes[0].is_internal is True, "a task comment must never be customer-visible"
    assert notes[0].content == "root cause found"
    assert notes[0].synced_from_task_id == task.id


@pytest.mark.asyncio
async def test_ticket_note_becomes_a_comment_on_the_task_and_reads_through_to_its_peer(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    copy = await _move(db_session, task, dst, dev)
    await db_session.commit()

    # The move re-pointed the ticket at the copy (follow_linked_task_to_board),
    # so that is where the note lands; the original reads it through.
    ticket = (
        await db_session.execute(
            select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert ticket.linked_task_id == copy.id

    activity = await sync.mirror_ticket_note_to_task(
        db_session, ticket, "customer confirmed", actor_id=dev.id, ticket_label="SD-7"
    )
    await db_session.commit()
    assert activity is not None and activity.task_id == copy.id
    assert activity.activity_metadata[sync.SYNCED_FROM_TICKET_KEY] == ticket.id

    original_activities, _ = await SprintTaskService(db_session).get_task_activities(task.id)
    assert any(a.comment == "customer confirmed" for a in original_activities)


@pytest.mark.asyncio
async def test_switch_off_stops_the_ticket_side(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task, synced=False)
    await db_session.commit()

    assert await sync.mirror_ticket_note_to_task(db_session, ticket, "x", actor_id=dev.id) is None
    await SprintTaskService(db_session).add_comment(task_id=task.id, comment="y", actor_id=dev.id)
    await db_session.commit()
    notes = (
        await db_session.execute(select(TicketResponse).where(TicketResponse.ticket_id == ticket.id))
    ).scalars().all()
    assert notes == []
    scope = await sync.work_update_scope(db_session, "ticket", ticket.id)
    assert list(scope) == [("ticket", ticket.id)]


@pytest.mark.asyncio
async def test_ticket_upload_appears_on_the_task_and_task_upload_on_the_ticket(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    await db_session.commit()

    entry = {"id": str(uuid.uuid4()), "filename": "form.pdf", "size": 9, "type": "application/pdf",
             "key": f"ticket-attachments/{ticket.id}/form.pdf"}
    created = await sync.mirror_ticket_upload_to_task(db_session, ticket, [entry], uploaded_by_id=dev.id)
    await db_session.commit()
    assert [c.task_id for c in created] == [task.id]
    assert created[0].storage_key == entry["key"]

    row = await SprintTaskService(db_session).add_attachment(
        task_id=task.id, file_name="trace.log", file_url="http://s/trace.log",
        storage_key=f"task-attachments/{task.id}/trace.log", uploaded_by_id=dev.id,
    )
    await db_session.commit()
    fresh = (
        await db_session.execute(
            select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    keys = [e["key"] for e in fresh.attachments]
    assert row.storage_key in keys
    assert next(e for e in fresh.attachments if e["key"] == row.storage_key)["source_task_id"] == task.id

    # Removing it on the task takes the ticket's entry with it.
    await SprintTaskService(db_session).delete_attachment(row.id, actor_id=dev.id)
    await db_session.commit()
    fresh = (
        await db_session.execute(
            select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert row.storage_key not in [e["key"] for e in fresh.attachments]


@pytest.mark.asyncio
async def test_work_update_scope_spans_ticket_and_task_both_ways(db_session: AsyncSession) -> None:
    ws, _dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    await db_session.commit()
    from aexy.services.service_desk_config import display_id, ticket_prefix

    from_task = await sync.work_update_scope(db_session, "task", task.id)
    from_ticket = await sync.work_update_scope(db_session, "ticket", ticket.id)
    # The same id the desk shows in its queue, prefix included.
    prefix = await ticket_prefix(db_session, ws.id)
    assert from_task[("ticket", ticket.id)] == f"ticket {display_id(prefix, 7)}"
    assert from_ticket[("task", task.id)] == f"task #{task.task_key}"


# ── review fixes ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_keep_without_sync_leaves_the_ticket_on_the_original(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    await db_session.commit()

    await _move(db_session, task, dst, dev, source_action="keep", sync_content=False)
    await db_session.commit()
    fresh = (
        await db_session.execute(
            select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert fresh.linked_task_id == task.id, "the original is still the live task; the ticket stays with it"


@pytest.mark.asyncio
async def test_keep_with_sync_still_hands_the_ticket_to_the_new_board(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    await db_session.commit()
    copy = await _move(db_session, task, dst, dev, source_action="keep", sync_content=True)
    await db_session.commit()
    fresh = (
        await db_session.execute(
            select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert fresh.linked_task_id == copy.id


@pytest.mark.asyncio
async def test_resolving_the_link_stops_the_sync(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src)
    copy = await _move(db_session, task, dst, dev)
    await db_session.commit()
    link = (
        await db_session.execute(select(TaskDependency).where(TaskDependency.dependent_task_id == copy.id))
    ).scalar_one()
    link.status = "resolved"
    await db_session.commit()
    assert await sync.synced_task_peers(db_session, task.id) == []


@pytest.mark.asyncio
async def test_deleting_a_conversion_copy_keeps_the_tickets_own_file(db_session: AsyncSession) -> None:
    """A ticket-owned entry (no source_task_id) is not a mirror: the task's copy
    going must not take the requester's file or its object."""
    ws, dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    key = f"ticket-attachments/{ticket.id}/contract.pdf"
    ticket.attachments = [{"id": str(uuid.uuid4()), "filename": "contract.pdf", "size": 5, "type": "application/pdf", "key": key}]
    row = TaskAttachment(
        id=str(uuid.uuid4()), task_id=task.id, file_name="contract.pdf",
        file_url="http://s/contract.pdf", storage_key=key,
    )
    db_session.add(row)
    await db_session.commit()

    assert await attachment_object_still_referenced(db_session, row) is True
    await SprintTaskService(db_session).delete_attachment(row.id, actor_id=dev.id)
    await db_session.commit()
    fresh = (
        await db_session.execute(
            select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert [e["key"] for e in fresh.attachments] == [key]


@pytest.mark.asyncio
async def test_object_kept_while_a_sent_reply_carries_it(db_session: AsyncSession) -> None:
    ws, dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    key = f"ticket-attachments/{ticket.id}/form.pdf"
    # Uploaded on the ticket, mirrored to the task, then sent: the entry now
    # lives on the message, not on the ticket.
    db_session.add(TicketResponse(
        id=str(uuid.uuid4()), ticket_id=ticket.id, author_id=dev.id, content="sent",
        is_internal=False, attachments=[{"id": str(uuid.uuid4()), "filename": "form.pdf", "key": key}],
    ))
    row = TaskAttachment(
        id=str(uuid.uuid4()), task_id=task.id, file_name="form.pdf",
        file_url="http://s/form.pdf", storage_key=key, uploaded_by_id=dev.id,
    )
    db_session.add(row)
    await db_session.commit()
    assert await attachment_object_still_referenced(db_session, row) is True


@pytest.mark.asyncio
async def test_task_mirrors_on_a_ticket_are_internal(db_session: AsyncSession) -> None:
    from aexy.services.service_desk_ticket_service import ServiceDeskTicketService
    from aexy.services.ticket_service import TicketService

    ws, dev = await _workspace(db_session)
    src = await _project(db_session, ws, "Ops")
    task = await _task(db_session, ws, src)
    ticket = await _ticket(db_session, ws, task)
    await db_session.commit()
    row = await SprintTaskService(db_session).add_attachment(
        task_id=task.id, file_name="heap-dump.log", file_url="http://s/heap.log",
        storage_key=f"task-attachments/{task.id}/heap.log", uploaded_by_id=dev.id,
    )
    await db_session.commit()
    fresh = (
        await db_session.execute(
            select(Ticket).where(Ticket.id == ticket.id).execution_options(populate_existing=True)
        )
    ).scalar_one()
    mirror = next(e for e in fresh.attachments if e["key"] == row.storage_key)
    assert sync.is_task_mirror_entry(mirror)

    tickets = TicketService(db_session)
    # Not on the share-link path, not among the sendable uploads…
    assert tickets.find_ticket_attachment(fresh, mirror["id"], include_internal=False) is None
    assert ServiceDeskTicketService._uploaded_attachments(fresh) == []
    # …but a member can still see and open it, labelled as the task's.
    assert tickets.find_ticket_attachment(fresh, mirror["id"], include_internal=True) is not None
    listed = [a for a in ServiceDeskTicketService._detail_attachments(fresh) if a.id == mirror["id"]]
    assert listed and listed[0].source == "task" and listed[0].can_forward is False


def test_every_action_the_service_writes_is_in_the_response_literal() -> None:
    """History fails response validation for any action missing here."""
    import re
    from pathlib import Path
    from typing import get_args

    from aexy.schemas.sprint import TaskActivityAction

    allowed = set(get_args(TaskActivityAction))
    source = Path(__file__).resolve().parents[2] / "src/aexy/services/sprint_task_service.py"
    written = set(re.findall(r'action="([a-z_]+)"', source.read_text()))
    assert written <= allowed, sorted(written - allowed)


@pytest.mark.asyncio
async def test_archiving_the_original_refuses_to_keep_it_in_sync(db_session: AsyncSession) -> None:
    """Archive and "keep in sync" are contradictory instructions.

    An archived task is off every board, so mirroring comments and files into
    it writes them where nobody can read them — and removing an attachment on
    the live side would reach into the archive to delete it there too. The
    sync branch also suppresses the "Moved to" breadcrumb, because the two
    descriptions have to match, so the pair would end up archived *and*
    traceless. The ticked box is ignored rather than honoured.
    """
    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src, description="original text")

    copy = await _move(db_session, task, dst, dev, source_action="archive", sync_content=True)
    await db_session.commit()

    link = (
        await db_session.execute(
            select(TaskDependency).where(TaskDependency.dependent_task_id == copy.id)
        )
    ).scalar_one()
    assert link.sync_content is False

    original = await _fresh(db_session, task.id)
    assert original.is_archived is True
    # The breadcrumb the sync branch would have suppressed is written, so the
    # archived task still says where the work went.
    assert "Moved to" in (original.description or "")
    assert await sync.synced_task_peers(db_session, task.id) == []


@pytest.mark.asyncio
async def test_an_integration_edit_reaches_the_synced_peer(db_session: AsyncSession) -> None:
    """Jira and Linear write `task.description` straight onto the row.

    Propagation lives in `update_task`, which those writes go around — so an
    edit made in Jira landed on one side of a synced pair and the two drifted
    with nothing to say why.
    """
    from aexy.services.content_sync_service import propagate_description

    ws, dev = await _workspace(db_session)
    src, dst = await _project(db_session, ws, "Ops"), await _project(db_session, ws, "Tech")
    task = await _task(db_session, ws, src, description="before")
    copy = await _move(db_session, task, dst, dev, sync_content=True)
    await db_session.commit()

    # What the integration does: assign, flush, then propagate.
    task.description = "edited in Jira"
    await db_session.flush()
    await propagate_description(db_session, task, actor_id=None)
    await db_session.commit()

    assert (await _fresh(db_session, copy.id)).description == "edited in Jira"
    rows = (
        await db_session.execute(
            select(TaskActivity).where(
                TaskActivity.task_id == copy.id,
                TaskActivity.action == "description_synced",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    # Nobody pressed save, so the history row names no actor.
    assert rows[0].actor_id is None

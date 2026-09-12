"""Keep two views of one piece of work saying the same thing.

Two links create a pair that should not drift:

* **A moved task and its original.** Moving a task to another project forks it
  and records a ``task_dependencies`` row of type ``duplicates``. With
  ``sync_content`` set on that row the pair share description, comments and
  attachments.
* **A ticket and the task it was converted into**, through
  ``Ticket.linked_task_id`` while ``Ticket.sync_content_with_task`` is on. The
  pair share internal notes ↔ comments, progress updates and attachments. The
  ticket body is the requester's own words and is never written to from the
  task.

Nothing else is shared. Status, assignee, dates, points and sprint stay with
each board, because the point of the move is that the two boards run the work
independently.

How each kind of content is kept in step:

* **Description** is copied on write (``propagate_description``): the one
  field, two write paths, and every list that renders a task reads its own row.
* **Comments and progress updates** are read through, not copied. The rows stay
  where they were written and the list queries widen to the peers, so an edit
  or a delete happens once and is true everywhere. A ticket note and a task
  comment live in different tables, so that one pair *is* mirrored, with the
  mirror marked so it is never mirrored back.
* **Attachments** are mirrored as rows that point at the *same stored object*.
  Re-uploading would double the storage and give the copies different keys, so
  deleting one would look like it worked while the other still resolved.
  Deleting removes every row sharing the key, and the object only when nothing
  references it any more.

Peer resolution follows the sync links transitively — a task moved twice with
sync on is one group of three — and is bounded, so a pathological chain cannot
make a comment list walk the whole table.
"""

from __future__ import annotations

import logging
from collections import deque
from uuid import uuid4

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.dependency import TaskDependency
from aexy.models.sprint import SprintTask, TaskActivity, TaskAttachment
from aexy.models.ticketing import Ticket, TicketResponse

logger = logging.getLogger(__name__)

# How many linked tasks a group may hold before resolution stops widening. A
# task moved a handful of times is the realistic ceiling; the bound exists so a
# corrupt or adversarial chain of links cannot turn one read into a table walk.
MAX_PEER_GROUP = 25

# Metadata key on a TaskActivity comment that was mirrored from a ticket note.
SYNCED_FROM_TICKET_KEY = "synced_from_ticket_id"


async def synced_task_peers(db: AsyncSession, task_id: str) -> list[str]:
    """Every *live* task kept in sync with ``task_id``, excluding itself.

    Walks ``duplicates`` links with ``sync_content`` in both directions,
    transitively, up to ``MAX_PEER_GROUP`` members.

    An archived task is never a peer. Archiving and syncing are contradictory:
    an archived task is off every board, so mirroring comments and files into
    it writes them where nobody can read them, and deleting an attachment on
    the live side would reach into the archive to delete it there too. The
    move dialog refuses the combination up front, but a task can be archived
    at any time afterwards — through the board, the API, a bulk action — so
    the rule belongs here, in the one function every read and write goes
    through, rather than at whichever door happened to be noticed.

    The walk still *passes through* an archived task: A moved to B and B moved
    to C, with B later archived, leaves A and C two live tasks that were
    deliberately linked. Only the archived member drops out of the group.
    """
    seen: set[str] = {str(task_id)}
    queue: deque[str] = deque([str(task_id)])
    while queue and len(seen) < MAX_PEER_GROUP:
        current = queue.popleft()
        rows = (
            await db.execute(
                select(
                    TaskDependency.dependent_task_id, TaskDependency.blocking_task_id
                ).where(
                    TaskDependency.dependency_type == "duplicates",
                    TaskDependency.sync_content.is_(True),
                    # A link the user has resolved is an unlink: the task detail
                    # stops listing it, so the sync stops with it.
                    TaskDependency.status == "active",
                    or_(
                        TaskDependency.dependent_task_id == current,
                        TaskDependency.blocking_task_id == current,
                    ),
                )
            )
        ).all()
        for dependent_id, blocking_id in rows:
            for other in (str(dependent_id), str(blocking_id)):
                if other not in seen:
                    seen.add(other)
                    queue.append(other)
    seen.discard(str(task_id))
    if not seen:
        return []
    live = (
        (
            await db.execute(
                select(SprintTask.id).where(
                    SprintTask.id.in_(sorted(seen)),
                    SprintTask.is_archived.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    return sorted(str(row) for row in live)


async def synced_tickets_for_tasks(
    db: AsyncSession, task_ids: list[str]
) -> list[Ticket]:
    """Tickets linked to any of ``task_ids`` with the sync switch on."""
    if not task_ids:
        return []
    return list(
        (
            await db.execute(
                select(Ticket).where(
                    Ticket.linked_task_id.in_(task_ids),
                    Ticket.sync_content_with_task.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )


def synced_task_id_for_ticket(ticket: Ticket) -> str | None:
    """The task a ticket syncs with, or None when there is none or it is off."""
    if ticket.linked_task_id and ticket.sync_content_with_task:
        return str(ticket.linked_task_id)
    return None


async def task_group(db: AsyncSession, task_id: str) -> list[str]:
    """``task_id`` together with every task it is kept in sync with."""
    return [str(task_id), *await synced_task_peers(db, task_id)]


# ── description ──────────────────────────────────────────────────────────────


async def propagate_description(
    db: AsyncSession, source: SprintTask, *, actor_id: str | None
) -> list[SprintTask]:
    """Copy ``source``'s description onto every synced peer.

    Each peer gets a ``description_synced`` history row naming where the text
    came from, so its History tab does not show the description changing with
    nobody having edited it. Peers whose text already matches are left alone.
    """
    peer_ids = await synced_task_peers(db, str(source.id))
    if not peer_ids:
        return []
    peers = list(
        (await db.execute(select(SprintTask).where(SprintTask.id.in_(peer_ids))))
        .scalars()
        .all()
    )
    changed: list[SprintTask] = []
    for peer in peers:
        if (
            peer.description == source.description
            and peer.description_json == source.description_json
        ):
            continue
        peer.description = source.description
        peer.description_json = source.description_json
        db.add(
            TaskActivity(
                id=str(uuid4()),
                task_id=peer.id,
                action="description_synced",
                actor_id=actor_id,
                field_name="description",
                activity_metadata={
                    "source_task_id": str(source.id),
                    "source_task_key": source.task_key,
                    "source_task_team_id": str(source.team_id) if source.team_id else None,
                },
            )
        )
        changed.append(peer)
    if changed:
        await db.flush()
    return changed


# ── attachments ──────────────────────────────────────────────────────────────


def is_task_mirror_entry(entry: object) -> bool:
    """Is this ``Ticket.attachments`` entry a mirror of a task's file?

    Ownership follows provenance: an entry carrying ``source_task_id`` was put
    there by the sync and goes when the task's row goes; an entry without one
    is the ticket's own file (the requester's, or an upload to send) and a
    task deleting its copy must not take it. The desk also treats mirrors as
    internal — never offered for sending, never served on a share link.
    """
    return isinstance(entry, dict) and bool(entry.get("source_task_id"))


def _ticket_entry_for(attachment: TaskAttachment, *, task_id: str) -> dict:
    """A ``Ticket.attachments`` entry pointing at the task's stored object."""
    return {
        "id": str(uuid4()),
        "filename": attachment.file_name,
        "size": attachment.file_size or 0,
        "type": attachment.content_type or "application/octet-stream",
        "key": attachment.storage_key,
        "source_task_id": task_id,
    }


async def mirror_attachment(
    db: AsyncSession, attachment: TaskAttachment, *, peer_ids: list[str] | None = None
) -> list[TaskAttachment]:
    """Put ``attachment`` on every synced peer task and synced ticket.

    The new rows share the storage key — one object, several rows. Peers that
    already hold a row for the key are skipped, so mirroring is idempotent.
    Nothing is mirrored for a row without a key (legacy URL-only rows): there
    is nothing durable for the copy to point at.
    """
    if not attachment.storage_key:
        return []
    task_id = str(attachment.task_id)
    if peer_ids is None:
        peer_ids = await synced_task_peers(db, task_id)
    created: list[TaskAttachment] = []
    if peer_ids:
        existing = set(
            (
                await db.execute(
                    select(TaskAttachment.task_id).where(
                        TaskAttachment.task_id.in_(peer_ids),
                        TaskAttachment.storage_key == attachment.storage_key,
                    )
                )
            )
            .scalars()
            .all()
        )
        for peer_id in peer_ids:
            if peer_id in {str(e) for e in existing}:
                continue
            row = TaskAttachment(
                id=str(uuid4()),
                task_id=peer_id,
                file_name=attachment.file_name,
                file_url=attachment.file_url,
                storage_key=attachment.storage_key,
                file_size=attachment.file_size,
                content_type=attachment.content_type,
                uploaded_by_id=attachment.uploaded_by_id,
            )
            db.add(row)
            created.append(row)

    for ticket in await synced_tickets_for_tasks(db, [task_id, *peer_ids]):
        entries = list(ticket.attachments or [])
        if any(
            isinstance(e, dict) and e.get("key") == attachment.storage_key
            for e in entries
        ):
            continue
        entries.append(_ticket_entry_for(attachment, task_id=task_id))
        # Reassigned so SQLAlchemy sees the JSONB change.
        ticket.attachments = entries

    if created or peer_ids:
        await db.flush()
    return created


async def mirror_ticket_upload_to_task(
    db: AsyncSession, ticket: Ticket, entries: list[dict], *, uploaded_by_id: str | None
) -> list[TaskAttachment]:
    """Files uploaded to a ticket appear on its synced task (and that task's peers)."""
    task_id = synced_task_id_for_ticket(ticket)
    if task_id is None:
        return []
    group = await task_group(db, task_id)
    created: list[TaskAttachment] = []
    for entry in entries:
        key = entry.get("key") if isinstance(entry, dict) else None
        if not key:
            continue
        held = {
            str(t)
            for t in (
                await db.execute(
                    select(TaskAttachment.task_id).where(
                        TaskAttachment.task_id.in_(group),
                        TaskAttachment.storage_key == key,
                    )
                )
            )
            .scalars()
            .all()
        }
        for tid in group:
            if tid in held:
                continue
            from aexy.services.task_attachment_service import attachment_download_url

            attachment_id = str(uuid4())
            row = TaskAttachment(
                id=attachment_id,
                task_id=tid,
                file_name=str(entry.get("filename") or "attachment")[:500],
                file_url=attachment_download_url(attachment_id)[:2000],
                storage_key=str(key)[:1024],
                file_size=entry.get("size") or None,
                content_type=entry.get("type") or None,
                uploaded_by_id=uploaded_by_id,
            )
            db.add(row)
            created.append(row)
    if created:
        await db.flush()
    return created


async def remove_attachment_everywhere(
    db: AsyncSession, attachment: TaskAttachment
) -> None:
    """Drop every mirror of ``attachment`` from its synced peers and tickets.

    Only *mirrors* go: peer rows sharing the key, and ticket entries the sync
    wrote (``is_task_mirror_entry``). A ticket's own file that the task holds a
    conversion copy of stays on the ticket. Whether the stored object may be
    deleted is a separate question — ``task_attachment_service.
    attachment_object_still_referenced`` — and the row passed in is not
    deleted here; the caller owns both.
    """
    key = attachment.storage_key
    if not key:
        return
    task_id = str(attachment.task_id)
    peer_ids = await synced_task_peers(db, task_id)
    if peer_ids:
        mirrors = list(
            (
                await db.execute(
                    select(TaskAttachment).where(
                        TaskAttachment.task_id.in_(peer_ids),
                        TaskAttachment.storage_key == key,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in mirrors:
            await db.delete(row)
    for ticket in await synced_tickets_for_tasks(db, [task_id, *peer_ids]):
        entries = list(ticket.attachments or [])
        kept = [
            e
            for e in entries
            if not (is_task_mirror_entry(e) and e.get("key") == key)
        ]
        if len(kept) != len(entries):
            ticket.attachments = kept
    await db.flush()


async def remove_ticket_upload_from_task(
    db: AsyncSession, ticket: Ticket, key: str | None
) -> bool:
    """A file removed from a ticket leaves its synced task too.

    Returns True when a task row outside the synced group still points at the
    object, so the caller must not delete it from storage.
    """
    if not key:
        return False
    task_id = synced_task_id_for_ticket(ticket)
    if task_id is not None:
        group = await task_group(db, task_id)
        rows = list(
            (
                await db.execute(
                    select(TaskAttachment).where(
                        TaskAttachment.task_id.in_(group),
                        TaskAttachment.storage_key == key,
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            await db.delete(row)
        await db.flush()
    remaining = (
        await db.execute(select(TaskAttachment.id).where(TaskAttachment.storage_key == key))
    ).first()
    return remaining is not None


# ── comments ↔ notes ─────────────────────────────────────────────────────────


async def mirror_task_comment_to_tickets(
    db: AsyncSession, task: SprintTask, comment: str, *, actor_id: str | None
) -> list[TicketResponse]:
    """A task comment becomes an internal note on every synced ticket.

    Internal, always: a note the requester can see is an email, and nothing a
    developer types on a board should leave the building by accident.
    """
    tickets = await synced_tickets_for_tasks(db, await task_group(db, str(task.id)))
    created: list[TicketResponse] = []
    for ticket in tickets:
        note = TicketResponse(
            id=str(uuid4()),
            ticket_id=ticket.id,
            author_id=actor_id,
            content=comment,
            is_internal=True,
            synced_from_task_id=str(task.id),
        )
        db.add(note)
        created.append(note)
    if created:
        await db.flush()
    return created


async def mirror_ticket_note_to_task(
    db: AsyncSession,
    ticket: Ticket,
    content: str,
    *,
    actor_id: str | None,
    ticket_label: str | None = None,
) -> TaskActivity | None:
    """An internal note written on a ticket becomes a comment on its synced task.

    Written to the linked task only; tasks kept in sync with *that* one read it
    through like any other comment.
    """
    task_id = synced_task_id_for_ticket(ticket)
    if task_id is None:
        return None
    activity = TaskActivity(
        id=str(uuid4()),
        task_id=task_id,
        action="comment",
        actor_id=actor_id,
        comment=content,
        activity_metadata={
            SYNCED_FROM_TICKET_KEY: str(ticket.id),
            "ticket_label": ticket_label,
        },
    )
    db.add(activity)
    await db.flush()
    return activity


# ── progress updates ─────────────────────────────────────────────────────────


async def work_update_scope(
    db: AsyncSession, entity_type: str, entity_id: str
) -> dict[tuple[str, str], str | None]:
    """Every (entity_type, entity_id) whose updates belong on this entity's list.

    Maps each to a label for the ones that are not the entity itself — the
    task key or the ticket number — so the panel can say where an update was
    written. The entity itself maps to None.
    """
    # Column selects throughout: a full SprintTask row drags fourteen selectin
    # relationships behind it (its whole history and attachment list among
    # them) and this runs on every Updates panel open. Labels only need three.
    from aexy.services.service_desk_config import display_id, ticket_prefix

    scope: dict[tuple[str, str], str | None] = {(entity_type, str(entity_id)): None}

    async def label_tasks(task_ids: list[str], prefix: str) -> None:
        rows = await db.execute(
            select(SprintTask.id, SprintTask.task_key, SprintTask.title).where(
                SprintTask.id.in_(task_ids)
            )
        )
        for tid, key, title in rows:
            scope[("task", str(tid))] = f"{prefix}#{key}" if key is not None else title

    if entity_type == "task":
        group = await task_group(db, entity_id)
        peers = [t for t in group if t != str(entity_id)]
        if peers:
            await label_tasks(peers, "")
        tickets = (
            await db.execute(
                select(Ticket.id, Ticket.ticket_number, Ticket.workspace_id).where(
                    Ticket.linked_task_id.in_(group),
                    Ticket.sync_content_with_task.is_(True),
                )
            )
        ).all()
        for tid, number, workspace_id in tickets:
            # The same id the desk shows everywhere else (prefix included), so
            # what the panel names can be found in the queue.
            prefix = await ticket_prefix(db, str(workspace_id))
            scope[("ticket", str(tid))] = f"ticket {display_id(prefix, number)}"
    elif entity_type == "ticket":
        row = (
            await db.execute(
                select(Ticket.linked_task_id, Ticket.sync_content_with_task).where(
                    Ticket.id == entity_id
                )
            )
        ).first()
        if row is not None and row[0] and row[1]:
            await label_tasks(await task_group(db, str(row[0])), "task ")
    return scope

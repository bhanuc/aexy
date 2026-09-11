"""Progress updates on tasks and tickets.

See ``models/work_update.py`` for why this is separate from comments and from
the activity log.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.work_update import WORK_UPDATE_ENTITY_TYPES, WorkUpdate
from aexy.services.activity_logger import log_activity

logger = logging.getLogger(__name__)

MAX_BODY_CHARS = 5000


class WorkUpdateService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── entity resolution ────────────────────────────────────────────────

    async def _assert_entity_in_workspace(
        self, workspace_id: str, entity_type: str, entity_id: str
    ) -> None:
        """Verify the target exists *in this workspace* before writing.

        Without this the workspace id comes from the URL and the entity id from
        the body, so a member of workspace A could hang an update off a task in
        workspace B — and then read it back, since the list path filters on the
        same unverified pair. The check is the same one
        ``api/entity_activity.py`` makes for its own polymorphic writes.
        """
        if entity_type not in WORK_UPDATE_ENTITY_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Progress updates are not supported for {entity_type!r}. "
                    f"Expected one of: {', '.join(sorted(WORK_UPDATE_ENTITY_TYPES))}"
                ),
            )

        # Lazy imports: both modules import service code transitively.
        if entity_type == "task":
            from aexy.models.sprint import SprintTask as model
        else:
            from aexy.models.ticketing import Ticket as model

        found = await self.db.execute(
            select(model.id).where(
                model.id == entity_id,
                model.workspace_id == workspace_id,
            )
        )
        if found.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"{entity_type.capitalize()} not found",
            )

    @staticmethod
    def _clean_body(body: str) -> str:
        cleaned = (body or "").strip()
        if not cleaned:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An update needs some text",
            )
        if len(cleaned) > MAX_BODY_CHARS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"An update is limited to {MAX_BODY_CHARS} characters",
            )
        return cleaned

    # ── reads ────────────────────────────────────────────────────────────

    async def list_updates(
        self, workspace_id: str, entity_type: str, entity_id: str
    ) -> list[WorkUpdate]:
        """Newest first — the current state of the work is the thing you want
        to read, and the history of it is below."""
        await self._assert_entity_in_workspace(workspace_id, entity_type, entity_id)
        updates, _ = await self.list_updates_with_origin(
            workspace_id, entity_type, entity_id
        )
        return updates

    async def list_updates_with_origin(
        self, workspace_id: str, entity_type: str, entity_id: str
    ) -> tuple[list[WorkUpdate], dict[str, str]]:
        """The entity's updates plus those read through from what it syncs with.

        A task converted from a ticket, or moved to another board with content
        sync on, is one piece of work with several rows; a standup note written
        on any of them is the same fact. Rows stay where they were written —
        this widens the read rather than copying — so an edit or delete happens
        once. The second value maps update id → label of where it was written,
        for the ones that were not written here.
        """
        from aexy.services.content_sync_service import work_update_scope

        scope = await work_update_scope(self.db, entity_type, entity_id)
        clauses = [
            (WorkUpdate.entity_type == et) & (WorkUpdate.entity_id == eid)
            for (et, eid) in scope
        ]
        result = await self.db.execute(
            select(WorkUpdate)
            .where(WorkUpdate.workspace_id == workspace_id, or_(*clauses))
            .order_by(WorkUpdate.created_at.desc())
        )
        updates = list(result.scalars().all())
        origins = {
            str(u.id): label
            for u in updates
            if (label := scope.get((u.entity_type, str(u.entity_id)))) is not None
        }
        return updates, origins

    async def latest_by_entity(
        self, workspace_id: str, entity_type: str, entity_ids: list[str]
    ) -> dict[str, WorkUpdate]:
        """Most recent update per entity, for a whole board in one query.

        Used to show "last update 3 days ago" on cards. Done as a single
        fetch-and-fold rather than a correlated subquery per card because a
        board renders a few hundred at once; the index on
        (entity_type, entity_id, created_at) keeps the scan tight.
        """
        if not entity_ids:
            return {}
        result = await self.db.execute(
            select(WorkUpdate)
            .where(
                WorkUpdate.workspace_id == workspace_id,
                WorkUpdate.entity_type == entity_type,
                WorkUpdate.entity_id.in_(entity_ids),
            )
            .order_by(WorkUpdate.created_at.desc())
        )
        latest: dict[str, WorkUpdate] = {}
        for update in result.scalars().all():
            # Descending order means the first row seen per entity is its newest.
            latest.setdefault(str(update.entity_id), update)
        return latest

    async def get_update(self, workspace_id: str, update_id: str) -> WorkUpdate:
        result = await self.db.execute(
            select(WorkUpdate).where(
                WorkUpdate.id == update_id,
                WorkUpdate.workspace_id == workspace_id,
            )
        )
        update = result.scalar_one_or_none()
        if update is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Update not found"
            )
        return update

    # ── writes ───────────────────────────────────────────────────────────

    async def create_update(
        self,
        workspace_id: str,
        entity_type: str,
        entity_id: str,
        author_id: str,
        body: str,
        mentioned_user_ids: list[str] | None = None,
    ) -> WorkUpdate:
        await self._assert_entity_in_workspace(workspace_id, entity_type, entity_id)
        cleaned = self._clean_body(body)

        update = WorkUpdate(
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=entity_id,
            author_id=author_id,
            body=cleaned,
        )
        self.db.add(update)
        await self.db.flush()

        # Mirror the *event* into the activity log so an update shows up in the
        # History tab and the workspace feed. Deliberately no body here: the
        # update is editable and the log is not, so copying the text would leave
        # the feed quoting a version that no longer exists.
        await log_activity(
            self.db,
            workspace_id=workspace_id,
            entity_type=entity_type,
            entity_id=str(entity_id),
            activity_type="progress_updated",
            actor_id=author_id,
            title="Posted a progress update",
        )

        await self.db.refresh(update)

        if mentioned_user_ids:
            await self._notify_mentions(
                workspace_id, entity_type, entity_id, author_id, cleaned, mentioned_user_ids
            )
        return update

    async def _notify_mentions(
        self,
        workspace_id: str,
        entity_type: str,
        entity_id: str,
        author_id: str,
        body: str,
        mentioned_user_ids: list[str],
    ) -> None:
        """Tell each @-mentioned member, except the author, and only members.

        The ids arrive from the client, so each is checked against the
        workspace before anyone is notified — otherwise a body could be used
        to ping arbitrary accounts.
        """
        from aexy.models.developer import Developer
        from aexy.models.workspace import WorkspaceMember
        from aexy.services.notification_service import notify_mention

        wanted = {str(u) for u in mentioned_user_ids if str(u) != str(author_id)}
        if not wanted:
            return
        members = {
            str(m)
            for m in (
                await self.db.execute(
                    select(WorkspaceMember.developer_id).where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.developer_id.in_(wanted),
                        WorkspaceMember.status == "active",
                    )
                )
            ).scalars()
        }
        if not members:
            return
        author = await self.db.get(Developer, author_id)
        author_name = (author.name if author and author.name else None) or "Someone"
        if entity_type == "task":
            from aexy.models.sprint import SprintTask

            task = await self.db.get(SprintTask, entity_id)
            action_url = (
                f"/sprints/{task.team_id}/board?task={entity_id}"
                if task is not None and task.team_id
                else f"/sprints?task={entity_id}"
            )
            label = "task update"
        else:
            action_url = f"/service-desk/tickets/{entity_id}"
            label = "ticket update"
        snippet = body if len(body) <= 100 else body[:100] + "..."
        for uid in sorted(members):
            try:
                await notify_mention(
                    db=self.db,
                    mentioned_user_id=uid,
                    mentioner_name=author_name,
                    entity_type=label,
                    entity_id=str(entity_id),
                    action_url=action_url,
                    snippet=snippet,
                )
            except Exception:  # a failed ping must not lose the update
                logger.exception("Mention notification for %s failed", uid)

    async def edit_update(
        self, workspace_id: str, update_id: str, requester_id: str, body: str
    ) -> WorkUpdate:
        """Only the author may reword their own update.

        Not an admin override: an update is a statement attributed to a person,
        and letting someone else rewrite it under that person's name is worse
        than leaving a wrong one standing. Admins can delete (below).
        """
        update = await self.get_update(workspace_id, update_id)
        if str(update.author_id) != str(requester_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author can edit an update",
            )
        update.body = self._clean_body(body)
        update.edited_at = datetime.now(timezone.utc)
        await self.db.flush()
        await self.db.refresh(update)
        return update

    async def delete_update(
        self,
        workspace_id: str,
        update_id: str,
        requester_id: str,
        requester_is_admin: bool = False,
    ) -> None:
        update = await self.get_update(workspace_id, update_id)
        if str(update.author_id) != str(requester_id) and not requester_is_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only the author or a workspace admin can delete an update",
            )
        await self.db.delete(update)
        await self.db.flush()

    async def delete_for_entity(
        self, workspace_id: str, entity_type: str, entity_id: str
    ) -> int:
        """Drop every update for an entity that is being hard-deleted.

        There is no FK to cascade from — the target lives in one of two tables —
        so a deleted task would otherwise leave its updates behind, and a new
        task that reused the id (restore-from-backup, re-import) would inherit
        someone else's status notes.
        """
        result = await self.db.execute(
            select(WorkUpdate).where(
                WorkUpdate.workspace_id == workspace_id,
                WorkUpdate.entity_type == entity_type,
                WorkUpdate.entity_id == entity_id,
            )
        )
        orphans = list(result.scalars().all())
        for orphan in orphans:
            await self.db.delete(orphan)
        if orphans:
            await self.db.flush()
        return len(orphans)

"""Ticket numbers, allocated in one place.

`migrate_atomic_issue_keys` replaced `MAX(ticket_number) + 1` with a counter on
the workspace row, because reading a number in one statement and writing it in
another lets two concurrent submissions pick the same one — and `tickets` has a
unique constraint on (workspace_id, ticket_number), so that surfaced as a 500 on
a public form.

Only one of the four places that create tickets was moved onto the counter.
The other three — form submissions with `auto_create_ticket`, alert ingestion
and uptime incidents — kept counting, which left them racy *and* made them
advance `MAX(ticket_number)` without advancing the counter. Once those drift
apart the fixed path is the one that breaks: its next allocation returns a
number the counting paths already used, and every public-form submission 500s
until the counter climbs back past the high-water mark.

So the allocation lives here, and all four callers use it.
"""

from __future__ import annotations

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from aexy.models.workspace import Workspace


async def next_ticket_number(db: AsyncSession, workspace_id: str) -> int:
    """Allocate the next ticket number for a workspace.

    The UPDATE...RETURNING locks the workspace row, so concurrent submissions
    serialize on it and get distinct numbers — the same mechanism as
    `SprintTask.task_key` and the bug and story keys.

    `next_ticket_number` holds the value to assign NEXT, so a fresh workspace's
    first ticket is #1 and the counter becomes 2.

    Raises:
        ValueError: if the workspace does not exist.
    """
    row = (
        await db.execute(
            update(Workspace)
            .where(Workspace.id == workspace_id)
            .values(next_ticket_number=Workspace.next_ticket_number + 1)
            .returning(Workspace.next_ticket_number)
        )
    ).fetchone()
    if row is None:
        raise ValueError(f"Workspace {workspace_id} does not exist")
    return int(row[0]) - 1

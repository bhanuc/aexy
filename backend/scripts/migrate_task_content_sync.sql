-- Content sync between a moved task and its original, and between a ticket and
-- the task it was converted into.
--
-- Moving a task to another project forks it: a new row on the destination board,
-- linked back through `task_dependencies` as "duplicates". Until now the two
-- then drifted — a comment on one was invisible from the other, and a file
-- attached to the copy never reached the original. The link now carries a flag
-- saying the pair keep their description, comments and attachments identical.
-- Nothing else is shared; each board still runs its own status, assignee,
-- dates and points.
--
-- Existing links stay unsynced: they were made under the old contract, where
-- the source was closed and the copy was the only live one, so there is
-- nothing to reconcile and switching them on would start writing into
-- archived rows.
ALTER TABLE task_dependencies
    ADD COLUMN IF NOT EXISTS sync_content BOOLEAN NOT NULL DEFAULT FALSE;

-- A ticket and its linked task are the same piece of work seen from two desks,
-- so the pair default to syncing: an internal note on the ticket becomes a
-- comment on the task and vice versa, progress updates read across, and a file
-- attached on either side appears on both. The ticket body — the requester's
-- own words — is never part of this. Defaults on for the links that already
-- exist, because the link is live on both sides (the ticket is open and the
-- task is being worked); the ticket page has a switch to turn it off.
ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS sync_content_with_task BOOLEAN NOT NULL DEFAULT TRUE;

-- An internal note that is the mirror of a task comment records which task it
-- came from, so the desk can label it and never mirror it back.
ALTER TABLE ticket_responses
    ADD COLUMN IF NOT EXISTS synced_from_task_id UUID
        REFERENCES sprint_tasks(id) ON DELETE SET NULL;

SELECT
    (SELECT count(*) FROM task_dependencies WHERE dependency_type = 'duplicates') AS duplicate_links_existing,
    (SELECT count(*) FROM tickets WHERE linked_task_id IS NOT NULL) AS tickets_linked_to_a_task;

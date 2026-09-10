-- Migration: index the manual-ticket logger, and priority for the desk's queue
--
-- Two indexes, both for predicates that landed on the hot ticket-list path.
--
-- 1. `field_values ->> 'logged_by_id'`
--
--    Row-level visibility now admits a ticket to whoever logged it, so that the
--    operator who took the call can still attach the file to it — the attachment
--    upload is a second, scope-checked request and it used to 404 on the ticket
--    its own author had just created. That clause is in
--    `resolve_scope_clause`, which means every ticket list, count, CSV export
--    and by-id check for a caller without full desk view now carries a JSONB
--    path comparison. Unindexed, it is a scan per query.
--
--    Partial, because only manual tickets carry the key at all: a phone/WhatsApp
--    ticket is a few percent of the table (12 of 314 on the desk this was found
--    on), so the index stays small and the planner can still use it for the
--    equality it is asked.
--
-- 2. `priority`
--
--    The desk gained a priority field, filter and sort. The column already has
--    `index=True` on the model, so this only covers the composite the list
--    actually orders by — workspace first, because every query is scoped to one.
--
-- Both are IF NOT EXISTS and CONCURRENTLY-free: the runner wraps a migration in
-- a transaction, and these tables are small enough that a brief lock is cheaper
-- than the bookkeeping of running them outside one.

CREATE INDEX IF NOT EXISTS idx_tickets_logged_by
ON tickets ((field_values ->> 'logged_by_id'))
WHERE field_values ? 'logged_by_id';

CREATE INDEX IF NOT EXISTS idx_tickets_workspace_priority
ON tickets (workspace_id, priority)
WHERE priority IS NOT NULL;

-- Resync `workspaces.next_ticket_number` with the tickets that actually exist.
--
-- `migrate_atomic_issue_keys` moved ticket numbering onto a counter on the
-- workspace row and backfilled it correctly. But only one of the five places
-- that create tickets was moved onto that counter; form submissions with
-- `auto_create_ticket`, alert ingestion, uptime incidents and service-desk
-- intake all kept doing `MAX(ticket_number) + 1`.
--
-- Every ticket those four created advanced the high-water mark without
-- advancing the counter. Once they drift apart it is the *fixed* path that
-- breaks: the allocator hands out a number one of the counting paths already
-- used, `uq_ticket_number` rejects the insert, and the public form answers 500
-- — on every submission, until the counter climbs back past the high-water
-- mark on its own.
--
-- The code fix points all five at the shared allocator. This repairs the
-- workspaces the counting paths already desynchronised; without it they keep
-- failing after the deploy.
--
-- GREATEST, so a workspace whose counter is already ahead (tickets deleted
-- since) never goes backwards and never reissues a number.
UPDATE workspaces w
   SET next_ticket_number = GREATEST(
       w.next_ticket_number,
       COALESCE((
           SELECT MAX(t.ticket_number) FROM tickets t WHERE t.workspace_id = w.id
       ), 0) + 1
   );

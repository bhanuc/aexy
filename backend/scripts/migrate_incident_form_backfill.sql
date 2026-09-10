-- Migration: give alert tickets a form whose fields they actually populate
--
-- `AlertIngestionService._resolve_form_id` prefers a form seeded from the
-- `incident_auto` template, because its field keys mirror exactly what the
-- ingestion writes into `field_values`. Failing that it falls back to *the
-- oldest active form of any kind*, which keeps the alert rather than dropping
-- it but lands the ticket on a form with no field for `service_name`,
-- `severity`, `alert_name`, `log_context` or `trace_links`. Every piece of
-- context the alert carried then renders as nothing, and the integration reads
-- as broken when it is only unconfigured.
--
-- That is what happened on the workspace this was found on: no `incident_auto`
-- form existed, so three OpenObserve tickets landed on the *Service Desk* form
-- (the oldest, by twelve days) and showed a title and nothing else.
--
-- New integrations now provision the form on connect
-- (`AlertIntegrationService._ensure_incident_form`). This handles the tickets
-- that already exist.
--
-- Deliberately narrow. It repoints only rows that
--   * are alert-sourced (`source` matches a known provider), and
--   * sit on a form that is NOT an `incident_auto` form, and
--   * belong to a workspace that HAS one.
-- A workspace with no incident form is left completely alone — inventing a form
-- here would mean creating rows this migration cannot fill in properly (fields,
-- ordering, a `created_by_id`), and the service layer does that better on the
-- next integration connect. Nothing is deleted and no `field_values` are
-- touched; only `form_id` moves.

-- One statement, so a workspace with several alert integrations cannot get a
-- partial repoint. `DISTINCT ON` picks the oldest incident form per workspace,
-- matching the service layer's own `ORDER BY created_at LIMIT 1`.
WITH incident_forms AS (
    SELECT DISTINCT ON (workspace_id)
           workspace_id,
           id AS form_id
    FROM ticket_forms
    WHERE template_type = 'incident_auto'
      AND is_active = true
    ORDER BY workspace_id, created_at
)
UPDATE tickets AS t
SET form_id = f.form_id,
    updated_at = NOW()
FROM incident_forms AS f
WHERE t.workspace_id = f.workspace_id
  AND t.form_id <> f.form_id
  -- The provider slugs `AlertProvider` defines. Matched explicitly rather than
  -- by "not a form submission", so a ticket from some future non-alert source
  -- is never swept onto the incident form by accident.
  AND t.source IN ('openobserve', 'grafana', 'datadog', 'sentry', 'generic')
  -- Never move a ticket that is already on an incident form, even a second one.
  AND NOT EXISTS (
      SELECT 1
      FROM ticket_forms AS current
      WHERE current.id = t.form_id
        AND current.template_type = 'incident_auto'
  );

-- The sort column for the alert history screen, and the only one of the four
-- filterable columns on `alert_events` without an index (integration_id,
-- workspace_id, fingerprint and action_taken all have one). A workspace-wide
-- history orders by this over every event ever received.
CREATE INDEX IF NOT EXISTS idx_alert_events_workspace_received
ON alert_events (workspace_id, received_at DESC);

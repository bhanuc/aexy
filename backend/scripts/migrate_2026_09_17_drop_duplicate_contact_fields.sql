-- Every Forms module template seeded its own "Email" field, and the two CRM
-- templates a "Full Name" as well. The public page renders the contact block —
-- Your Name, Email Address — above the designed fields, so a support form
-- created from a template asked for an email twice, in two different boxes,
-- and stored the answers in two different places.
--
-- The templates no longer seed them. This removes the duplicates from the
-- forms already created from a template.
--
-- Scope is deliberately narrow:
--   * only forms with a template_type — a field somebody added by hand is
--     theirs, however much it looks like a duplicate;
--   * only the exact keys and types the templates seeded ('email'/email,
--     'name'/text), not anything merely named similarly;
--   * only where the form actually collects that contact field, so a form
--     that has turned the contact block off keeps the field that is now its
--     only way to ask.
--
-- Submitted answers are NOT touched: they live in `form_submissions.data` and
-- `tickets.field_values` as JSONB, keyed by field_key, and deleting a field
-- definition leaves them exactly where they are. What is lost is the label —
-- an old answer under `email` renders as "email" rather than "Email" in views
-- that read labels from the form. That is the trade this migration makes.

DELETE FROM form_fields f
 USING forms fo
 WHERE f.form_id = fo.id
   AND fo.template_type IS NOT NULL
   AND (
        (f.field_key = 'email' AND f.field_type = 'email' AND fo.collect_email)
     OR (f.field_key = 'name'  AND f.field_type = 'text'  AND fo.collect_name)
   );

-- Positions are left as they are: `position` only orders fields and the page
-- sorts by it, so a gap is invisible.

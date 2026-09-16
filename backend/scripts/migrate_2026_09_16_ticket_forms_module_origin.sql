-- A ticket can come from either form system, and they are different tables.
--
-- `tickets.form_id` is a NOT NULL foreign key to `ticket_forms`. The Forms
-- module's submission handler wrote its own `forms.id` into that column, which
-- `tickets_form_id_fkey` rejected — so every submission to a Forms module form
-- with `auto_create_ticket` enabled answered 500, on every attempt, for the
-- entire life of the feature. Nothing was ever written, so there is no bad data
-- to repair: the constraint refused all of it.
--
-- `form_id` therefore becomes nullable and gains a sibling pointing at the
-- other table. A CHECK keeps exactly one of them set, so relaxing NOT NULL does
-- not quietly allow a ticket that belongs to no form at all.

-- ON DELETE RESTRICT, deliberately unlike `tickets.form_id`, which cascades.
-- Nothing has ever pointed at `forms.id` from `tickets`, so there is no
-- precedent here to preserve — only one to decline to extend. A Forms module
-- form is deleted with one click from a list page, and the tickets it raised
-- carry replies, SLA clocks and share links. `forms_service.delete_form`
-- refuses with a count rather than letting the database quietly oblige.
--
-- ON DELETE SET NULL is not an option: it would leave both form columns null
-- and violate ck_ticket_exactly_one_form below.
ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS forms_form_id UUID REFERENCES forms(id) ON DELETE RESTRICT;

-- Stated rather than assumed: an environment that ran an earlier cut of this
-- branch has the column with ON DELETE CASCADE, and ADD COLUMN IF NOT EXISTS
-- above would leave it that way. Re-point the constraint so the delete rule is
-- whatever this file says it is, not whatever ran first.
DO $$
DECLARE
    con_name TEXT;
BEGIN
    SELECT c.conname INTO con_name
      FROM pg_constraint c
      JOIN pg_attribute a
        ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
     WHERE c.conrelid = 'tickets'::regclass
       AND c.contype = 'f'
       AND a.attname = 'forms_form_id'
       AND c.confdeltype <> 'r'   -- 'r' = RESTRICT
     LIMIT 1;

    IF con_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE tickets DROP CONSTRAINT %I', con_name);
        ALTER TABLE tickets
            ADD CONSTRAINT tickets_forms_form_id_fkey
            FOREIGN KEY (forms_form_id) REFERENCES forms(id) ON DELETE RESTRICT;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_tickets_forms_form_id ON tickets (forms_form_id);

ALTER TABLE tickets ALTER COLUMN form_id DROP NOT NULL;

-- Guarded: every existing row came through the ticket-form path and so has
-- form_id set, but an operator re-running this against edited data should get
-- a clear failure rather than a half-applied schema.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM tickets
         WHERE (form_id IS NULL) = (forms_form_id IS NULL)
    ) THEN
        RAISE EXCEPTION
            'tickets rows have neither or both form references; fix those before adding ck_ticket_exactly_one_form';
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'ck_ticket_exactly_one_form'
    ) THEN
        ALTER TABLE tickets
            ADD CONSTRAINT ck_ticket_exactly_one_form
            CHECK ((form_id IS NULL) <> (forms_form_id IS NULL));
    END IF;
END $$;

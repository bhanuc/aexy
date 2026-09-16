-- The public form page rendered "Your Name" and "Email Address" above the
-- designed fields unconditionally. Neither appeared in the builder, so a form
-- designed with four fields showed six, and whoever designed it had no way to
-- see that or change it.
--
-- These make the contact block the form's decision. Defaults reproduce the old
-- behaviour exactly, so every existing form renders as it does today.
ALTER TABLE forms
    ADD COLUMN IF NOT EXISTS collect_name  BOOLEAN NOT NULL DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS require_name  BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS collect_email BOOLEAN NOT NULL DEFAULT TRUE;

-- "Required but not collected" is a form that can never be submitted. The
-- combination is unreachable through the builder, but nothing else stopped an
-- API caller reaching it.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_form_contact_required_is_collected') THEN
        ALTER TABLE forms
            ADD CONSTRAINT ck_form_contact_required_is_collected
            CHECK (
                (collect_name  OR NOT require_name)
                AND (collect_email OR NOT require_email)
            );
    END IF;
END $$;

-- Email verification with no address to verify. The constraint above ties
-- `require_email` to `collect_email` but says nothing about `auth_mode`, so
-- this pairing stayed reachable through the API: the submission is accepted,
-- the response reports `requires_email_verification`, and the public page asks
-- the submitter to check an inbox the form never collected.
--
-- No existing row can violate it — `collect_email` defaults to TRUE above.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_form_email_verification_collects_email') THEN
        ALTER TABLE forms
            ADD CONSTRAINT ck_form_email_verification_collects_email
            CHECK (collect_email OR auth_mode <> 'email_verification');
    END IF;
END $$;

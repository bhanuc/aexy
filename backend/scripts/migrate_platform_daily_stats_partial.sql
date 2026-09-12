-- Whether a snapshot row is missing figures that could not be recovered.
--
-- `platform_daily_stats` holds two kinds of number. The dated ones — signups,
-- developers created, cancellations, AI spend — can be recomputed for any past
-- day, because the source rows still carry their timestamps. The rest describe
-- *now*: subscription state, seat counts, the month-to-date bill. Backfilling a
-- day that has already gone leaves those at zero, and a zero that means "we did
-- not know" must never be read as a zero that means "there was none".
--
-- That distinction was being carried in the `notes` array and recovered by
-- searching it for the words "historical day". Prose is not a flag: rewording
-- the note silently turned every backfilled day back into real data, and the
-- growth chart would then draw revenue plunging to zero across a range where
-- nothing had happened at all. It is a column now.
--
-- Existing rows are classified by the same substring the code used to match, so
-- the switch keeps whatever the table already says rather than resetting it.
ALTER TABLE platform_daily_stats
    ADD COLUMN IF NOT EXISTS is_partial BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE platform_daily_stats
SET is_partial = TRUE
WHERE is_partial = FALSE
  AND notes::text LIKE '%historical day%';

CREATE INDEX IF NOT EXISTS idx_platform_daily_stats_complete
    ON platform_daily_stats (day DESC)
    WHERE is_partial = FALSE;

SELECT
    (SELECT count(*) FROM platform_daily_stats) AS snapshots,
    (SELECT count(*) FROM platform_daily_stats WHERE is_partial) AS partial;

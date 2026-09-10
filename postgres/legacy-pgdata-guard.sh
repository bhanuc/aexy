#!/bin/sh
# Refuse to start on a volume that still holds a pre-18 cluster at its root.
#
# `docker-compose.yml` mounts postgres_data at /var/lib/postgresql/data and
# sets PGDATA to the pgdata/ subdirectory below it. That combination is what
# postgres:18 wants — the 18+ images store data under a major-version
# directory and reject a volume mounted directly at the legacy path, which is
# why a plain `docker-compose up` on a fresh clone used to die with
#
#     Error: in 18+, these Docker images are configured to store database data
#            in a format which is compatible with "pg_ctlcluster" ...
#            there appears to be PostgreSQL data in:
#              /var/lib/postgresql/data (unused mount/volume)
#
# But setting PGDATA away from the image default also switches OFF the stock
# entrypoint's upgrade check: it only scans for an older cluster when PGDATA is
# the default /var/lib/postgresql/$PG_MAJOR/docker. So on a volume written by
# an earlier image — cluster files sitting directly in /var/lib/postgresql/data
# — the entrypoint would find no PG_VERSION at the new PGDATA, initdb a fresh
# empty cluster in pgdata/ beside the old one, and hand the app an empty
# database. Nothing is deleted, but it reads as total data loss, and the next
# person to "fix" it by re-seeding would make that true.
#
# So the check is reproduced here, before the real entrypoint runs. Refusing to
# start is recoverable; coming up empty is how people restore from backups they
# find out they don't have.
LEGACY_DIR=/var/lib/postgresql/data

if [ -s "$LEGACY_DIR/PG_VERSION" ]; then
    legacy_version="$(cat "$LEGACY_DIR/PG_VERSION" 2>/dev/null)"
    cat >&2 <<MSG

================================ REFUSING TO START ================================
A PostgreSQL $legacy_version cluster is sitting directly in $LEGACY_DIR, which is
this container's data volume root. This image runs PostgreSQL ${PG_MAJOR:-18} and
reads its data from \$PGDATA ($PGDATA), a subdirectory of that volume.

Starting anyway would create a new, EMPTY cluster next to your existing data and
the application would come up with no rows in it. Your data is still there and
untouched — it is simply not where this server looks.

PostgreSQL major versions cannot share a data directory, so the old cluster has
to be migrated rather than pointed at:

  1. Back the volume up first:
       docker run --rm -v aexy_postgres_data:/v -v "\$PWD":/out alpine \\
         tar czf /out/postgres_data_backup.tgz -C /v .

  2. Dump with the OLD server, restore into the new one. Start the previous
     image against the same volume (postgres:$legacy_version-alpine, mounted at
     $LEGACY_DIR with no PGDATA override), then:
       docker exec <old-container> pg_dumpall -U postgres > dump.sql
     Bring this image up on an empty volume and feed the dump back in.

  See docs/guides/database-operations.md — "Major version bump" — for the full
  procedure.

  If this volume holds nothing you need, discard it and start clean:
       docker-compose down && docker volume rm aexy_postgres_data
===================================================================================

MSG
    exit 1
fi

exec docker-entrypoint.sh "$@"

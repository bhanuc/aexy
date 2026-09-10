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
THIS_MAJOR="${PG_MAJOR:-18}"

if [ -s "$LEGACY_DIR/PG_VERSION" ]; then
    legacy_version="$(cat "$LEGACY_DIR/PG_VERSION" 2>/dev/null)"

    # Same major version: nothing needs upgrading, the server is simply being
    # pointed at the wrong directory. Almost always someone who worked around
    # the pre-0.37.3 startup failure by setting PGDATA to the volume root
    # themselves, and has now picked up a compose file that puts it one level
    # down. Telling them to dump and restore would be alarming and wrong.
    if [ "$legacy_version" = "$THIS_MAJOR" ]; then
        cat >&2 <<SAME

================================ REFUSING TO START ================================
A PostgreSQL $legacy_version cluster — the same major version this image runs —
is sitting directly in $LEGACY_DIR, but \$PGDATA is set to
$PGDATA.

Nothing is wrong with your data and nothing needs upgrading. The server is just
being pointed at a different directory inside the same volume, and starting
anyway would initialise a second, empty cluster beside the one you have.

Pick either:

  * Keep using the directory you already have — drop the PGDATA override, or
    set it back to $LEGACY_DIR:
        PGDATA: $LEGACY_DIR
    Note that a bare postgres:18+ image refuses a volume mounted at that path,
    which is why the shipped compose file moves PGDATA down a level. This image
    allows it, because this guard replaces the check that would have caught it.

  * Or move the cluster to where PGDATA now points, with the container stopped:
        docker run --rm -v aexy_postgres_data:/v alpine sh -c \\
          'mkdir -p /v/pgdata && find /v -maxdepth 1 -mindepth 1 \\
             ! -name pgdata -exec mv {} /v/pgdata/ \;'
    Back the volume up first (see below) — this moves live data.

  Back up before either:
      docker run --rm -v aexy_postgres_data:/v -v "\$PWD":/out alpine \\
        tar czf /out/postgres_data_backup.tgz -C /v .
===================================================================================

SAME
        exit 1
    fi

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

  2. Dump with the OLD server, restore into the new one. The old server needs
     pgvector: this database has 'vector' columns, and dumping their rows calls
     the extension's output function, so a stock postgres image fails at the
     step you least want to fail. Build the same image for the old major —
     alpine throughout, so the postgres UID and libc collations still match the
     volume:
       docker build -t aexy-postgres:$legacy_version-alpine-pgvector \\
         --build-arg PG_IMAGE=postgres:$legacy_version-alpine ./postgres
     Run it against this volume with PGDATA at $LEGACY_DIR, then:
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

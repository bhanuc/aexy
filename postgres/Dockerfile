# Aexy Postgres image: stock postgres:18-alpine + pgvector extension.
#
# Why a custom image: keeping the alpine base preserves the postgres user UID
# and the libc collations the existing data volume was created with. A switch
# to the official pgvector/pgvector:pg18 image (Debian) would require a
# pg_dump/restore cycle to avoid UID and libc collation issues.
#
# pgvector v0.8.1 is the first tag with PostgreSQL 18 support — earlier tags
# fail to compile against the v18 headers.

# Overridable so the same recipe can build a pgvector-enabled image for an
# older major, which is what a PG_VERSION-mismatch recovery needs: dumping a
# database that has `vector` columns requires the extension's library to be
# loadable, and the stock postgres images do not carry it. Keeping the alpine
# base across versions also keeps the postgres UID and the libc collations the
# existing volume was created with — see the note below.
#   docker build -t aexy-postgres:17-alpine-pgvector \
#     --build-arg PG_IMAGE=postgres:17-alpine ./postgres
ARG PG_IMAGE=postgres:18-alpine
FROM ${PG_IMAGE}

ARG PGVECTOR_VERSION=v0.8.1

# postgres:18-alpine is a floating tag: the base drifts to newer Alpine
# releases over time, and each release ships a different default LLVM. pgvector's
# JIT bitcode must be built with the SAME clang/llvm version postgres itself was
# compiled against, so we derive that version from pg_config instead of
# hardcoding it (hardcoding breaks whenever the base image is rebuilt/repulled).
RUN LLVM_MAJOR="$(pg_config --configure | grep -oE 'llvm[0-9]+' | grep -oE '[0-9]+' | head -1)" \
 && echo "Building pgvector against LLVM ${LLVM_MAJOR}" \
 && apk add --no-cache --virtual .build-deps \
        build-base git "clang${LLVM_MAJOR}" "llvm${LLVM_MAJOR}-dev" \
 && cd /tmp \
 && git clone --depth 1 --branch ${PGVECTOR_VERSION} \
        https://github.com/pgvector/pgvector.git \
 && cd pgvector \
 && make OPTFLAGS="" \
 && make install \
 && cd / \
 && rm -rf /tmp/pgvector \
 && apk del .build-deps

# postgres:18+ stores data under a major-version directory and rejects a volume
# mounted straight at the legacy /var/lib/postgresql/data. `docker-compose.yml`
# keeps that mount point (existing volumes are named for it) and sets PGDATA to
# the pgdata/ subdirectory instead, which the entrypoint accepts.
#
# The catch is that a non-default PGDATA also disables the stock entrypoint's
# "there is an older cluster here, run pg_upgrade" check, so a volume written by
# an earlier image would quietly get a new empty cluster beside its real data.
# This wrapper reinstates that check and then hands off to the real entrypoint.
COPY legacy-pgdata-guard.sh /usr/local/bin/legacy-pgdata-guard.sh
RUN chmod +x /usr/local/bin/legacy-pgdata-guard.sh

ENTRYPOINT ["legacy-pgdata-guard.sh"]
CMD ["postgres"]

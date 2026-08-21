#!/usr/bin/env bash
# Recreate the homepage product-tour screenshots from scratch, end to end:
# stack up → demo data seeded → token minted → light-mode captures written
# to public/marketing/home/.
#
# Usage (from frontend/):
#   ./e2e/tools/recreate-marketing-shots.sh
#
# Prereqs: Docker running; frontend dev server on :3000 (npm run dev) or
# PLAYWRIGHT_BASE_URL pointing elsewhere.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
FRONTEND_DIR="$REPO_ROOT/frontend"

echo "==> Ensuring the docker-compose stack is up"
if ! curl -sf -m 3 http://localhost:8000/api/v1/health >/dev/null 2>&1; then
  (cd "$REPO_ROOT" && docker-compose up -d)
  echo "==> Waiting for the backend to become healthy"
  for _ in $(seq 1 30); do
    curl -sf -m 3 http://localhost:8000/api/v1/health >/dev/null 2>&1 && break
    sleep 5
  done
  curl -sf -m 3 http://localhost:8000/api/v1/health >/dev/null \
    || { echo "backend never became healthy" >&2; exit 1; }
fi

echo "==> Ensuring the frontend is reachable"
BASE_URL="${PLAYWRIGHT_BASE_URL:-http://localhost:3000}"
curl -sf -m 5 "$BASE_URL" >/dev/null \
  || { echo "frontend not reachable at $BASE_URL — start it with 'npm run dev'" >&2; exit 1; }

echo "==> Seeding marketing demo data (idempotent)"
docker exec aexy-backend python scripts/seed_marketing_demo.py

echo "==> Minting a test token"
TOKEN="$(docker exec aexy-backend python scripts/generate_test_token.py --first \
  | sed -n 's/.*export AEXY_TEST_TOKEN="\([^"]*\)".*/\1/p' | head -1)"
[ -n "$TOKEN" ] || { echo "could not extract token" >&2; exit 1; }

echo "==> Capturing screenshots"
cd "$FRONTEND_DIR"
AEXY_TEST_TOKEN="$TOKEN" npx tsx e2e/tools/capture-marketing-shots.ts

echo "==> Done. Shots in public/marketing/home/"

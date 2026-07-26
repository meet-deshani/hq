#!/usr/bin/env bash
# Local dev server for HQ, on a throwaway SQLite database.
#
# NEVER points at production: the repo .env holds the live Postgres DSN, so
# DATABASE_URL is set explicitly here to override it. A local run that quietly
# connected to hq.dotsai.in's database would be a very bad afternoon.
#
#   ./scripts/dev.sh            # http://127.0.0.1:8077
#   HQ_PORT=8100 ./scripts/dev.sh
#
# Then, in another shell:  ./tests/run-all.sh
set -euo pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="sqlite:////tmp/hqdev.db"
export SECRET_KEY="local-dev-only-not-a-production-secret"
# Required since PR #6 — without it the admin user is not seeded at all.
export SEED_ADMIN_PASSWORD="${SEED_ADMIN_PASSWORD:-local-admin-test-pw}"
export SEED_NISHANT_PASSWORD="${SEED_NISHANT_PASSWORD:-nishant-local-test-pw}"
export SEED_HEMISH_PASSWORD="${SEED_HEMISH_PASSWORD:-hemish-local-test-pw}"
# Inbound messaging fails closed without this, so set it for local QA.
export COMMS_WEBHOOK_TOKEN="${COMMS_WEBHOOK_TOKEN:-local-webhook-secret}"

PORT="${HQ_PORT:-8077}"
echo "HQ dev server on http://127.0.0.1:${PORT}"
echo "  admin    meet@dotsai.in     / ${SEED_ADMIN_PASSWORD}"
echo "  partner  nishant@neonir.com / ${SEED_NISHANT_PASSWORD}"
echo "  advisor  hemish@neonir.com  / ${SEED_HEMISH_PASSWORD}"
echo "  db       /tmp/hqdev.db  (delete it for a clean seed)"
exec venv/bin/uvicorn backend.main:app --host 127.0.0.1 --port "$PORT" --log-level info

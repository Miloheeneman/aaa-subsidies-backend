#!/usr/bin/env bash
# Test harness: rebuilds the dev DB, boots uvicorn, runs every E2E suite
# in a clean database snapshot, then tears uvicorn down. Exits non-zero
# if any suite fails.
set -uo pipefail

cd "$(dirname "$0")/.."
source .venv/bin/activate

export DATABASE_URL="postgresql+psycopg://postgres:postgres@/aaa_subsidies?host=/tmp&port=55432"
export FRONTEND_URL=http://localhost:5173
export JWT_SECRET_KEY=test-secret
export API_BASE=http://127.0.0.1:8769/api/v1

reset_db() {
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
  sleep 1
  psql -h /tmp -p 55432 -U postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='aaa_subsidies';" >/dev/null 2>&1 || true
  psql -h /tmp -p 55432 -U postgres -c 'DROP DATABASE IF EXISTS aaa_subsidies;' >/dev/null
  psql -h /tmp -p 55432 -U postgres -c 'CREATE DATABASE aaa_subsidies;' >/dev/null
  alembic upgrade head >/dev/null
  uvicorn app.main:app --host 127.0.0.1 --port 8769 --log-level warning >/tmp/uvicorn.log 2>&1 &
  sleep 2
}

FAIL=0
for suite in e2e_smoke e2e_subsidiecheck e2e_aanvragen e2e_documenten_admin e2e_installateur_stripe e2e_deadline_regelingen e2e_onboarding; do
  echo ""
  echo "==================== $suite ===================="
  reset_db
  if ! python "tests/${suite}.py"; then
    echo ">>> FAIL: $suite"
    FAIL=1
  else
    echo ">>> OK: $suite"
  fi
done

pkill -f "uvicorn app.main:app" 2>/dev/null || true
exit $FAIL

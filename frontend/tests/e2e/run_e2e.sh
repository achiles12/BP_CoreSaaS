#!/usr/bin/env bash
# Run the critical-flow browser suite (B12 D8/D9) against the running stack.
#   bash frontend/tests/e2e/run_e2e.sh            (or: make e2e)
# Env: BASE (default FRONTEND_URL, else PUBLIC_HOST + FRONTEND_PORT from .env),
#      MAILPIT (default localhost + MAILPIT_UI_PORT), E2E_REPORT (report dir).
# Exit code = Playwright's (0 = all green).
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
cd "$ROOT"
PW_IMAGE="mcr.microsoft.com/playwright:v1.65.0-noble"
env_value() { grep -E "^$1=" .env 2>/dev/null | tail -1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//; s/[[:space:]]+$//'; }
BASE="${BASE:-$(env_value FRONTEND_URL)}"; HOST_="$(env_value PUBLIC_HOST)"; PORT_="$(env_value FRONTEND_PORT)"
BASE="${BASE:-http://${HOST_:-localhost}:${PORT_:-3200}}"
MPORT_="$(env_value MAILPIT_UI_PORT)"
MAILPIT="${MAILPIT:-http://localhost:${MPORT_:-8025}}"
REPORT="${E2E_REPORT:-$ROOT/frontend/tests/e2e/report}"
rm -rf "$REPORT"; mkdir -p "$REPORT"

echo "[e2e] seeding tenant e2e"
docker compose exec -T backend python - <"$HERE/seed_e2e.py" | grep -v '^\S* \S* \[' || { echo "[e2e] seed failed"; exit 2; }

echo "[e2e] running Playwright against $BASE (mail: $MAILPIT)"
# The spec files are copied into the container's /tmp so node_modules never
# lands in the repo; reports are written to the mounted $REPORT.
docker run --rm --network host -u "$(id -u):$(id -g)" -e HOME=/tmp \
  -e BASE="$BASE" -e MAILPIT="$MAILPIT" -e E2E_OUT=/report \
  -v "$HERE":/e2e:ro -v "$REPORT":/report "$PW_IMAGE" bash -c \
  "mkdir -p /tmp/e2e && cp /e2e/*.ts /e2e/package.json /tmp/e2e/ && cd /tmp/e2e && \
   npm i -s --no-audit --no-fund @playwright/test@1.65.0 >/dev/null 2>&1 && \
   npx playwright test"
rc=$?
echo "[e2e] exit $rc · report: $REPORT/html/index.html · junit: $REPORT/junit.xml"
exit $rc

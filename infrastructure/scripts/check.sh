#!/usr/bin/env bash
# Everything CI runs, locally, in one command. Exits non-zero on the first failure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

echo "=== backend ==="
infrastructure/scripts/test-api.sh

echo "=== shared types ==="
npm ci --no-audit --no-fund
npm run check:types

echo "=== frontend ==="
npm run lint
npm run typecheck
npm run test
NEXT_TELEMETRY_DISABLED=1 npm run build

echo "=== compose ==="
POSTGRES_PASSWORD=x SECRET_KEY=x docker compose config --quiet

echo "All checks passed."

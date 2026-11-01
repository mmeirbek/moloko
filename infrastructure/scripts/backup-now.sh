#!/usr/bin/env bash
# Make a backup now (and optionally test restoring it): backup-now.sh [--check]
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose exec -T backup sh /scripts/backup.sh
if [[ "${1:-}" == "--check" ]]; then
  docker compose exec -T backup sh /scripts/restore-check.sh
fi

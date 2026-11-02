#!/usr/bin/env bash
# Make a backup now:  backup-now.sh [--check] [--offsite]
#   --check    also test restoring it (into a scratch database)
#   --offsite  also send it to the off-site repository now (OFFSITE_* in .env); together
#              with --check also check that repository and test-restore from it
set -euo pipefail
cd "$(dirname "$0")/../.."
# MOLOKO_ENV_FILE: another env file than ./.env (optional).
ENV_ARGS=()
[[ -n "${MOLOKO_ENV_FILE:-}" ]] && ENV_ARGS=(--env-file "$MOLOKO_ENV_FILE")
compose() { docker compose ${ENV_ARGS[@]+"${ENV_ARGS[@]}"} "$@"; }

check=0
offsite=0
for arg in "$@"; do
  case "$arg" in
    --check) check=1 ;;
    --offsite) offsite=1 ;;
    *) echo "Usage: $0 [--check] [--offsite]" >&2; exit 2 ;;
  esac
done

compose exec -T backup sh /scripts/backup.sh
if [[ "$check" == 1 ]]; then
  compose exec -T backup sh /scripts/restore-check.sh
fi
if [[ "$offsite" == 1 ]]; then
  compose exec -T backup sh /scripts/offsite.sh backup manual
  if [[ "$check" == 1 ]]; then
    compose exec -T backup sh /scripts/offsite.sh check
    compose exec -T backup sh /scripts/offsite.sh drill
  fi
fi

#!/bin/sh
# Container entrypoint for the API and the worker (same image).
#   RUN_MIGRATIONS=true  (backend): wait for PostgreSQL, apply migrations, run.
#   RUN_MIGRATIONS=false (worker):  wait until the backend has migrated, run.
# If PostgreSQL is not up yet (e.g. right after a host reboot) this exits non-zero
# and Docker's restart policy tries again.
set -eu

python -m app.cli wait-for-db --timeout "${DB_WAIT_TIMEOUT:-60}"
if [ "${RUN_MIGRATIONS:-true}" = "true" ]; then
  alembic upgrade head
else
  python -m app.cli wait-for-migrations --timeout "${MIGRATION_WAIT_TIMEOUT:-180}"
fi
exec "$@"

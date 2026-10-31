#!/bin/sh
# Container entrypoint for the API: wait for PostgreSQL, apply migrations, then run.
# If PostgreSQL is not up yet (e.g. right after a host reboot) this exits non-zero
# and Docker's restart policy tries again.
set -eu

python -m app.cli wait-for-db --timeout "${DB_WAIT_TIMEOUT:-60}"
alembic upgrade head
exec "$@"

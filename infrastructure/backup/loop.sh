#!/bin/sh
# The backup service. Wakes up every hour and does what is due:
#   - the local backup (backup.sh), once a day at BACKUP_HOUR (UTC) — or later that day if
#     the server was off at that hour; on Sundays also the local restore drill;
#   - the encrypted off-site copy of the newest local backup while it is not off-site yet,
#     so a failed upload (no internet, disk unplugged) is retried every hour (offsite.sh);
#   - the off-site check and the off-site restore drill when they are due.
# The off-site steps do nothing unless OFFSITE_* is set in .env.
set -u
HOUR="${BACKUP_HOUR:-3}"
case "$HOUR" in "" | *[!0-9]*) HOUR=3 ;; esac
STATUS=/backups/status.json

backup_due() { # no backup yet; or none today and it is BACKUP_HOUR or later (UTC)
  [ -f "$STATUS" ] || return 0
  now="$(date -u +%s)"
  [ $(( now / 3600 % 24 )) -ge "$HOUR" ] && [ $(( $(stat -c %Y "$STATUS") / 86400 )) -lt $(( now / 86400 )) ]
}

sleep 60
sh /scripts/offsite.sh state || true  # tells the app whether off-site copies are set up
while true; do
  if backup_due; then
    sh /scripts/backup.sh || true
    if [ "$(date -u +%u)" = "7" ]; then sh /scripts/restore-check.sh || true; fi
  fi
  if sh /scripts/offsite.sh pending; then sh /scripts/offsite.sh backup || true; fi
  sh /scripts/offsite.sh due || true
  sleep $(( 3600 - $(date -u +%s) % 3600 ))
done

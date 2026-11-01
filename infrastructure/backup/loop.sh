#!/bin/sh
# The backup service: a backup every day at BACKUP_HOUR (UTC), a restore drill every
# Sunday after it. Also one backup shortly after start if none exists yet.
set -u
HOUR="${BACKUP_HOUR:-3}"
sleep 60
[ -f /backups/status.json ] || sh /scripts/backup.sh || true
while true; do
  now="$(date -u +%s)"
  next="$(date -u -d "$(date -u +%Y-%m-%d) ${HOUR}:00:00" +%s 2>/dev/null || echo $((now + 86400)))"
  [ "$next" -le "$now" ] && next=$((next + 86400))
  sleep $((next - now))
  sh /scripts/backup.sh || true
  if [ "$(date -u +%u)" = "7" ]; then sh /scripts/restore-check.sh || true; fi
done

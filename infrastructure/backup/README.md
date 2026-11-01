# Backups

The `backup` service (docker-compose.yml) runs `loop.sh`: every day at `BACKUP_HOUR`
(UTC) `backup.sh` writes a PostgreSQL dump and an archive of the workspaces to
`BACKUP_DIR`, verifies them (checksums, `pg_restore --list`, `gzip -t`) and rotates them
(`BACKUP_KEEP_DAILY` dailies, `BACKUP_KEEP_WEEKLY` weeklies). Every Sunday
`restore-check.sh` restores the newest dump into a scratch database and checks it.

`BACKUP_DIR` must be **on another disk** (external drive, NAS mount): a backup on the
same disk is not protection. Settings → Backups warns when it is the same disk.

Manual run, restore and the restore drill: `docs/deployment.md` → «Резервные копии».

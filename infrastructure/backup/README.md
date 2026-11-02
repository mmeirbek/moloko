# Backups

The `backup` service (docker-compose.yml, image built from `Dockerfile` here: postgres
client tools + restic) runs `loop.sh`, which wakes up every hour:

- **Local backup** — once a day at `BACKUP_HOUR` (UTC), or later that day if the server was
  off: `backup.sh` writes a PostgreSQL dump and an archive of the workspaces and chat files (`files`
  volume; big attachments make it big) to `BACKUP_DIR`,
  verifies them (checksums, `pg_restore --list`, `gzip -t`) and rotates them
  (`BACKUP_KEEP_DAILY` dailies, `BACKUP_KEEP_WEEKLY` weeklies). Every Sunday
  `restore-check.sh` restores the newest dump into a scratch database and checks it.
- **Off-site copy** (only when `OFFSITE_REPOSITORY` or `OFFSITE_DISK` is set) —
  `offsite.sh backup` sends the newest local backup set, encrypted by restic, to cloud
  storage (S3: Backblaze B2, Cloudflare R2, …), an SFTP host or an external disk, then
  applies the retention (`restic forget --prune`, `OFFSITE_KEEP_*`). A failed upload is
  retried every hour. Every `OFFSITE_CHECK_DAYS`: `restic check --read-data-subset`;
  every `OFFSITE_DRILL_DAYS`: the newest off-site copy is restored into a scratch folder and
  database (`restore-check.sh` with the restored dump) and compared with the local copy.

Status files in `BACKUP_DIR` (world-readable, never a secret in them) feed Settings →
Backups: `status.json`, `last-drill.json`, `offsite-config.json`, `offsite-status.json`,
`offsite-last.json`, `offsite-check.json`, `offsite-drill.json`.

A local backup on the laptop's own disk is no protection against losing the laptop: set up
the off-site copies. Settings → Backups warns until there is a recent one.

Scripts (`infrastructure/scripts/`): `backup-now.sh [--check] [--offsite]`, `restore.sh`,
`offsite-init.sh` (one-time setup), `offsite-restore.sh` (list / restore off-site copies),
`test-offsite.sh` (end-to-end test against a local folder repository).
How-to: `docs/deployment.md` → «Резервные копии» and «Копии вне ноутбука».

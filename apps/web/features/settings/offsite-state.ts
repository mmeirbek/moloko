import type { StorageStatus } from "@moloko/shared-types";

/** Off-site copies as GET /system/storage reports them (infrastructure/backup/offsite.sh). */
export type Offsite = StorageStatus["backups"]["offsite"];

/** Off-site warnings of the backend (services/storage.py); "offsite_off" is the "off" state. */
export const OFFSITE_WARNINGS = [
  "offsite_failed",
  "offsite_no_copy_yet",
  "offsite_too_old",
  "offsite_check_failed",
  "offsite_drill_failed",
] as const;

/** Error codes offsite.sh writes into offsite-status / -check / -drill.json. */
export const OFFSITE_ERROR_CODES = [
  "no_repository",
  "wrong_password",
  "no_password",
  "disk_missing",
  "bad_settings",
  "locked",
  "no_local_backup",
  "incomplete",
  "forget_failed",
  "interrupted",
  "corrupt",
  "no_snapshot",
  "failed",
] as const;

export type OffsiteState = "protected" | "problem" | "off";

/** Protected = on, with a good copy and no off-site warning. */
export function offsiteState(offsite: Offsite, warnings: readonly string[]) {
  const problems = OFFSITE_WARNINGS.filter((w) => warnings.includes(w));
  const state: OffsiteState = !offsite.enabled
    ? "off"
    : offsite.last_copy != null && problems.length === 0
      ? "protected"
      : "problem";
  return { state, problems };
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";

import { AlertTriangle, ShieldAlert, ShieldCheck } from "@/components/icons";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { storageKey, systemStorage } from "@/lib/api/agents";
import { cn } from "@/lib/utils";

import { type Offsite, offsiteState } from "./offsite-state";

const WARNINGS = [
  "not_configured",
  "no_backup_yet",
  "last_backup_failed",
  "backup_too_old",
  "restore_drill_failed",
  "same_disk",
  "low_disk",
] as const;

const warningClass =
  "flex items-start gap-2 border border-amber-400/50 bg-amber-400/10 px-3 py-2 text-amber-800 dark:text-amber-200";

/** Dates and sizes the same way in both cards. */
function useFormat() {
  const format = useFormatter();
  const when = (iso?: string | null) =>
    iso ? format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" }) : "—";
  const size = (bytes: number) => {
    const [value, unit] =
      bytes >= 1e9 ? [bytes / 1e9, "gigabyte"] : bytes >= 1e6 ? [bytes / 1e6, "megabyte"] : [bytes / 1e3, "kilobyte"];
    return format.number(value, { style: "unit", unit, unitDisplay: "short", maximumFractionDigits: 1 });
  };
  return { when, size };
}

/** Settings → Backups (spec 21.3): local backups + the encrypted off-site copies. */
export function BackupsSection() {
  const t = useTranslations("backups");
  const { when, size } = useFormat();
  const status = useQuery({ queryKey: storageKey, queryFn: ({ signal }) => systemStorage(signal) });
  const data = status.data;
  const last = data?.backups.last as { ok?: boolean; at?: string; database_bytes?: number } | null | undefined;
  const drill = data?.backups.drill as { ok?: boolean; at?: string } | null | undefined;
  return (
    <>
      <Card id="backups">
        <CardHeader>
          <CardTitle>{t("title")}</CardTitle>
          <CardDescription>{t("description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3 text-sm">
          {data?.warnings
            .filter((w): w is (typeof WARNINGS)[number] => (WARNINGS as readonly string[]).includes(w))
            .map((w) => (
              <p key={w} role="alert" className={warningClass}>
                {t(`warnings.${w}`)}
              </p>
            ))}
          {data && (
            <dl className="grid gap-1 sm:grid-cols-[14rem_1fr]">
              <dt className="text-muted-foreground">{t("last")}</dt>
              <dd className={cn(last && !last.ok && "text-destructive")}>
                {last ? `${when(last.at)} · ${last.ok ? t("ok") : t("failed")}` : "—"}
                {last?.database_bytes ? ` · ${size(last.database_bytes)}` : ""}
              </dd>
              <dt className="text-muted-foreground">{t("drill")}</dt>
              <dd className={cn(drill && !drill.ok && "text-destructive")}>
                {drill ? `${when(drill.at)} · ${drill.ok ? t("drillOk") : t("failed")}` : t("noDrill")}
              </dd>
              <dt className="text-muted-foreground">{t("copies")}</dt>
              <dd>{data.backups.files.filter((f) => f.name.endsWith(".dump")).length}</dd>
              {data.disks.map((d) => (
                <div key={d.path} className="contents">
                  <dt className="text-muted-foreground">{t("disk", { path: d.path })}</dt>
                  <dd className={cn(d.low && "text-destructive")}>
                    {t("free", { free: size(d.free_bytes), percent: d.free_percent })}
                  </dd>
                </div>
              ))}
            </dl>
          )}
          <p className="text-xs text-muted-foreground">{t("howto")}</p>
        </CardContent>
      </Card>
      {data?.backups.configured && <OffsiteCard offsite={data.backups.offsite} warnings={data.warnings} />}
    </>
  );
}

/** The encrypted copies off the laptop (restic; infrastructure/backup/offsite.sh). */
function OffsiteCard({ offsite, warnings }: { offsite: Offsite; warnings: string[] }) {
  const t = useTranslations("backups.offsite");
  const { when, size } = useFormat();
  const { state, problems } = offsiteState(offsite, warnings);
  const healthy = state === "protected";
  const errorText = (code?: string | null) => {
    const key = `errors.${code ?? "failed"}`;
    return t.has(key as "errors.failed") ? t(key as "errors.failed") : t("errors.failed");
  };
  const copy = offsite.last_copy;
  const { check, drill } = offsite;
  const StateIcon = healthy ? ShieldCheck : ShieldAlert;
  return (
    <Card id="offsite" className={cn(healthy && "[--frame-color:var(--color-grass)]")}>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        <p
          className={cn(
            "flex items-center gap-2 font-pixel text-lg",
            healthy ? "text-grass" : "text-amber-700 dark:text-amber-300",
          )}
        >
          <StateIcon className="size-6 shrink-0" aria-hidden />
          {t(`state.${state}`)}
        </p>

        {!offsite.enabled ? (
          <>
            <p>{t("offExplain")}</p>
            <ol className="flex list-decimal flex-col gap-1 pl-5">
              <li>{t("steps.storage")}</li>
              <li>{t("steps.env")}</li>
              <li>
                {t("steps.init")} <code className="text-xs break-all">infrastructure/scripts/offsite-init.sh</code>
              </li>
            </ol>
            <p className="text-xs text-muted-foreground">{t("docs")}</p>
          </>
        ) : (
          <>
            {problems.map((w) => (
              <div key={w} role="alert" className={warningClass}>
                <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                <div className="flex min-w-0 flex-col gap-1">
                  <p>
                    {t(`warnings.${w}`)}
                    {w === "offsite_failed" && ` ${errorText(offsite.last_attempt?.error_code)}`}
                  </p>
                  {w === "offsite_failed" && offsite.last_attempt?.error && (
                    <p className="text-xs break-all opacity-80">{offsite.last_attempt.error}</p>
                  )}
                </div>
              </div>
            ))}
            <dl className="grid gap-1 sm:grid-cols-[14rem_1fr]">
              <dt className="text-muted-foreground">{t("where")}</dt>
              <dd className="min-w-0">
                {t.has(`kinds.${offsite.kind}` as "kinds.s3") ? t(`kinds.${offsite.kind}` as "kinds.s3") : offsite.kind}
                {offsite.repository && (
                  <span className="block text-xs break-all text-muted-foreground">{offsite.repository}</span>
                )}
              </dd>
              <dt className="text-muted-foreground">{t("lastCopy")}</dt>
              <dd>
                {copy
                  ? [when(copy.at), copy.bytes != null ? size(copy.bytes) : null, t("snapshot", { id: copy.snapshot })]
                      .filter(Boolean)
                      .join(" · ")
                  : t("noCopy")}
              </dd>
              {copy && (copy.stored_bytes != null || copy.snapshots != null) && (
                <>
                  <dt className="text-muted-foreground">{t("stored")}</dt>
                  <dd>
                    {[
                      copy.stored_bytes != null ? size(copy.stored_bytes) : null,
                      copy.snapshots != null ? t("copiesKept", { count: copy.snapshots }) : null,
                    ]
                      .filter(Boolean)
                      .join(" · ")}
                  </dd>
                </>
              )}
              {offsite.keep_daily != null && (
                <>
                  <dt className="text-muted-foreground">{t("retention")}</dt>
                  <dd>
                    {t("keep", {
                      daily: offsite.keep_daily,
                      weekly: offsite.keep_weekly ?? 0,
                      monthly: offsite.keep_monthly ?? 0,
                    })}
                  </dd>
                </>
              )}
              <dt className="text-muted-foreground">{t("check")}</dt>
              <dd className={cn(check && !check.ok && "text-destructive")}>
                {check
                  ? `${when(check.at)} · ${check.ok ? t("checkOk", { subset: check.subset ?? "" }) : errorText(check.error_code)}`
                  : t("notYet", { days: offsite.check_days ?? 7 })}
                {check && !check.ok && check.detail && (
                  <span className="block text-xs break-all opacity-80">{check.detail}</span>
                )}
              </dd>
              <dt className="text-muted-foreground">{t("drill")}</dt>
              <dd className={cn(drill && !drill.ok && "text-destructive")}>
                {drill
                  ? `${when(drill.at)} · ${
                      drill.ok
                        ? drill.same_as_local
                          ? t("drillOkSame")
                          : t("drillOk")
                        : drill.error_code
                          ? errorText(drill.error_code)
                          : t("drillFailed")
                    }`
                  : t("notYet", { days: offsite.drill_days ?? 7 })}
                {drill && !drill.ok && drill.detail && (
                  <span className="block text-xs break-all opacity-80">{drill.detail}</span>
                )}
              </dd>
            </dl>
            <p className="text-xs text-muted-foreground">{t("howto")}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

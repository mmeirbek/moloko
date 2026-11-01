"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { storageKey, systemStorage } from "@/lib/api/agents";
import { cn } from "@/lib/utils";

const WARNINGS = [
  "not_configured",
  "no_backup_yet",
  "last_backup_failed",
  "backup_too_old",
  "restore_drill_failed",
  "same_disk",
  "low_disk",
] as const;

/** Settings → Backups (spec 21.3): last backup, restore drill, disk space, warnings. */
export function BackupsSection() {
  const t = useTranslations("backups");
  const format = useFormatter();
  const status = useQuery({ queryKey: storageKey, queryFn: ({ signal }) => systemStorage(signal) });
  const data = status.data;
  const last = data?.backups.last as { ok?: boolean; at?: string; database_bytes?: number } | null | undefined;
  const drill = data?.backups.drill as { ok?: boolean; at?: string } | null | undefined;
  const when = (iso?: string) =>
    iso ? format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" }) : "—";
  const size = (bytes: number) =>
    format.number(bytes / 1_000_000, { style: "unit", unit: "megabyte", unitDisplay: "short", maximumFractionDigits: 1 });
  return (
    <Card id="backups">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {data?.warnings
          .filter((w): w is (typeof WARNINGS)[number] => (WARNINGS as readonly string[]).includes(w))
          .map((w) => (
            <p
              key={w}
              role="alert"
              className="rounded-md border border-amber-400/50 bg-amber-400/10 px-3 py-2 text-amber-800 dark:text-amber-200"
            >
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
  );
}

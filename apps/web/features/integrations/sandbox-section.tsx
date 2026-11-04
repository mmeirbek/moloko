"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { integrationsStatus, toolingKeys } from "@/lib/api/tooling";
import { ErrorState } from "@/features/system/query-state";

export function SandboxSection() {
  const t = useTranslations("integrations.sandbox");
  const status = useQuery({ queryKey: toolingKeys.status, queryFn: ({ signal }) => integrationsStatus(signal) });
  const s = status.data?.sandbox;
  const limits = (s?.limits ?? {}) as { cpus?: number; memory_mb?: number; pids?: number; timeout_seconds?: number };
  return (
    <Card id="sandbox">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        {status.isError ? (
          <ErrorState error={status.error} onRetry={() => status.refetch()} />
        ) : (
          <p role="status">{!s ? "…" : !s.configured ? t("notConfigured") : s.ok ? t("ok") : t("down")}</p>
        )}
        {s?.configured && s.ok && (
          <dl className="grid gap-1 sm:grid-cols-[12rem_1fr]">
            <dt className="text-muted-foreground">{t("image")}</dt>
            <dd className="font-mono text-xs">{s.image}</dd>
            <dt className="text-muted-foreground">{t("limits")}</dt>
            <dd>
              {t("limitsValue", {
                cpus: limits.cpus ?? 0,
                memory: limits.memory_mb ?? 0,
                pids: limits.pids ?? 0,
                timeout: limits.timeout_seconds ?? 0,
              })}
            </dd>
            <dt className="text-muted-foreground">{t("network")}</dt>
            <dd>{t("noNetwork")}</dd>
          </dl>
        )}
        {s && (
          <p className="text-xs text-muted-foreground">
            {t("commands")}: <span className="font-mono">{s.allowed_commands.join(" ")}</span>
          </p>
        )}
        <p className="border-t pt-2 text-sm">{status.data?.web_search ? t("searchOn") : t("searchOff")}</p>
      </CardContent>
    </Card>
  );
}

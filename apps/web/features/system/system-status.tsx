"use client";

import { useQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { authKeys, getHealth, getMe, systemKeys } from "@/lib/api/auth";
import { cn } from "@/lib/utils";

function StatusRow({ label, ok }: { label: string; ok: boolean | null }) {
  const t = useTranslations("system");
  return (
    <div className="flex items-center justify-between py-2 text-sm">
      <span>{label}</span>
      <span className="flex items-center gap-2">
        <span
          aria-hidden="true"
          className={cn(
            "size-2 rounded-full",
            ok === null ? "bg-muted-foreground" : ok ? "bg-grass" : "bg-destructive",
          )}
        />
        {ok === null ? "…" : ok ? t("ok") : t("error")}
      </span>
    </div>
  );
}

export function SystemStatus() {
  const t = useTranslations("system");
  const health = useQuery({
    queryKey: systemKeys.health,
    queryFn: ({ signal }) => getHealth(signal),
    refetchInterval: 15_000,
  });
  const data = health.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        {data && <CardDescription>{t("version", { version: data.version })}</CardDescription>}
      </CardHeader>
      <CardContent className="divide-y">
        <StatusRow label={t("api")} ok={health.isError ? false : data ? true : null} />
        <StatusRow label={t("database")} ok={data ? data.checks.database === "ok" : null} />
        <StatusRow label={t("redis")} ok={data ? data.checks.redis === "ok" : null} />
      </CardContent>
    </Card>
  );
}

export function AccountCard() {
  const t = useTranslations();
  const format = useFormatter();
  const me = useQuery({ queryKey: authKeys.me, queryFn: ({ signal }) => getMe(signal) });
  if (!me.data) return null;
  const { user, session } = me.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("system.account")}</CardTitle>
        <CardDescription>
          {t("auth.signedInAs", { name: user.display_name || user.username })}
        </CardDescription>
      </CardHeader>
      <CardContent className="text-sm text-muted-foreground">
        {t("system.sessionExpires", {
          date: format.dateTime(new Date(session.expires_at), {
            dateStyle: "medium",
            timeStyle: "short",
          }),
        })}
      </CardContent>
    </Card>
  );
}

"use client";

import type { MeResponse } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { authKeys, getHealth, getMe, systemKeys, updateProfile } from "@/lib/api/auth";
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
            "size-2",
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
      <CardContent className="flex flex-col gap-4">
        <AddressForm current={user.address_as} />
        <p className="text-xs text-muted-foreground">
          {t("system.sessionExpires", {
            date: format.dateTime(new Date(session.expires_at), { dateStyle: "medium", timeStyle: "short" }),
          })}
        </p>
      </CardContent>
    </Card>
  );
}

/** How moloko addresses the owner: one line, used in the chat and in every agent's answers. */
function AddressForm({ current }: { current: string | null }) {
  const t = useTranslations("profile");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [value, setValue] = useState(current ?? "");
  const save = useMutation({
    mutationFn: () => updateProfile({ address_as: value.trim() || null }),
    onSuccess: (user) => {
      queryClient.setQueryData<MeResponse>(authKeys.me, (me) => (me ? { ...me, user } : me));
    },
  });
  const changed = (value.trim() || null) !== current;
  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (changed) save.mutate();
      }}
    >
      <Label htmlFor="address-as">{t("addressAs")}</Label>
      <div className="flex flex-wrap gap-3">
        <Input
          id="address-as"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={t("addressAsPlaceholder")}
          aria-describedby="address-as-hint"
          className="min-w-0 flex-1 basis-56"
        />
        <Button type="submit" variant="outline" disabled={!changed || save.isPending}>
          {t("save")}
        </Button>
      </div>
      <p id="address-as-hint" className="text-xs text-muted-foreground">
        {t("addressAsHint")}
      </p>
      {save.isSuccess && !changed && (
        <p role="status" className="text-xs text-grass">
          {t("saved")}
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(save.error).message}
        </p>
      )}
    </form>
  );
}

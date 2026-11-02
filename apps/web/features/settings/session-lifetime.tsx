"use client";

import type { SessionSettingsOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { ErrorState, LoadingState } from "@/features/system/query-state";
import { authKeys, getSessionSettings, updateSessionSettings } from "@/lib/api/auth";

/** Common choices, in hours; only those inside the server's bounds are offered. */
const PRESETS = [1, 12, 24, 72, 168, 336, 720, 2160];

type Unit = "hours" | "days";

/** "7 days", "12 hours" — whole days when it divides evenly. */
function useDuration() {
  const format = useFormatter();
  return (hours: number) =>
    hours % 24 === 0
      ? format.number(hours / 24, { style: "unit", unit: "day", unitDisplay: "long" })
      : format.number(hours, { style: "unit", unit: "hour", unitDisplay: "long" });
}

/**
 * How long a sign-in lasts, chosen by the owner (spec: sessions with expiry) and confirmed
 * with the moloko password, so a borrowed or stolen session cannot lengthen itself.
 */
export function SessionLifetimeCard() {
  const t = useTranslations("settings.session");
  const settings = useQuery({ queryKey: authKeys.sessionSettings, queryFn: ({ signal }) => getSessionSettings(signal) });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {settings.isPending && <LoadingState />}
        {settings.isError && <ErrorState error={settings.error} onRetry={() => settings.refetch()} />}
        {settings.data && <SessionLifetimeForm data={settings.data} />}
      </CardContent>
    </Card>
  );
}

function SessionLifetimeForm({ data }: { data: SessionSettingsOut }) {
  const t = useTranslations("settings.session");
  const format = useFormatter();
  const duration = useDuration();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const presets = PRESETS.filter((h) => h >= data.min_hours && h <= data.max_hours);
  const initial = data.uses_default ? "default" : presets.includes(data.ttl_hours) ? String(data.ttl_hours) : "custom";
  const [choice, setChoice] = useState(initial);
  const [amount, setAmount] = useState(() => String(data.ttl_hours % 24 === 0 ? data.ttl_hours / 24 : data.ttl_hours));
  const [unit, setUnit] = useState<Unit>(data.ttl_hours % 24 === 0 ? "days" : "hours");
  const [password, setPassword] = useState("");
  const [saved, setSaved] = useState<string | null>(null);

  const customHours = Math.round(Number(amount) * (unit === "days" ? 24 : 1));
  const customValid = Number.isFinite(customHours) && customHours >= data.min_hours && customHours <= data.max_hours;
  const ttl = choice === "default" ? null : choice === "custom" ? customHours : Number(choice);

  const save = useMutation({
    mutationFn: () => updateSessionSettings({ ttl_hours: ttl, password }),
    onSuccess: (updated) => {
      setPassword("");
      setSaved(updated.current_session_expires_at);
      queryClient.setQueryData(authKeys.sessionSettings, updated);
      void queryClient.invalidateQueries({ queryKey: authKeys.me }); // "this sign-in lasts until …"
    },
    onError: () => setPassword(""),
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    setSaved(null);
    if (choice === "custom" && !customValid) return;
    save.mutate();
  }

  const date = (iso: string) => format.dateTime(new Date(iso), { dateStyle: "medium", timeStyle: "short" });

  return (
    <form className="flex flex-col gap-4" onSubmit={submit} data-testid="session-lifetime">
      <div className="flex flex-col gap-1 text-sm">
        <p>
          {data.uses_default
            ? t("currentDefault", { duration: duration(data.ttl_hours) })
            : t("current", { duration: duration(data.ttl_hours) })}
        </p>
        <p className="text-muted-foreground">{t("expires", { date: date(data.current_session_expires_at) })}</p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="session-ttl">{t("duration")}</Label>
          <select
            id="session-ttl"
            value={choice}
            onChange={(e) => setChoice(e.target.value)}
            className="h-10 rounded-md border border-input bg-background px-2 text-base md:text-sm"
          >
            <option value="default">{t("defaultOption", { duration: duration(data.default_ttl_hours) })}</option>
            {presets.map((h) => (
              <option key={h} value={String(h)}>
                {duration(h)}
              </option>
            ))}
            <option value="custom">{t("custom")}</option>
          </select>
        </div>
        {choice === "custom" && (
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="session-amount">{t("amount")}</Label>
            <div className="flex gap-2">
              <Input
                id="session-amount"
                type="number"
                inputMode="numeric"
                min={1}
                step={1}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                aria-invalid={!customValid}
                aria-describedby="session-range"
                className="min-w-0 flex-1"
              />
              <select
                aria-label={t("unit")}
                value={unit}
                onChange={(e) => setUnit(e.target.value as Unit)}
                className="h-10 rounded-md border border-input bg-background px-2 text-base md:text-sm"
              >
                <option value="hours">{t("hours")}</option>
                <option value="days">{t("days")}</option>
              </select>
            </div>
            <p id="session-range" className={customValid ? "text-xs text-muted-foreground" : "text-xs text-destructive"}>
              {t("range", { min: duration(data.min_hours), max: duration(data.max_hours) })}
            </p>
          </div>
        )}
      </div>
      <div className="flex flex-col gap-1.5 sm:max-w-sm">
        <Label htmlFor="session-password">{t("password")}</Label>
        <Input
          id="session-password"
          type="password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-describedby="session-password-hint"
        />
        <p id="session-password-hint" className="text-xs text-muted-foreground">
          {t("passwordHint")}
        </p>
      </div>
      <p className="text-xs text-muted-foreground">{t("otherDevices")}</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={save.isPending || !password || (choice === "custom" && !customValid)}>
          {t("save")}
        </Button>
        {saved && (
          <p role="status" className="text-sm text-grass">
            {t("saved", { date: date(saved) })}
          </p>
        )}
        {save.isError && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(save.error).message}
          </p>
        )}
      </div>
    </form>
  );
}

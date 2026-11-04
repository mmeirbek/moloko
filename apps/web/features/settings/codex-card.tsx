"use client";

import type { ProviderOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Check, Copy, RefreshCw } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { modelKeys } from "@/lib/api/chat";
import { codexStatus, createProvider, providerKeys, syncModels } from "@/lib/api/providers";

/**
 * Codex with the owner's ChatGPT sign-in (owner: «Вариант 2 — Codex с входом через ChatGPT,
 * чтоб я мог использовать модели для кодинга»). The sign-in happens on the server (the device
 * code flow, in the codex container); here: whether it worked, the command, and «Подключить»,
 * which adds the plan's models as a provider.
 */
export function CodexCard({ providers }: { providers: ProviderOut[] | undefined }) {
  const t = useTranslations("settings.codex");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const status = useQuery({ queryKey: providerKeys.codex, queryFn: ({ signal }) => codexStatus(signal) });
  const [copied, setCopied] = useState(false);
  const [added, setAdded] = useState<number | null>(null);
  const existing = (providers ?? []).find((p) => p.kind === "codex");
  const connect = useMutation({
    mutationFn: async () => {
      const provider = existing ?? (await createProvider({ kind: "codex", name: "Codex (ChatGPT)" }));
      return syncModels(provider.id);
    },
    onSuccess: (result) => {
      setAdded(result.total);
      void queryClient.invalidateQueries({ queryKey: providerKeys.list });
      void queryClient.invalidateQueries({ queryKey: providerKeys.models });
      void queryClient.invalidateQueries({ queryKey: modelKeys.picker });
    },
  });
  const s = status.data;
  if (!s) return null;

  async function copy(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
    } catch {
      // no clipboard (http, old browser): the command is on screen to select
    }
  }

  return (
    <Card data-testid="codex-card">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 text-sm">
        {!s.configured ? (
          <p className="text-muted-foreground">{t("off")}</p>
        ) : !s.reachable ? (
          <p role="alert" className="text-destructive">
            {t("unreachable")}
          </p>
        ) : (
          <>
            <p className={s.logged_in ? "inline-flex items-center gap-1.5 text-grass" : "text-muted-foreground"} role="status">
              {s.logged_in && <Check className="size-4" />}
              {s.logged_in ? t("signedIn", { mode: s.mode === "chatgpt" ? "ChatGPT" : (s.mode ?? "") }) : t("notSignedIn")}
              {s.version && <span className="text-xs text-muted-foreground">· {s.version}</span>}
            </p>
            {!s.logged_in && (
              <ol className="flex list-decimal flex-col gap-2 pl-5">
                <li>{t("step1")}</li>
                <li className="flex flex-col gap-1.5">
                  {t("step2")}
                  <span className="flex items-center gap-2">
                    <code className="min-w-0 flex-1 overflow-x-auto rounded bg-muted px-2 py-1 font-mono text-xs whitespace-nowrap" data-testid="codex-login-command">
                      {s.login_command}
                    </code>
                    <Button type="button" size="sm" variant="ghost" onClick={() => void copy(s.login_command)}>
                      {copied ? <Check /> : <Copy />} {copied ? t("copied") : t("copy")}
                    </Button>
                  </span>
                </li>
                <li>{t("step3")}</li>
              </ol>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="outline" size="sm" onClick={() => void status.refetch()} disabled={status.isFetching}>
                <RefreshCw /> {t("check")}
              </Button>
              <Button type="button" size="sm" onClick={() => connect.mutate()} disabled={!s.logged_in || connect.isPending}>
                {connect.isPending ? t("connecting") : existing ? t("refresh") : t("connect")}
              </Button>
              {existing && <span className="text-xs text-grass">{t("connected")}</span>}
              {added !== null && (
                <span role="status" className="text-xs text-muted-foreground">
                  {t("added", { count: added })}
                </span>
              )}
            </div>
            {connect.error && (
              <p role="alert" className="text-xs text-destructive">
                {toMessage(connect.error).message}
              </p>
            )}
          </>
        )}
        <p className="text-xs text-muted-foreground">{t("caution")}</p>
      </CardContent>
    </Card>
  );
}

"use client";

import type { FreeProviderOut, ProviderOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Check, ExternalLink } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { modelKeys } from "@/lib/api/chat";
import { createProvider, freeCatalog, providerKeys, syncModels } from "@/lib/api/providers";

/** The address prefix that marks a provider as this platform (also with an account id in it). */
const prefixOf = (p: FreeProviderOut) => p.base_url.replace(/\/$/, "").split("{account_id}")[0]!;

function Platform({ platform, connected }: { platform: FreeProviderOut; connected: boolean }) {
  const t = useTranslations("settings.freeProviders");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [key, setKey] = useState("");
  const [account, setAccount] = useState("");
  const [added, setAdded] = useState<number | null>(null);
  const connect = useMutation({
    mutationFn: async () => {
      const provider = await createProvider({
        kind: "openai",
        name: platform.name,
        api_key: key.trim(),
        base_url: platform.base_url.replace("{account_id}", account.trim()),
      });
      return syncModels(provider.id);
    },
    onSuccess: (result) => {
      setAdded(result.added);
      setKey("");
      setOpen(false);
      void queryClient.invalidateQueries({ queryKey: providerKeys.list });
      void queryClient.invalidateQueries({ queryKey: providerKeys.models });
      void queryClient.invalidateQueries({ queryKey: modelKeys.picker });
    },
  });
  const id = `free-${platform.key}`;
  // the server's list may name a platform these texts do not know yet
  const text = (name: "allowance" | "caution") => {
    const key = `platforms.${platform.key}.${name}` as Parameters<typeof t>[0];
    return t.has(key) ? t(key) : null;
  };
  const caution = text("caution");

  function submit(e: FormEvent) {
    e.preventDefault();
    if (key.trim() && (!platform.needs_account || account.trim())) connect.mutate();
  }

  return (
    <li className="flex flex-col gap-2 py-3" data-testid={`free-${platform.key}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-medium">{platform.name}</span>
        {connected && (
          <span className="inline-flex items-center gap-1 text-xs text-grass">
            <Check className="size-3.5" /> {t("connected")}
          </span>
        )}
        <span className="min-w-0 flex-1" />
        <a href={platform.key_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-sky hover:underline">
          {t("getKey")} <ExternalLink className="size-3" />
        </a>
        {!open && (
          <Button size="sm" variant={connected ? "ghost" : "outline"} onClick={() => setOpen(true)}>
            {connected ? t("addAnother") : t("connect")}
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        {text("allowance")}
        {caution && <span> · ⚠ {caution}</span>}
      </p>
      {added !== null && (
        <p role="status" className="text-xs text-grass">
          {t("added", { count: added })}
        </p>
      )}
      {open && (
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row sm:items-end">
          {platform.needs_account && (
            <div className="flex flex-col gap-1">
              <Label htmlFor={`${id}-account`}>{t("account")}</Label>
              <Input id={`${id}-account`} value={account} onChange={(e) => setAccount(e.target.value)} autoComplete="off" />
            </div>
          )}
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <Label htmlFor={`${id}-key`}>{t("key")}</Label>
            <Input id={`${id}-key`} type="password" value={key} onChange={(e) => setKey(e.target.value)} autoComplete="off" autoFocus />
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={connect.isPending || !key.trim()}>
              {connect.isPending ? t("connecting") : t("connect")}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
          </div>
        </form>
      )}
      {connect.error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(connect.error).message}
        </p>
      )}
    </li>
  );
}

/**
 * Free models (owner: «использовать все модели из freellmapi»): platforms whose official API has
 * a free tier. The owner gets a key there (the link), pastes it, and the platform's free chat
 * models are added; the Orchestrator then picks among them by what each is best at.
 */
export function FreeProvidersCard({ providers }: { providers: ProviderOut[] | undefined }) {
  const t = useTranslations("settings.freeProviders");
  const catalog = useQuery({ queryKey: providerKeys.free, queryFn: ({ signal }) => freeCatalog(signal) });
  if (!catalog.data) return null;
  const has = (p: FreeProviderOut) => (providers ?? []).some((x) => (x.base_url ?? "").startsWith(prefixOf(p)));
  return (
    <Card data-testid="free-providers">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-1">
        <ul className="divide-y">
          {catalog.data.map((p) => (
            <Platform key={p.key} platform={p} connected={has(p)} />
          ))}
        </ul>
        <p className="text-xs text-muted-foreground">{t("privacy")}</p>
      </CardContent>
    </Card>
  );
}

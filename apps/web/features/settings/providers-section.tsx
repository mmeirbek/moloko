"use client";

import type { ModelOut, ProviderOut, ProviderTestResult } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { modelKeys } from "@/lib/api/chat";
import {
  createModel,
  createProvider,
  getProviderKinds,
  listAllModels,
  listProviders,
  providerKeys,
  syncModels,
  testProvider,
  updateModel,
  updateProvider,
} from "@/lib/api/providers";

// Brand names stay as they are; the offline test provider gets a translated name.
const KIND_LABEL: Record<string, string> = { openai: "OpenAI", anthropic: "Anthropic" };

function useKindLabel(): (kind: string) => string {
  const t = useTranslations("settings.providers");
  return (kind) => (kind === "mock" ? t("mockKind") : (KIND_LABEL[kind] ?? kind));
}

function useInvalidateAll() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: providerKeys.list });
    void queryClient.invalidateQueries({ queryKey: providerKeys.models });
    void queryClient.invalidateQueries({ queryKey: modelKeys.picker });
  };
}

function AddProviderForm({ kinds }: { kinds: string[] }) {
  const t = useTranslations("settings.providers");
  const kindLabel = useKindLabel();
  const toMessage = useErrorMessage();
  const invalidate = useInvalidateAll();
  const [kind, setKind] = useState(kinds[0] ?? "openai");
  const [name, setName] = useState("");
  const [apiKey, setApiKey] = useState("");
  const create = useMutation({
    mutationFn: async () => {
      const provider = await createProvider({
        kind: kind as "openai" | "anthropic" | "mock",
        name: name.trim() || kindLabel(kind),
        api_key: apiKey || null,
      });
      // Import the provider's model list right away when possible.
      await syncModels(provider.id).catch(() => undefined);
      return provider;
    },
    onSuccess: () => {
      setName("");
      setApiKey("");
      invalidate();
    },
  });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    create.mutate();
  }

  return (
    <form onSubmit={onSubmit} className="grid gap-3 rounded-md border p-4 md:grid-cols-[auto_1fr_1fr_auto] md:items-end">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="provider-kind">{t("kind")}</Label>
        <select
          id="provider-kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
        >
          {kinds.map((k) => (
            <option key={k} value={k}>
              {kindLabel(k)}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="provider-name">{t("name")}</Label>
        <Input id="provider-name" value={name} placeholder={kindLabel(kind)} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="provider-key">{t("apiKey")}</Label>
        <Input
          id="provider-key"
          type="password"
          autoComplete="off"
          value={apiKey}
          placeholder={kind === "mock" ? t("noKeyNeeded") : t("apiKeyPlaceholder")}
          disabled={kind === "mock"}
          onChange={(e) => setApiKey(e.target.value)}
        />
      </div>
      <Button type="submit" disabled={create.isPending}>
        {t("add")}
      </Button>
      {create.error && (
        <p role="alert" className="text-sm text-destructive md:col-span-4">
          {toMessage(create.error).message}
        </p>
      )}
      <p className="text-xs text-muted-foreground md:col-span-4">{t("keyPolicy")}</p>
    </form>
  );
}

function ProviderRow({ provider }: { provider: ProviderOut }) {
  const t = useTranslations("settings.providers");
  const kindLabel = useKindLabel();
  const confirm = useConfirm();
  const toMessage = useErrorMessage();
  const invalidate = useInvalidateAll();
  const [result, setResult] = useState<ProviderTestResult | null>(null);
  const [newKey, setNewKey] = useState("");
  const [editingKey, setEditingKey] = useState(false);

  const test = useMutation({ mutationFn: () => testProvider(provider.id), onSuccess: setResult });
  const sync = useMutation({ mutationFn: () => syncModels(provider.id), onSuccess: invalidate });
  const update = useMutation({
    mutationFn: (body: Parameters<typeof updateProvider>[1]) => updateProvider(provider.id, body),
    onSuccess: () => {
      setEditingKey(false);
      setNewKey("");
      invalidate();
    },
  });
  const error = test.error ?? sync.error ?? update.error;

  const keyText =
    provider.api_key_source === "stored"
      ? t("keyStored", { hint: provider.api_key_hint ?? "" })
      : provider.api_key_source === "environment"
        ? t("keyEnv")
        : t("keyMissing");

  return (
    <li className="flex flex-col gap-2 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">
            {provider.name}{" "}
            <span className="text-xs font-normal text-muted-foreground">{kindLabel(provider.kind)}</span>
          </p>
          <p className="text-xs text-muted-foreground">{keyText}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1">
          <Button size="sm" variant="outline" onClick={() => test.mutate()} disabled={test.isPending}>
            {t("test")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => sync.mutate()} disabled={sync.isPending}>
            {t("sync")}
          </Button>
          {provider.kind !== "mock" && (
            <Button size="sm" variant="ghost" onClick={() => setEditingKey((v) => !v)}>
              {t("replaceKey")}
            </Button>
          )}
          <label className="flex items-center gap-1.5 px-2 text-sm">
            <input
              type="checkbox"
              checked={provider.enabled}
              onChange={(e) => update.mutate({ enabled: e.target.checked })}
            />
            {t("enabled")}
          </label>
        </div>
      </div>
      {editingKey && (
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (newKey) update.mutate({ api_key: newKey });
          }}
        >
          <Input
            type="password"
            autoComplete="off"
            value={newKey}
            placeholder={t("apiKeyPlaceholder")}
            onChange={(e) => setNewKey(e.target.value)}
            className="max-w-sm"
          />
          <Button size="sm" type="submit" disabled={!newKey || update.isPending}>
            {t("saveKey")}
          </Button>
          {provider.api_key_source === "stored" && (
            <Button
              size="sm"
              variant="ghost"
              type="button"
              disabled={update.isPending}
              onClick={async () => {
                if (await confirm({ title: t("clearKeyConfirm"), confirmLabel: t("clearKey"), destructive: true }))
                  update.mutate({ clear_api_key: true });
              }}
            >
              {t("clearKey")}
            </Button>
          )}
        </form>
      )}
      {result && (
        <p role="status" className={result.ok ? "text-sm text-grass" : "text-sm text-destructive"}>
          {result.ok ? t("testOk", { count: result.models_found ?? 0 }) : result.error_message}
        </p>
      )}
      {sync.data && <p className="text-sm text-muted-foreground">{t("synced", { added: sync.data.added })}</p>}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(error).message}
        </p>
      )}
    </li>
  );
}

function ModelRow({ model }: { model: ModelOut }) {
  const t = useTranslations("settings.models");
  const toMessage = useErrorMessage();
  const invalidate = useInvalidateAll();
  const update = useMutation({
    mutationFn: (body: Parameters<typeof updateModel>[1]) => updateModel(model.id, body),
    onSuccess: invalidate,
  });
  return (
    <li className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
      <div className="min-w-0">
        <p className="truncate font-mono">{model.display_name || model.model}</p>
        <p className="text-xs text-muted-foreground">{model.provider_name}</p>
      </div>
      <div className="flex items-center gap-3">
        <label className="flex items-center gap-1.5">
          <input
            type="checkbox"
            checked={model.enabled}
            disabled={update.isPending}
            onChange={(e) => update.mutate({ enabled: e.target.checked })}
          />
          {t("enabled")}
        </label>
        <label className="flex items-center gap-1.5">
          <input
            type="radio"
            name="default-model"
            checked={model.is_default}
            disabled={update.isPending}
            onChange={() => update.mutate({ is_default: true })}
          />
          {t("default")}
        </label>
      </div>
      {update.error && (
        <p role="alert" className="w-full text-xs text-destructive">
          {toMessage(update.error).message}
        </p>
      )}
    </li>
  );
}

function AddModelForm({ providers }: { providers: ProviderOut[] }) {
  const t = useTranslations("settings.models");
  const toMessage = useErrorMessage();
  const invalidate = useInvalidateAll();
  const [chosenProvider, setProviderId] = useState("");
  const providerId = providers.some((p) => p.id === chosenProvider) ? chosenProvider : (providers[0]?.id ?? "");
  const [model, setModel] = useState("");
  const add = useMutation({
    mutationFn: () => createModel({ provider_id: providerId, model: model.trim() }),
    onSuccess: () => {
      setModel("");
      invalidate();
    },
  });
  if (providers.length === 0) return null;
  return (
    <form
      className="flex flex-wrap items-end gap-2 pt-3"
      onSubmit={(e) => {
        e.preventDefault();
        if (model.trim()) add.mutate();
      }}
    >
      <select
        aria-label={t("provider")}
        value={providerId}
        onChange={(e) => setProviderId(e.target.value)}
        className="h-10 rounded-md border border-input bg-background px-2 text-sm"
      >
        {providers.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <Input
        aria-label={t("modelId")}
        placeholder={t("modelId")}
        value={model}
        onChange={(e) => setModel(e.target.value)}
        className="max-w-xs"
      />
      <Button type="submit" variant="outline" disabled={add.isPending}>
        {t("add")}
      </Button>
      {add.error && (
        <p role="alert" className="w-full text-sm text-destructive">
          {toMessage(add.error).message}
        </p>
      )}
    </form>
  );
}

export function ProvidersSection() {
  const t = useTranslations("settings");
  const kinds = useQuery({ queryKey: providerKeys.kinds, queryFn: ({ signal }) => getProviderKinds(signal) });
  const providers = useQuery({ queryKey: providerKeys.list, queryFn: ({ signal }) => listProviders(signal) });
  const models = useQuery({ queryKey: providerKeys.models, queryFn: ({ signal }) => listAllModels(signal) });

  return (
    <>
      <Card>
        <CardHeader>
          <CardTitle>{t("providers.title")}</CardTitle>
          <CardDescription>{t("providers.description")}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {kinds.data && <AddProviderForm kinds={kinds.data} />}
          <ul className="divide-y">
            {providers.data?.map((p) => <ProviderRow key={p.id} provider={p} />)}
          </ul>
          {providers.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("providers.none")}</p>}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("models.title")}</CardTitle>
          <CardDescription>{t("models.description")}</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="max-h-96 divide-y overflow-y-auto">
            {models.data?.map((m) => <ModelRow key={m.id} model={m} />)}
          </ul>
          {models.data?.length === 0 && <p className="text-sm text-muted-foreground">{t("models.none")}</p>}
          {providers.data && <AddModelForm providers={providers.data} />}
        </CardContent>
      </Card>
    </>
  );
}

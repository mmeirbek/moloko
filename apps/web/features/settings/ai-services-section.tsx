"use client";

import type { ProviderOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { listProviders, providerKeys } from "@/lib/api/providers";
import { getAiServices, searchKeys, searchStatus, updateAiServices } from "@/lib/api/search";

/** Settings → Voice & search: which provider turns speech into text and builds the search index. */
export function AiServicesSection() {
  const t = useTranslations("aiServices");
  const ai = useQuery({ queryKey: searchKeys.ai, queryFn: ({ signal }) => getAiServices(signal) });
  if (!ai.data) return null;
  // Mounted once with the loaded values: saving must not reset the form (and its "Saved" state).
  return <AiServicesForm data={ai.data} title={t("title")} />;
}

function AiServicesForm({ data, title }: { data: NonNullable<Awaited<ReturnType<typeof getAiServices>>>; title: string }) {
  const t = useTranslations("aiServices");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const providers = useQuery({ queryKey: providerKeys.list, queryFn: ({ signal }) => listProviders(signal) });
  const status = useQuery({ queryKey: searchKeys.status, queryFn: ({ signal }) => searchStatus(signal) });
  const [provider, setProvider] = useState(data.provider_id ?? "");
  const [voiceModel, setVoiceModel] = useState(data.transcription_model);
  const [embedModel, setEmbedModel] = useState(data.embedding_model);
  const [semantic, setSemantic] = useState(data.semantic_search);
  const capable = (providers.data ?? []).filter((p: ProviderOut) => p.kind === "openai" || p.kind === "mock");
  const save = useMutation({
    mutationFn: () =>
      updateAiServices({
        provider_id: provider || null,
        transcription_model: voiceModel.trim() || null,
        embedding_model: embedModel.trim() || null,
        semantic_search: semantic,
      }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ["ai"] }),
  });
  return (
    <Card data-testid="ai-services">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <p className="text-sm">
            {data.available ? t("active", { name: data.active_provider_name ?? "" }) : t("unavailable")}
          </p>
          <div className="grid gap-3 sm:grid-cols-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ai-provider">{t("provider")}</Label>
              <select
                id="ai-provider"
                value={provider}
                onChange={(e) => setProvider(e.target.value)}
                className="h-10 rounded-md border border-input bg-background px-2 text-base md:text-sm"
              >
                <option value="">{t("auto")}</option>
                {capable.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ai-voice">{t("voiceModel")}</Label>
              <Input id="ai-voice" value={voiceModel} onChange={(e) => setVoiceModel(e.target.value)} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="ai-embed">{t("embedModel")}</Label>
              <Input id="ai-embed" value={embedModel} onChange={(e) => setEmbedModel(e.target.value)} />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" className="size-4" checked={semantic} onChange={(e) => setSemantic(e.target.checked)} />
            {t("semantic")}
          </label>
          {status.data && (
            <p className="text-xs text-muted-foreground">
              {t("index", { sources: status.data.sources, chunks: status.data.chunks, vectors: status.data.with_vectors })}
            </p>
          )}
          {save.error && (
            <p role="alert" className="text-sm text-destructive">
              {toMessage(save.error).message}
            </p>
          )}
          <Button type="submit" className="self-start" disabled={save.isPending}>
            {save.isSuccess ? t("saved") : t("save")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

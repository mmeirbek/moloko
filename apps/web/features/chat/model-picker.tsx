"use client";

import type { ModelOut } from "@moloko/shared-types";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

export function modelLabel(m: ModelOut) {
  return m.display_name || m.model;
}

export function ModelPicker({
  models,
  value,
  onChange,
  className,
}: {
  models: ModelOut[];
  value: string | null;
  onChange: (id: string | null) => void;
  className?: string;
}) {
  const t = useTranslations("chat");
  const byProvider = new Map<string, ModelOut[]>();
  for (const m of models) byProvider.set(m.provider_name, [...(byProvider.get(m.provider_name) ?? []), m]);
  const fallback = models.find((m) => m.is_default);

  return (
    <select
      aria-label={t("model")}
      className={cn(
        "h-9 max-w-52 truncate rounded-md border border-input bg-background px-2 text-sm",
        className,
      )}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value || null)}
    >
      <option value="">
        {t("defaultModel")}
        {fallback ? ` (${modelLabel(fallback)})` : ""}
      </option>
      {[...byProvider.entries()].map(([provider, list]) => (
        <optgroup key={provider} label={provider}>
          {list.map((m) => (
            <option key={m.id} value={m.id}>
              {modelLabel(m)}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}

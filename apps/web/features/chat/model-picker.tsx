"use client";

import type { ModelOut } from "@moloko/shared-types";
import { useTranslations } from "next-intl";

import { ChevronDown } from "@/components/icons";
import { cn } from "@/lib/utils";

export function modelLabel(m: ModelOut) {
  return m.display_name || m.model;
}

/**
 * The model for this chat, as a quiet pill in the composer's toolbar. "Default" shows the
 * default model's own name, so the owner always sees which model will answer.
 */
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
    <span className={cn("relative inline-flex min-w-0 items-center", className)}>
      <select
        aria-label={t("model")}
        title={t("model")}
        className="h-9 max-w-44 min-w-0 cursor-pointer appearance-none truncate bg-transparent pr-7 pl-3 text-xs text-muted-foreground transition-colors outline-none hover:bg-accent hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring sm:max-w-56"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">{fallback ? t("defaultModelNamed", { name: modelLabel(fallback) }) : t("defaultModel")}</option>
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
      <ChevronDown className="pointer-events-none absolute right-2.5 size-3.5 text-muted-foreground" aria-hidden />
    </span>
  );
}

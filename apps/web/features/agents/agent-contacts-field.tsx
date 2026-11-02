"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useId } from "react";

import { agentKeys, listAgents } from "@/lib/api/agents";
import { cn } from "@/lib/utils";

import { CONTACT_MODES, toggleContact, type AgentFormValues } from "./agent-form-model";

/**
 * «С кем может общаться»: the colleagues this agent may ask or tell directly, without the
 * Orchestrator. The rule is mutual — both agents must allow each other.
 */
export function AgentContactsField({
  agentId,
  values,
  onChange,
}: {
  agentId?: string;
  values: AgentFormValues;
  onChange: (values: AgentFormValues) => void;
}) {
  const t = useTranslations("agents.form.contacts");
  const uid = useId();
  const agents = useQuery({ queryKey: agentKeys.all, queryFn: ({ signal }) => listAgents(signal) });
  const colleagues = (agents.data ?? [])
    .filter((a) => a.agent_type === "autonomous" && a.id !== agentId)
    .sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="flex flex-col gap-3" data-testid="agent-contacts">
      <div role="radiogroup" aria-label={t("title")} className="grid gap-3 sm:grid-cols-3">
        {CONTACT_MODES.map((mode) => (
          <label
            key={mode}
            className={cn(
              "flex cursor-pointer flex-col gap-1 bg-card p-3 text-sm pixel-frame",
              values.contactMode === mode && "bg-accent [--frame-color:var(--color-ring)]",
            )}
          >
            <span className="flex items-center gap-2">
              <input
                type="radio"
                name={`${uid}-contacts`}
                value={mode}
                checked={values.contactMode === mode}
                onChange={() => onChange({ ...values, contactMode: mode })}
              />
              {t(`modes.${mode}.title`)}
            </span>
            <span className="text-xs text-muted-foreground">{t(`modes.${mode}.body`)}</span>
          </label>
        ))}
      </div>
      {values.contactMode === "list" &&
        (colleagues.length === 0 ? (
          <p className="text-xs text-muted-foreground">{t("noColleagues")}</p>
        ) : (
          <fieldset className="flex flex-col gap-2">
            <legend className="sr-only">{t("pick")}</legend>
            {colleagues.map((a) => (
              <label key={a.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={values.contactIds.includes(a.id)}
                  onChange={(e) => onChange(toggleContact(values, a.id, e.target.checked))}
                />
                <span className="truncate">{a.name}</span>
                {a.specialization && <span className="truncate text-xs text-muted-foreground">· {a.specialization}</span>}
              </label>
            ))}
          </fieldset>
        ))}
      <p className="text-xs text-muted-foreground">{t("note")}</p>
    </div>
  );
}

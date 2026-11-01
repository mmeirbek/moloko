"use client";

import type { AgentOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { modelLabel } from "@/features/chat/model-picker";
import { agentKeys, createAgent, systemLimits, systemLimitsKey, updateAgent } from "@/lib/api/agents";
import { listPickerModels, modelKeys } from "@/lib/api/chat";
import { memoryKeys } from "@/lib/api/memories";
import { toolingKeys } from "@/lib/api/tooling";
import { cn } from "@/lib/utils";

import { AUTONOMY, fromAgent, toPayload, validate, type AgentFormValues, type FormErrors } from "./agent-form-model";
import { AgentToolsField } from "./agent-tools-field";

const textareaClass = "rounded-md border border-input bg-background px-3 py-2 text-base md:text-sm";

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: ReactNode;
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children}
      {error ? (
        <p id={`${id}-error`} className="text-xs text-destructive">
          {error}
        </p>
      ) : (
        hint && <p className="text-xs text-muted-foreground">{hint}</p>
      )}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <fieldset className="flex flex-col gap-4 rounded-lg border bg-card p-4">
      <legend className="px-1 text-sm font-medium">{title}</legend>
      {children}
    </fieldset>
  );
}

/** Create (no ``agent``) or edit an agent profile: model, instructions, autonomy, limits, memory. */
export function AgentForm({ agent, onSaved }: { agent?: AgentOut; onSaved?: (agent: AgentOut) => void }) {
  const t = useTranslations("agents.form");
  const ta = useTranslations("agents");
  const toMessage = useErrorMessage();
  const router = useRouter();
  const queryClient = useQueryClient();
  const uid = useId();
  const models = useQuery({ queryKey: modelKeys.picker, queryFn: ({ signal }) => listPickerModels(signal) });
  const limits = useQuery({ queryKey: systemLimitsKey, queryFn: ({ signal }) => systemLimits(signal) });
  const [values, setValues] = useState<AgentFormValues>(() => fromAgent(agent));
  const [touched, setTouched] = useState(false);
  const [saved, setSaved] = useState(false);
  const errors: FormErrors = validate(values, limits.data);
  const isOrchestrator = agent?.agent_type === "orchestrator";

  const save = useMutation({
    mutationFn: () => (agent ? updateAgent(agent.id, toPayload(values)) : createAgent(toPayload(values))),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      void queryClient.invalidateQueries({ queryKey: memoryKeys.all }); // memory settings change the preview
      void queryClient.invalidateQueries({ queryKey: toolingKeys.tools });
      queryClient.setQueryData(agentKeys.detail(result.id), result);
      setValues(fromAgent(result));
      setTouched(false);
      setSaved(true);
      if (onSaved) onSaved(result);
      else if (!agent) router.push(`/office/agents/${result.id}`);
    },
  });

  const set = <K extends keyof AgentFormValues>(key: K, value: AgentFormValues[K]) => {
    setValues((v) => ({ ...v, [key]: value }));
    setSaved(false);
  };
  const errorText = (key: keyof AgentFormValues) => {
    const e = errors[key];
    if (!e || (!touched && key === "name")) return undefined;
    return t(`errors.${e.error}`, { limit: e.limit ?? 0 });
  };
  const id = (name: string) => `${uid}-${name}`;
  const globalHint = (value: number | undefined, unit: "steps" | "minutes" | "chars") =>
    value === undefined ? undefined : t(`globalLimit.${unit}`, { value });

  function submit(e: FormEvent) {
    e.preventDefault();
    setTouched(true);
    if (Object.keys(errors).length === 0) save.mutate();
  }

  return (
    <form onSubmit={submit} className="flex max-w-3xl flex-col gap-4" noValidate>
      <Section title={t("profile")}>
        <Field id={id("name")} label={ta("name")} error={errorText("name")}>
          <Input
            id={id("name")}
            value={values.name}
            maxLength={100}
            onChange={(e) => set("name", e.target.value)}
            aria-invalid={Boolean(errorText("name"))}
            autoFocus={!agent}
          />
        </Field>
        <Field id={id("description")} label={t("description")} hint={t("descriptionHint")}>
          <Input
            id={id("description")}
            value={values.description}
            maxLength={2000}
            onChange={(e) => set("description", e.target.value)}
          />
        </Field>
        <Field id={id("specialization")} label={t("specialization")} hint={t("specializationHint")}>
          <Input
            id={id("specialization")}
            value={values.specialization}
            maxLength={64}
            onChange={(e) => set("specialization", e.target.value)}
          />
        </Field>
        <Field id={id("model")} label={ta("model")} hint={t("modelHint")}>
          <select
            id={id("model")}
            value={values.modelId}
            onChange={(e) => set("modelId", e.target.value)}
            className="h-10 rounded-md border border-input bg-background px-2 text-sm"
          >
            <option value="">{ta("defaultModel")}</option>
            {models.data?.map((m) => (
              <option key={m.id} value={m.id}>
                {m.provider_name} · {modelLabel(m)}
              </option>
            ))}
            {values.modelId && models.data && !models.data.some((m) => m.id === values.modelId) && (
              <option value={values.modelId}>{t("modelUnavailable")}</option>
            )}
          </select>
        </Field>
        <Field id={id("prompt")} label={ta("systemPrompt")} hint={t("systemPromptHint")}>
          <textarea
            id={id("prompt")}
            rows={6}
            maxLength={20000}
            value={values.systemPrompt}
            onChange={(e) => set("systemPrompt", e.target.value)}
            placeholder={ta("systemPromptHint")}
            className={textareaClass}
          />
        </Field>
      </Section>

      <Section title={t("autonomy")}>
        <div role="radiogroup" aria-label={t("autonomy")} className="grid gap-2 sm:grid-cols-3">
          {AUTONOMY.map((level) => (
            <label
              key={level}
              className={cn(
                "flex cursor-pointer flex-col gap-1 rounded-md border p-3 text-sm has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
                values.autonomy === level && "border-primary bg-accent",
              )}
            >
              <span className="flex items-center gap-2 font-medium">
                <input
                  type="radio"
                  name={id("autonomy")}
                  value={level}
                  checked={values.autonomy === level}
                  onChange={() => set("autonomy", level)}
                />
                {t(`autonomyLevels.${level}.title`)}
              </span>
              <span className="text-xs text-muted-foreground">{t(`autonomyLevels.${level}.body`)}</span>
            </label>
          ))}
        </div>
        <p className="text-xs text-muted-foreground">{t("autonomyNote")}</p>
      </Section>

      <Section title={t("tools")}>
        <AgentToolsField
          values={values}
          onChange={(next) => {
            setValues(next);
            setSaved(false);
          }}
        />
      </Section>

      <Section title={t("limits")}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            id={id("steps")}
            label={t("maxSteps")}
            hint={globalHint(limits.data?.max_steps_per_run, "steps")}
            error={errorText("maxSteps")}
          >
            <Input
              id={id("steps")}
              inputMode="numeric"
              value={values.maxSteps}
              placeholder={limits.data ? String(limits.data.max_steps_per_run) : ""}
              onChange={(e) => set("maxSteps", e.target.value)}
              aria-invalid={Boolean(errorText("maxSteps"))}
            />
          </Field>
          <Field
            id={id("timeout")}
            label={t("timeoutMinutes")}
            hint={globalHint(limits.data ? Math.floor(limits.data.run_timeout_seconds / 60) : undefined, "minutes")}
            error={errorText("timeoutMinutes")}
          >
            <Input
              id={id("timeout")}
              inputMode="numeric"
              value={values.timeoutMinutes}
              placeholder={limits.data ? String(Math.floor(limits.data.run_timeout_seconds / 60)) : ""}
              onChange={(e) => set("timeoutMinutes", e.target.value)}
              aria-invalid={Boolean(errorText("timeoutMinutes"))}
            />
          </Field>
        </div>
      </Section>

      <Section title={t("memory")}>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={values.memoryEnabled}
            onChange={(e) => set("memoryEnabled", e.target.checked)}
          />
          {t("memoryEnabled")}
        </label>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={values.includeShared}
            disabled={!values.memoryEnabled}
            onChange={(e) => set("includeShared", e.target.checked)}
          />
          {t("includeShared")}
        </label>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field id={id("projects")} label={t("projects")} hint={t("projectsHint")}>
            <Input
              id={id("projects")}
              value={values.projects}
              disabled={!values.memoryEnabled}
              onChange={(e) => set("projects", e.target.value)}
            />
          </Field>
          <Field
            id={id("chars")}
            label={t("maxContextChars")}
            hint={globalHint(limits.data?.memory_context_max_chars, "chars")}
            error={errorText("maxContextChars")}
          >
            <Input
              id={id("chars")}
              inputMode="numeric"
              value={values.maxContextChars}
              disabled={!values.memoryEnabled}
              placeholder={limits.data ? String(limits.data.memory_context_max_chars) : ""}
              onChange={(e) => set("maxContextChars", e.target.value)}
              aria-invalid={Boolean(errorText("maxContextChars"))}
            />
          </Field>
        </div>
        <p className="text-xs text-muted-foreground">{t("memoryNote")}</p>
      </Section>

      {isOrchestrator && <p className="text-xs text-muted-foreground">{t("orchestratorNote")}</p>}
      {save.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(save.error).message}
        </p>
      )}
      <div className="flex items-center gap-3">
        <Button type="submit" disabled={save.isPending}>
          {agent ? t("save") : ta("create")}
        </Button>
        {!agent && (
          <Button type="button" variant="ghost" onClick={() => router.push("/office/agents")}>
            {ta("cancelForm")}
          </Button>
        )}
        {saved && agent && (
          <span role="status" className="text-sm text-grass">
            {t("saved")}
          </span>
        )}
      </div>
    </form>
  );
}

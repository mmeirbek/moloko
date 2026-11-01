"use client";

import type { AgentTemplateOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Code2, Languages, ListChecks, Plus, Search, X, type LucideIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentKeys, createAgentFromTemplate, listAgentTemplates } from "@/lib/api/agents";
import { cn } from "@/lib/utils";

const ICONS: Record<string, LucideIcon> = {
  researcher: Search,
  programmer: Code2,
  reviewer: ListChecks,
  translator: Languages,
};

/**
 * One-click persistent agents (office → "Add agent"). A new agent walks into the office
 * and rests in the lounge until it is given a task.
 */
export function AgentTemplates({
  onCreated,
  onClose,
  className,
}: {
  onCreated: (agentId: string) => void;
  onClose: () => void;
  className?: string;
}) {
  const t = useTranslations("agents.templates");
  const locale = useLocale();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: agentKeys.templates(locale),
    queryFn: ({ signal }) => listAgentTemplates(locale, signal),
  });
  const add = useMutation({
    mutationFn: (template: string) => createAgentFromTemplate({ template, locale }),
    onSuccess: (agent) => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      onCreated(agent.id);
    },
  });

  return (
    <section
      aria-label={t("title")}
      className={cn("flex flex-col gap-3 rounded-lg border bg-card p-4", className)}
      data-testid="agent-templates"
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-base">{t("title")}</h2>
          <p className="text-sm text-muted-foreground">{t("hint")}</p>
        </div>
        <Button size="icon" variant="ghost" onClick={onClose} aria-label={t("close")}>
          <X />
        </Button>
      </div>
      <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
        {templates.data?.map((tpl: AgentTemplateOut) => {
          const Icon = ICONS[tpl.key] ?? Plus;
          return (
            <li key={tpl.key} className="flex flex-col gap-2 rounded-md border p-3">
              <p className="flex items-center gap-2 font-medium">
                <Icon className="size-4 text-sky" aria-hidden="true" /> {tpl.name}
              </p>
              <p className="flex-1 text-xs text-muted-foreground">{tpl.description}</p>
              <Button
                size="sm"
                variant="outline"
                disabled={add.isPending}
                onClick={() => add.mutate(tpl.key)}
                data-testid={`template-${tpl.key}`}
              >
                <Plus /> {t("add")}
              </Button>
            </li>
          );
        })}
      </ul>
      {add.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(add.error).message}
        </p>
      )}
    </section>
  );
}

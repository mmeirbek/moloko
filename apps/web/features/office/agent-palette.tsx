"use client";

import type { AgentOut, AgentTemplateOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";

import { Bot, Code2, GripVertical, Languages, ListChecks, Plus, RotateCcw, Search, Trash2, X, type IconComponent } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentKeys, deleteAgentTemplate, listAgentTemplates, listArchivedAgents } from "@/lib/api/agents";
import { cn } from "@/lib/utils";

import { startDrag, useAddToOffice, type OfficeDrop } from "./add-to-office";

const ICONS: Record<string, IconComponent> = {
  researcher: Search,
  programmer: Code2,
  reviewer: ListChecks,
  translator: Languages,
};

type PaletteItem = {
  item: OfficeDrop;
  title: string;
  hint: string;
  icon: IconComponent;
  archived: boolean;
  /** The owner's own template: marked «yours», can be deleted. */
  own: AgentTemplateOut | null;
  testId: string;
};

/**
 * Agents the owner can put into the office: templates (built-in and the owner's own — a new
 * agent) and agents removed earlier. Drag one onto the office map, or press its button
 * (keyboard, touch). `panel` sits above the office page's map; `strip` is one scrolling row in
 * the island.
 */
export function AgentPalette({
  variant = "panel",
  onAdded,
  onClose,
  className,
}: {
  variant?: "panel" | "strip";
  onAdded?: (agentId: string) => void;
  onClose?: () => void;
  className?: string;
}) {
  const t = useTranslations("agents.templates");
  const locale = useLocale();
  const toMessage = useErrorMessage();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const templates = useQuery({
    queryKey: agentKeys.templates(locale),
    queryFn: ({ signal }) => listAgentTemplates(locale, signal),
  });
  const archived = useQuery({ queryKey: agentKeys.archived, queryFn: ({ signal }) => listArchivedAgents(signal) });
  const add = useAddToOffice(onAdded);
  const remove = useMutation({
    mutationFn: (id: string) => deleteAgentTemplate(id),
    onSettled: () => void queryClient.invalidateQueries({ queryKey: agentKeys.templates(locale) }),
  });
  const items: PaletteItem[] = [
    ...(templates.data ?? []).map((tpl: AgentTemplateOut) => {
      const own = tpl.source === "own";
      return {
        item: { kind: "template" as const, key: tpl.key },
        title: tpl.name,
        hint: tpl.description || (own ? t("ownHint") : ""),
        icon: own ? Bot : (ICONS[tpl.key] ?? Plus),
        archived: false,
        own: own ? tpl : null,
        testId: `template-${tpl.key}`,
      };
    }),
    ...(archived.data ?? []).map((agent: AgentOut) => ({
      item: { kind: "archived" as const, id: agent.id },
      title: agent.name,
      hint: t("removed"),
      icon: RotateCcw,
      archived: true,
      own: null,
      testId: `restore-${agent.id}`,
    })),
  ];
  const failed = add.error ?? remove.error;
  const error = failed ? <p role="alert" className="text-xs text-destructive">{toMessage(failed).message}</p> : null;

  async function removeTemplate(tpl: AgentTemplateOut) {
    if (!tpl.id) return;
    const ok = await confirm({
      title: t("deleteConfirm", { name: tpl.name }),
      description: t("deleteHint"),
      confirmLabel: t("delete"),
      destructive: true,
    });
    if (ok) remove.mutate(tpl.id);
  }

  const ownMark = (
    <span className="shrink-0 bg-sky/20 px-1 text-xs text-sky" data-testid="template-own-mark">
      {t("own")}
    </span>
  );

  if (variant === "strip") {
    return (
      <section aria-label={t("title")} className={cn("flex min-w-0 flex-col gap-2", className)} data-testid="agent-palette">
        <ul className="flex gap-3 overflow-x-auto px-(--px) pt-(--px) pb-2">
          {items.map(({ item, title, icon: Icon, archived: old, own, testId }) => (
            <li key={testId} className="shrink-0">
              <button
                type="button"
                draggable
                onDragStart={(e) => startDrag(e, item)}
                onClick={() => add.mutate(item)}
                disabled={add.isPending}
                title={t("dragHint")}
                data-testid={testId}
                className={cn(
                  "flex h-10 cursor-grab items-center gap-2 bg-card px-3 text-sm pixel-frame pixel-raised active:cursor-grabbing disabled:opacity-50",
                  old && "text-muted-foreground",
                )}
              >
                <Icon aria-hidden="true" />
                <span className="max-w-36 truncate">{title}</span>
                {own && ownMark}
              </button>
            </li>
          ))}
        </ul>
        {error}
      </section>
    );
  }

  return (
    <section aria-label={t("title")} className={cn("flex flex-col gap-4 bg-card p-4 pixel-frame", className)} data-testid="agent-templates">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h2 className="font-pixel text-lg">{t("title")}</h2>
          <p className="text-xs text-muted-foreground">{t("hint")}</p>
        </div>
        {onClose && (
          <Button size="icon" variant="ghost" onClick={onClose} aria-label={t("close")}>
            <X />
          </Button>
        )}
      </div>
      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {items.map(({ item, title, hint, icon: Icon, archived: old, own, testId }) => (
          <li
            key={testId}
            draggable
            onDragStart={(e) => startDrag(e, item)}
            title={t("dragHint")}
            className="flex cursor-grab flex-col gap-2 bg-background p-3 pixel-frame active:cursor-grabbing"
          >
            <p className="flex items-center gap-2">
              <GripVertical className="text-muted-foreground" aria-hidden="true" />
              <Icon className="text-sky" aria-hidden="true" />
              <span className="min-w-0 truncate">{title}</span>
              {own && ownMark}
            </p>
            <p className="flex-1 text-xs text-muted-foreground">{hint}</p>
            <div className="flex gap-2">
              <Button
                size="sm"
                variant="outline"
                className="flex-1"
                disabled={add.isPending}
                onClick={() => add.mutate(item)}
                data-testid={testId}
              >
                {old ? <RotateCcw /> : <Plus />} {old ? t("restore") : t("add")}
              </Button>
              {own && (
                <Button
                  size="icon"
                  variant="ghost"
                  className="size-9 text-muted-foreground hover:text-destructive"
                  aria-label={t("deleteLabel", { name: title })}
                  disabled={remove.isPending}
                  onClick={() => void removeTemplate(own)}
                  data-testid={`delete-template-${own.key}`}
                >
                  <Trash2 />
                </Button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {error}
    </section>
  );
}

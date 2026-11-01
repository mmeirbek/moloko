"use client";

import type { ToolOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { CategoryBadge } from "@/features/approvals/approval-card";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { listTools, toolingKeys, updateTool } from "@/lib/api/tooling";

import { useToolTitle } from "./use-tool-title";

export const GROUP_ORDER = ["files", "terminal", "web", "github", "memory", "mcp"] as const;

export function groupTools(tools: ToolOut[]): [string, ToolOut[]][] {
  const groups = new Map<string, ToolOut[]>();
  for (const tool of tools) groups.set(tool.group, [...(groups.get(tool.group) ?? []), tool]);
  const rank = (g: string) => {
    const i = (GROUP_ORDER as readonly string[]).indexOf(g);
    return i === -1 ? GROUP_ORDER.length : i;
  };
  return [...groups.entries()].sort(([a], [b]) => rank(a) - rank(b));
}

export function ToolRow({ tool }: { tool: ToolOut }) {
  const t = useTranslations("tools");
  const title = useToolTitle()(tool);
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const update = useMutation({
    mutationFn: (body: { enabled?: boolean; category?: "read" | "write" | "sensitive" }) => updateTool(tool.name, body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: toolingKeys.tools });
      void queryClient.invalidateQueries({ queryKey: toolingKeys.mcp });
    },
  });
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2" data-tool={tool.name}>
      <label className="flex min-w-0 flex-1 items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={tool.enabled}
          disabled={update.isPending}
          onChange={(e) => update.mutate({ enabled: e.target.checked })}
          aria-label={t("enable", { name: title })}
        />
        <span className="min-w-0">
          <span className="font-medium">{title}</span>{" "}
          <span className="font-mono text-xs text-muted-foreground">{tool.name}</span>
          <span className="block text-xs text-muted-foreground">{tool.description}</span>
        </span>
      </label>
      {tool.source === "mcp" ? (
        <select
          aria-label={t("category")}
          value={tool.category}
          onChange={(e) => update.mutate({ category: e.target.value as "read" })}
          className="h-8 rounded-md border border-input bg-background px-2 text-xs"
        >
          {(["read", "write", "sensitive"] as const).map((c) => (
            <option key={c} value={c}>
              {t(`categories.${c}`)}
            </option>
          ))}
        </select>
      ) : (
        <CategoryBadge category={tool.category} />
      )}
      {!tool.available && <span className="text-xs text-amber-700 dark:text-amber-300">{t("notConfigured")}</span>}
      {update.error && <p className="w-full text-xs text-destructive">{toMessage(update.error).message}</p>}
    </li>
  );
}

export function ToolsSection() {
  const t = useTranslations("tools");
  const tools = useQuery({ queryKey: toolingKeys.tools, queryFn: ({ signal }) => listTools(signal) });
  const groups = groupTools((tools.data ?? []).filter((tool) => tool.source === "builtin"));
  return (
    <Card id="tools">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.map(([group, items]) => (
          <section key={group} aria-label={t(`groups.${group as "files"}`)}>
            <h3 className="text-sm font-semibold">{t(`groups.${group as "files"}`)}</h3>
            <ul className="divide-y">
              {items.map((tool) => (
                <ToolRow key={tool.name} tool={tool} />
              ))}
            </ul>
          </section>
        ))}
      </CardContent>
    </Card>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";

import { CategoryBadge } from "@/features/approvals/approval-card";
import { groupTools } from "@/features/integrations/tools-section";
import { useToolTitle } from "@/features/integrations/use-tool-title";
import { listTools, listWorkspaces, toolingKeys } from "@/lib/api/tooling";

import { setOverride, toggleTool, type AgentFormValues, type ToolOverride } from "./agent-form-model";

/** Which tools the agent may use, stricter-only overrides, and its project workspace. */
export function AgentToolsField({
  values,
  onChange,
}: {
  values: AgentFormValues;
  onChange: (values: AgentFormValues) => void;
}) {
  const t = useTranslations("agents.form");
  const tt = useTranslations("tools");
  const titleOf = useToolTitle();
  const tools = useQuery({ queryKey: toolingKeys.tools, queryFn: ({ signal }) => listTools(signal) });
  const projects = useQuery({
    queryKey: [...toolingKeys.workspaces, "project"],
    queryFn: ({ signal }) => listWorkspaces("project", signal),
  });
  return (
    <div className="flex flex-col gap-4">
      <p className="text-xs text-muted-foreground">{t("toolsHint")}</p>
      {groupTools(tools.data ?? []).map(([group, items]) => (
        <fieldset key={group} className="flex flex-col gap-1">
          <legend className="text-sm font-semibold">{tt(`groups.${group as "files"}`)}</legend>
          {items.map((tool) => {
            const allowed = values.tools.includes(tool.name);
            return (
              <div
                key={tool.name}
                className="flex flex-wrap items-center gap-x-3 gap-y-1 py-1"
                data-agent-tool={tool.name}
              >
                <label className="flex min-w-0 flex-1 items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={allowed}
                    onChange={(e) => onChange(toggleTool(values, tool.name, e.target.checked))}
                  />
                  <span className="min-w-0 truncate">{titleOf(tool)}</span>
                </label>
                <CategoryBadge category={tool.category} />
                {(!tool.enabled || !tool.available) && (
                  <span className="text-xs text-amber-700 dark:text-amber-300">
                    {!tool.enabled ? tt("off") : tt("notConfigured")}
                  </span>
                )}
                {allowed && (
                  <select
                    aria-label={t("overrideFor", { name: titleOf(tool) })}
                    value={values.overrides[tool.name] ?? ""}
                    onChange={(e) => onChange(setOverride(values, tool.name, e.target.value as ToolOverride | ""))}
                    className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                  >
                    <option value="">{t("override.default")}</option>
                    <option value="approve">{t("override.approve")}</option>
                    <option value="deny">{t("override.deny")}</option>
                  </select>
                )}
              </div>
            );
          })}
        </fieldset>
      ))}
      <div className="flex flex-col gap-1.5">
        <label htmlFor="agent-workspace" className="text-sm font-medium">
          {t("workspace")}
        </label>
        <select
          id="agent-workspace"
          value={values.workspaceId}
          onChange={(e) => onChange({ ...values, workspaceId: e.target.value })}
          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">{t("workspacePerTask")}</option>
          {projects.data?.map((ws) => (
            <option key={ws.id} value={ws.id}>
              {ws.name}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { AlertTriangle, OctagonAlert } from "@/components/icons";
import { budgetLevel, usd } from "@/features/costs/format";
import { agentKeys, getAgentBudget } from "@/lib/api/agents";
import { cn } from "@/lib/utils";

/**
 * This month's spending against the agent's own budget: a pixel progress bar, the warning
 * threshold and the hard stop. A subagent shows the budget of the agent above it (it counts there).
 */
export function AgentBudget({ agentId, busy }: { agentId: string; busy: boolean }) {
  const t = useTranslations("agents.budget");
  const locale = useLocale();
  const budget = useQuery({
    queryKey: agentKeys.budget(agentId),
    queryFn: ({ signal }) => getAgentBudget(agentId, signal),
    refetchInterval: busy ? 10_000 : false, // spending grows while it works
  });
  const { refetch } = budget;
  const wasBusy = useRef(busy);
  useEffect(() => {
    if (wasBusy.current && !busy) void refetch(); // the last calls of a task that just ended
    wasBusy.current = busy;
  }, [busy, refetch]);
  const b = budget.data;
  if (!b) return null;

  const limit = b.monthly_budget_usd;
  const percent = Math.round(b.percent ?? 0);
  const level = budgetLevel(b.percent, b.warn_percent);
  const other = b.budget_agent_id !== agentId;
  const spent = usd(b.spent_usd, locale);

  return (
    <section
      aria-labelledby="agent-budget-title"
      className="flex max-w-xl flex-col gap-2 bg-card p-3 pixel-frame"
      data-testid="agent-budget"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="agent-budget-title" className="font-pixel text-lg">
          {t("title")}
        </h2>
        <span className="text-sm tabular-nums">
          {limit ? t("spentOf", { spent, limit: usd(limit, locale) }) : t("spent", { spent })}
        </span>
      </div>
      {limit && (
        <div
          role="meter"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={percent}
          aria-label={t("meter", { percent })}
          className="mx-(--px) h-3 overflow-hidden bg-muted pixel-frame pixel-sunken"
        >
          <div
            className={cn(
              "h-full",
              level === "over" ? "bg-destructive" : level === "warning" ? "bg-amber-500" : "bg-[var(--chart-bar)]",
            )}
            style={{ width: `${Math.min(100, b.percent ?? 0)}%` }}
          />
        </div>
      )}
      <p className="flex items-start gap-1 text-xs text-muted-foreground">
        {level === "over" && <OctagonAlert className="shrink-0 text-destructive" aria-hidden="true" />}
        {level === "warning" && <AlertTriangle className="shrink-0 text-amber-600" aria-hidden="true" />}
        <span>
          {other ? (
            <>
              {t("countsAgainst")}{" "}
              <Link href={`/office/agents/${b.budget_agent_id}`} className="underline underline-offset-2">
                {b.budget_agent_name}
              </Link>
              {limit ? ` · ${t("percent", { percent })}` : ""}
            </>
          ) : level === "over" ? (
            t("over")
          ) : level === "warning" ? (
            t("near", { percent, warn: b.warn_percent })
          ) : limit ? (
            t("ok", { percent, warn: b.warn_percent })
          ) : (
            t("noLimit")
          )}
        </span>
      </p>
    </section>
  );
}

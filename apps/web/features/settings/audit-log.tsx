"use client";

import type { AuditOut } from "@moloko/shared-types";
import { useInfiniteQuery } from "@tanstack/react-query";
import { useFormatter, useTranslations } from "next-intl";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { auditLog, toolingKeys } from "@/lib/api/tooling";
import { cn } from "@/lib/utils";
import { ErrorState, LoadingState } from "@/features/system/query-state";

export const AUDIT_AREAS = [
  "",
  "auth.",
  "agent.",
  "tool.",
  "approval.",
  "workspace.",
  "memory.",
  "integration.",
  "mcp.",
  "system.",
] as const;

const OUTCOME_TONE: Record<string, string> = {
  success: "text-grass",
  failure: "text-destructive",
  denied: "text-amber-700 dark:text-amber-300",
};

/** Compact, human-readable details (never secrets: the server never stores them here). */
export function summarizeDetails(details: Record<string, unknown>): string {
  return Object.entries(details)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
    .join(" · ")
    .slice(0, 400);
}

function Row({ entry }: { entry: AuditOut }) {
  const format = useFormatter();
  const t = useTranslations("audit");
  // Known values in words; anything new from the server is shown as it is.
  const outcome = t.has(`outcomes.${entry.outcome}` as "outcomes.success") ? t(`outcomes.${entry.outcome}` as "outcomes.success") : entry.outcome;
  const actor = t.has(`actors.${entry.actor_type}` as "actors.user") ? t(`actors.${entry.actor_type}` as "actors.user") : entry.actor_type;
  return (
    <li className="flex flex-col gap-0.5 py-2 text-sm" data-audit-action={entry.action}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-xs">{entry.action}</span>
        <span className={cn("text-xs", OUTCOME_TONE[entry.outcome])}>{outcome}</span>
        <span className="text-xs text-muted-foreground">
          {format.dateTime(new Date(entry.created_at), { dateStyle: "short", timeStyle: "medium" })} ·{" "}
          {actor}
        </span>
      </div>
      <p className="text-xs break-all text-muted-foreground">
        {entry.resource_type ? `${entry.resource_type}: ${entry.resource_id ?? ""} · ` : ""}
        {summarizeDetails(entry.details)}
      </p>
    </li>
  );
}

export function AuditLog() {
  const t = useTranslations("audit");
  const [action, setAction] = useState<string>("");
  const [outcome, setOutcome] = useState<string>("");
  const pages = useInfiniteQuery({
    queryKey: toolingKeys.audit(action, outcome),
    queryFn: ({ pageParam, signal }) => auditLog(action, outcome, pageParam, signal),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
  });
  const items = pages.data?.pages.flatMap((p) => p.items) ?? [];
  return (
    <div className="flex max-w-4xl flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <select
          aria-label={t("area")}
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          {AUDIT_AREAS.map((a) => (
            <option key={a} value={a}>
              {t(`areas.${a ? a.slice(0, -1) : "all"}` as "areas.all")}
            </option>
          ))}
        </select>
        <select
          aria-label={t("outcome")}
          value={outcome}
          onChange={(e) => setOutcome(e.target.value)}
          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">{t("outcomes.all")}</option>
          <option value="success">{t("outcomes.success")}</option>
          <option value="failure">{t("outcomes.failure")}</option>
          <option value="denied">{t("outcomes.denied")}</option>
        </select>
      </div>
      <ul className="divide-y rounded-lg border bg-card px-4" aria-label={t("title")}>
        {items.map((e) => (
          <Row key={e.id} entry={e} />
        ))}
      </ul>
      {pages.isPending && <LoadingState />}
      {pages.isError && !pages.data && <ErrorState error={pages.error} onRetry={() => pages.refetch()} />}
      {items.length === 0 && pages.isSuccess && <p className="text-sm text-muted-foreground">{t("empty")}</p>}
      {pages.hasNextPage && (
        <Button
          variant="outline"
          className="self-start"
          onClick={() => void pages.fetchNextPage()}
          disabled={pages.isFetchingNextPage}
        >
          {t("more")}
        </Button>
      )}
    </div>
  );
}

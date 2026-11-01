"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { listApprovals, toolingKeys } from "@/lib/api/tooling";
import { pendingApprovals, useRealtimeStore } from "@/lib/realtime/store";

import { ApprovalCard } from "./approval-card";
import { EmptyState } from "@/features/mascot/empty-state";
import { LoadingState } from "@/features/system/query-state";

export function ApprovalsView() {
  const t = useTranslations("approvals");
  const all = useRealtimeStore((s) => s.approvals); // stable reference; derive outside the selector
  // The live store is the truth once it has a snapshot and is connected; before that (or while
  // the connection is down) the REST list fills in, so waiting requests are never hidden.
  const live = useRealtimeStore((s) => s.lastSeq !== null && s.status === "online");
  const recent = useQuery({
    queryKey: toolingKeys.approvals("all"),
    queryFn: ({ signal }) => listApprovals("", signal),
  });
  const pending = useMemo(() => {
    if (live) return pendingApprovals(all);
    // Not live: the store is not updating, so the REST answer is the fresher one.
    const merged = { ...all, ...Object.fromEntries((recent.data ?? []).map((a) => [a.id, a])) };
    return pendingApprovals(merged);
  }, [live, all, recent.data]);
  const loading = !live && recent.isPending;
  const answered = (recent.data ?? []).filter((a) => a.status !== "pending").slice(0, 20);
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <section className="flex flex-col gap-3" aria-labelledby="pending-title">
        <h2 id="pending-title" className="text-lg font-semibold">
          {t("pending")}
        </h2>
        {loading && <LoadingState />}
        {!loading && pending.length === 0 && (
          <EmptyState title={t("none")} hint={t("noneHint")} mood="happy" className="rounded-lg border border-dashed" />
        )}
        {pending.map((a) => (
          <ApprovalCard key={a.id} approval={a} />
        ))}
      </section>
      {answered.length > 0 && (
        <section className="flex flex-col gap-3" aria-labelledby="answered-title">
          <h2 id="answered-title" className="text-lg font-semibold">
            {t("answered")}
          </h2>
          {answered.map((a) => (
            <ApprovalCard key={a.id} approval={a} compact />
          ))}
        </section>
      )}
    </div>
  );
}

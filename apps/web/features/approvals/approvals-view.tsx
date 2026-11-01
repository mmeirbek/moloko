"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useMemo } from "react";

import { listApprovals, toolingKeys } from "@/lib/api/tooling";
import { pendingApprovals, useRealtimeStore } from "@/lib/realtime/store";

import { ApprovalCard } from "./approval-card";
import { EmptyState } from "@/features/mascot/empty-state";

export function ApprovalsView() {
  const t = useTranslations("approvals");
  const all = useRealtimeStore((s) => s.approvals); // stable reference; derive outside the selector
  const pending = useMemo(() => pendingApprovals(all), [all]);
  const recent = useQuery({
    queryKey: toolingKeys.approvals("all"),
    queryFn: ({ signal }) => listApprovals("", signal),
  });
  const answered = (recent.data ?? []).filter((a) => a.status !== "pending").slice(0, 20);
  return (
    <div className="flex max-w-3xl flex-col gap-6">
      <section className="flex flex-col gap-3" aria-labelledby="pending-title">
        <h2 id="pending-title" className="text-lg font-semibold">
          {t("pending")}
        </h2>
        {pending.length === 0 && (
          <EmptyState title={t("none")} mood="happy" className="rounded-lg border border-dashed" />
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

"use client";

import type { ApprovalOut } from "@moloko/shared-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, ShieldAlert, X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentKeys, taskKeys } from "@/lib/api/agents";
import { resolveApproval } from "@/lib/api/tooling";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { minutesLeft } from "./time-left";

const CATEGORY_TONE: Record<string, string> = {
  read: "bg-muted text-muted-foreground",
  write: "bg-sky/15 text-sky",
  sensitive: "bg-destructive/15 text-destructive",
};

export function CategoryBadge({ category }: { category: string }) {
  const t = useTranslations("tools.categories");
  return (
    <span className={cn("rounded-full px-2 py-0.5 text-xs font-medium", CATEGORY_TONE[category])}>
      {t(category as "read")}
    </span>
  );
}

/** Spec 15.4: who asks, for which task, exactly what, what it touches and what happens. */
export function ApprovalCard({ approval, compact = false }: { approval: ApprovalOut; compact?: boolean }) {
  const t = useTranslations("approvals");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const task = useRealtimeStore((s) => s.tasks[approval.task_id]);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(id);
  }, []);
  const act = useMutation({
    mutationFn: (action: "approve" | "reject" | "cancel-task") => resolveApproval(approval.id, action),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["approvals"] });
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
      void queryClient.invalidateQueries({ queryKey: agentKeys.all });
    },
  });
  const pending = approval.status === "pending";
  const left = minutesLeft(approval.expires_at, now);

  return (
    <article
      className={cn("flex flex-col gap-3 rounded-lg border bg-card p-4", pending && "border-amber-400/60")}
      data-approval-id={approval.id}
      aria-label={t("label", { action: approval.summary })}
    >
      <header className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex min-w-0 items-start gap-2">
          <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-600" aria-hidden />
          <div className="min-w-0">
            <p className="font-medium break-words">{approval.summary}</p>
            <p className="text-xs text-muted-foreground">
              {t("requestedBy", { agent: approval.agent_name ?? "—" })}
              {task && (
                <>
                  {" · "}
                  <Link href={`/tasks/${task.id}`} className="underline-offset-2 hover:underline">
                    {task.title}
                  </Link>
                </>
              )}
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <CategoryBadge category={approval.category} />
          {!pending && (
            <span className="text-xs text-muted-foreground">{t(`status.${approval.status as "approved"}`)}</span>
          )}
        </div>
      </header>
      {!compact && (
        <dl className="grid gap-2 text-sm sm:grid-cols-[10rem_1fr]">
          <dt className="text-muted-foreground">{t("tool")}</dt>
          <dd className="font-mono text-xs break-all">{approval.tool_name}</dd>
          {approval.resources.length > 0 && (
            <>
              <dt className="text-muted-foreground">{t("resources")}</dt>
              <dd className="break-all">{approval.resources.join(", ")}</dd>
            </>
          )}
          {approval.consequences && (
            <>
              <dt className="text-muted-foreground">{t("consequences")}</dt>
              <dd>{approval.consequences}</dd>
            </>
          )}
          <dt className="text-muted-foreground">{t("why")}</dt>
          <dd>{approval.reason}</dd>
        </dl>
      )}
      <details className="text-sm">
        <summary className="cursor-pointer text-muted-foreground">{t("exactArgs")}</summary>
        <pre className="mt-2 max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap break-all">
          {JSON.stringify(approval.args, null, 2)}
        </pre>
      </details>
      {pending && (
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => act.mutate("approve")} disabled={act.isPending}>
            <Check /> {t("approve")}
          </Button>
          <Button size="sm" variant="outline" onClick={() => act.mutate("reject")} disabled={act.isPending}>
            <X /> {t("reject")}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive"
            disabled={act.isPending}
            onClick={() => {
              if (window.confirm(t("cancelConfirm"))) act.mutate("cancel-task");
            }}
          >
            <Ban /> {t("cancelTask")}
          </Button>
          <span className="ml-auto text-xs text-muted-foreground">{t("expiresIn", { minutes: left })}</span>
        </div>
      )}
      {pending && <p className="text-xs text-muted-foreground">{t("onlyThis")}</p>}
      {act.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(act.error).message}
        </p>
      )}
    </article>
  );
}

"use client";

import { ShieldAlert } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";

import { pendingApprovals, useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

/** Always-visible link to waiting approval requests (desktop sidebar and phone header). */
export function ApprovalsBadge({ className }: { className?: string }) {
  const t = useTranslations("approvals");
  const count = useRealtimeStore((s) => pendingApprovals(s.approvals).length);
  if (count === 0) return null;
  return (
    <Link
      href="/approvals"
      className={cn(
        "inline-flex items-center gap-1.5 rounded-md bg-amber-400/20 px-2 py-1 text-xs font-medium text-amber-800 dark:text-amber-200",
        className,
      )}
      aria-label={t("badge", { count })}
      data-testid="approvals-badge"
    >
      <ShieldAlert className="size-4" aria-hidden />
      <span>{count}</span>
    </Link>
  );
}

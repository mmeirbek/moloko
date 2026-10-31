"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

const TONE: Record<string, string> = {
  idle: "bg-muted text-muted-foreground",
  created: "bg-muted text-muted-foreground",
  queued: "bg-accent text-accent-foreground",
  planning: "bg-sky/15 text-sky",
  working: "bg-sky/15 text-sky",
  running: "bg-sky/15 text-sky",
  reviewing: "bg-sky/15 text-sky",
  waiting: "bg-amber-400/20 text-amber-700 dark:text-amber-300",
  waiting_approval: "bg-amber-400/20 text-amber-700 dark:text-amber-300",
  paused: "bg-amber-400/20 text-amber-700 dark:text-amber-300",
  completed: "bg-grass/15 text-grass",
  failed: "bg-destructive/15 text-destructive",
  cancelled: "bg-muted text-muted-foreground line-through",
};

export function StatusBadge({ status, className }: { status: string; className?: string }) {
  const t = useTranslations("status");
  const key = status as Parameters<typeof t>[0];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        TONE[status] ?? "bg-muted",
        className,
      )}
    >
      {["planning", "working", "running", "reviewing"].includes(status) && (
        <span className="size-1.5 animate-pulse rounded-full bg-current" aria-hidden="true" />
      )}
      {t.has(key) ? t(key) : status}
    </span>
  );
}

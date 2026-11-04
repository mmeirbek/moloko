"use client";

import { useEffect, useState } from "react";

import { cn } from "@/lib/utils";

/** Seconds since `since` (ticking), or null without a start time. */
function useElapsed(since: string | number | null | undefined): number | null {
  const start = since == null ? null : typeof since === "number" ? since : Date.parse(since);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (start === null) return;
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, [start]);
  return start === null || Number.isNaN(start) ? null : Math.max(0, Math.floor((now - start) / 1000));
}

/**
 * «Думает…» that visibly lives (owner: show that the chat or an agent thinks, searches, works —
 * that it has not frozen): three hopping dots, a light running over the words, and the seconds
 * once the wait gets long. `phases` change with the time waited (every `every` seconds).
 * Still when the owner prefers less motion.
 */
export function Thinking({
  label,
  phases,
  every = 4,
  since,
  className,
  testId = "thinking",
}: {
  label?: string;
  phases?: string[];
  every?: number;
  since?: string | number | null;
  className?: string;
  testId?: string;
}) {
  const elapsed = useElapsed(since);
  const words = phases?.length ? phases[Math.min(phases.length - 1, Math.floor((elapsed ?? 0) / every))] : label;
  return (
    <span role="status" className={cn("inline-flex items-center gap-2 text-sm", className)} data-testid={testId}>
      <span className="inline-flex items-end gap-[3px]" aria-hidden>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 rounded-full bg-current opacity-70 motion-safe:animate-[thinking-dot_1.1s_ease-in-out_infinite]"
            data-dot={i}
          />
        ))}
      </span>
      <span className="thinking-shimmer">{words}</span>
      {elapsed !== null && elapsed >= 5 && <span className="text-xs text-muted-foreground tabular-nums">{elapsed} с</span>}
    </span>
  );
}

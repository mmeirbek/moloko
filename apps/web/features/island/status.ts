"use client";

import { ACTIVE_STATUSES } from "@/features/agents/agent-controls";
import { useRealtimeStore } from "@/lib/realtime/store";

/** Agents doing something right now (planning, working, waiting, reviewing). */
export function useActiveAgentCount(): number {
  return useRealtimeStore((s) => Object.values(s.agents).filter((a) => ACTIVE_STATUSES.has(a.status)).length);
}

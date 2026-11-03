"use client";

import { pendingApprovals, useRealtimeStore } from "@/lib/realtime/store";

/** How many approval requests wait for the owner (live, from the realtime store). */
export function usePendingApprovalCount(): number {
  return useRealtimeStore((s) => pendingApprovals(s.approvals).length);
}

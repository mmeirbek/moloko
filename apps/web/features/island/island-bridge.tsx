"use client";

import type { ApprovalOut } from "@moloko/shared-types";
import { useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useEffectEvent, useRef } from "react";

import { usePendingApprovalCount } from "@/features/approvals/approvals-badge";
import { opParams } from "@/features/approvals/approval-text";
import { usePendingApprovals } from "@/features/approvals/approvals-view";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentKeys, taskKeys } from "@/lib/api/agents";
import { resolveApproval } from "@/lib/api/tooling";

import { ISLAND_EVENT, approvalActionOf, approvalChanges, nativeBridge, postToNative } from "./bridge";
import { useActiveAgentCount } from "./status";

/** One line saying what the agent wants to do — the same text as on the approval card. */
function useApprovalSummary() {
  const t = useTranslations("approvals");
  return useCallback(
    (approval: ApprovalOut) => {
      const params = opParams(approval);
      if (!params) return approval.summary;
      const op = approval.tool_name === "fs_write" && params.mode === "append" ? "fs_append" : approval.tool_name;
      return t(`ops.${op}.summary` as "ops.fs_write.summary", params);
    },
    [t],
  );
}

/**
 * Reports approvals to the Mac app so it can show native notifications: new pending ones, the
 * ones that stopped being pending, and (once per load) the whole pending list.
 */
function useApprovalNotifications() {
  const { pending, loading } = usePendingApprovals();
  const describe = useApprovalSummary();
  const reported = useRef<Set<string> | null>(null);
  useEffect(() => {
    if (loading || !nativeBridge()) return;
    if (reported.current === null) {
      reported.current = new Set();
      postToNative({ type: "approvalsPending", ids: pending.map((a) => a.id) });
    }
    const seen = reported.current;
    const { added, gone } = approvalChanges(seen, pending.map((a) => a.id));
    for (const approval of pending) {
      if (!added.includes(approval.id)) continue;
      seen.add(approval.id);
      postToNative({ type: "approval", id: approval.id, summary: describe(approval), agent: approval.agent_name ?? "" });
    }
    for (const id of gone) {
      seen.delete(id);
      postToNative({ type: "approvalGone", id });
    }
  }, [pending, loading, describe]);
}

/**
 * Talks to the Mac notch app: the pill's status, approval notifications, and the answers the
 * owner gives on those notifications (performed here — the page holds the session and CSRF).
 * The contract is described in ./bridge.ts.
 */
export function IslandBridge() {
  const queryClient = useQueryClient();
  const t = useTranslations("approvals");
  const toMessage = useErrorMessage();
  const pendingApprovals = usePendingApprovalCount();
  const activeAgents = useActiveAgentCount();
  const answering = useRef(new Set<string>());

  useEffect(() => {
    postToNative({ type: "status", pendingApprovals, activeAgents, signedIn: true });
  }, [pendingApprovals, activeAgents]);

  useApprovalNotifications();

  const onIslandEvent = useEffectEvent((detail: unknown) => {
    if ((detail as { open?: unknown } | null)?.open === true) void queryClient.invalidateQueries();
    const request = approvalActionOf(detail);
    if (!request || answering.current.has(request.approvalId)) return;
    const { action, approvalId } = request;
    answering.current.add(approvalId);
    resolveApproval(approvalId, action)
      .then(() => {
        const message = t(action === "approve" ? "status.approved" : "status.rejected");
        postToNative({ type: "approvalResolved", id: approvalId, ok: true, message });
        void queryClient.invalidateQueries({ queryKey: ["approvals"] });
        void queryClient.invalidateQueries({ queryKey: taskKeys.all });
        void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      })
      .catch((error: unknown) => {
        postToNative({ type: "approvalResolved", id: approvalId, ok: false, message: toMessage(error).message });
      })
      .finally(() => answering.current.delete(approvalId));
  });

  useEffect(() => {
    const listener = (e: Event) => onIslandEvent((e as CustomEvent<unknown>).detail);
    window.addEventListener(ISLAND_EVENT, listener);
    return () => window.removeEventListener(ISLAND_EVENT, listener);
  }, []);

  return null;
}

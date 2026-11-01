import type { AgentOut, ApprovalOut, EventEnvelope, RunOut, SnapshotFrame, TaskOut } from "@moloko/shared-types";
import { create } from "zustand";

export type ConnectionStatus = "connecting" | "online" | "offline";

export interface RealtimeState {
  status: ConnectionStatus;
  /** Highest event seq applied. null until the first snapshot. */
  lastSeq: number | null;
  agents: Record<string, AgentOut>;
  tasks: Record<string, TaskOut>;
  runs: Record<string, RunOut>;
  /** Approval requests (pending ones need the owner); resolved ones stay for display. */
  approvals: Record<string, ApprovalOut>;
  /** Latest intermediate message per run (agent.message), for live progress. */
  lastMessage: Record<string, { step: number; text: string }>;
  setStatus: (status: ConnectionStatus) => void;
  applySnapshot: (snapshot: SnapshotFrame) => void;
  /** Returns false if the event was a duplicate / already applied. */
  applyEvent: (event: EventEnvelope) => boolean;
  reset: () => void;
}

const empty = { lastSeq: null, agents: {}, tasks: {}, runs: {}, approvals: {}, lastMessage: {} };

function byId<T extends { id: string }>(items: T[]): Record<string, T> {
  return Object.fromEntries(items.map((item) => [item.id, item]));
}

/**
 * Client mirror of server state. It is only ever written from server data
 * (snapshot + events); UI components read it, never write agent state themselves.
 */
export const useRealtimeStore = create<RealtimeState>()((set, get) => ({
  status: "connecting",
  ...empty,
  setStatus: (status) => set({ status }),
  applySnapshot: (snapshot) =>
    set({
      lastSeq: snapshot.seq,
      agents: byId(snapshot.agents),
      tasks: byId(snapshot.tasks),
      runs: byId(snapshot.runs),
      approvals: byId(snapshot.approvals ?? []),
      lastMessage: {},
    }),
  applyEvent: (event) => {
    const { lastSeq } = get();
    if (event.seq !== null && lastSeq !== null && event.seq <= lastSeq) return false;
    const payload = event.payload as Record<string, unknown>;
    set((state) => {
      const next: Partial<RealtimeState> = {};
      if (event.seq !== null) next.lastSeq = event.seq;
      const agent = payload.agent as AgentOut | undefined;
      if (agent) next.agents = { ...state.agents, [agent.id]: agent };
      const task = payload.task as TaskOut | undefined;
      if (task) next.tasks = { ...state.tasks, [task.id]: task };
      const approval = payload.approval as ApprovalOut | undefined;
      if (approval && (event.type === "approval.required" || event.type === "approval.resolved")) {
        next.approvals = { ...state.approvals, [approval.id]: approval };
      }
      if (event.type === "agent.message" && event.run_id && payload.kind !== "tool_call") {
        next.lastMessage = {
          ...state.lastMessage,
          [event.run_id]: { step: Number(payload.step ?? 0), text: String(payload.text ?? "") },
        };
      }
      return next;
    });
    return true;
  },
  reset: () => set({ status: "connecting", ...empty }),
}));

/** Pending approval requests, oldest first (stable order for the owner). */
export function pendingApprovals(approvals: Record<string, ApprovalOut>): ApprovalOut[] {
  return Object.values(approvals)
    .filter((a) => a.status === "pending")
    .sort((a, b) => (a.created_at ?? "").localeCompare(b.created_at ?? ""));
}

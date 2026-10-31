/**
 * Realtime contracts (mirror of packages/agent-contracts/schemas/*.json).
 * Hand-written: WebSocket frames are not part of the OpenAPI schema.
 */
import type { AgentOut, RunOut, TaskOut } from "./index";

export type EventType =
  | "agent.created"
  | "agent.updated"
  | "agent.status_changed"
  | "agent.message"
  | "agent.task_started"
  | "agent.task_completed"
  | "agent.task_failed"
  | "task.created"
  | "task.updated"
  | "task.completed"
  | "task.failed"
  | "task.cancelled"
  | "approval.required"
  | "approval.resolved"
  | "chat.message_delta"
  | "chat.message_completed";

export interface EventEnvelope<P = Record<string, unknown>> {
  id: string;
  /** null for stream-only events (chat.message_delta) */
  seq: number | null;
  type: EventType;
  version: number;
  timestamp: string;
  agent_id: string | null;
  task_id: string | null;
  run_id: string | null;
  payload: P;
}

export interface SnapshotFrame {
  type: "snapshot";
  seq: number;
  agents: AgentOut[];
  tasks: TaskOut[];
  runs: RunOut[];
  approvals: unknown[];
}

export interface EventFrame {
  type: "event";
  event: EventEnvelope;
}

export interface ResumedFrame {
  type: "resumed";
  seq: number;
}

export type ServerFrame = SnapshotFrame | EventFrame | ResumedFrame | { type: "pong" };
export type ClientFrame = { type: "hello"; last_seq: number | null; csrf: string } | { type: "ping" };

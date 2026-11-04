import type { ApprovalOut, ConversationOut, TaskOut } from "@moloko/shared-types";

import { ownerQuestion } from "@/lib/notifications/text";

/** Why a task waits for the owner: an approval, a question in its answer, or it broke. */
export type WaitReason = "approval" | "question" | "failed";

export type WorkItem =
  | { kind: "task"; task: TaskOut; at: string; reason?: WaitReason }
  | { kind: "chat"; chat: ConversationOut; at: string };

export interface WorkGroups {
  waiting: WorkItem[];
  active: WorkItem[];
  recent: WorkItem[];
}

const ACTIVE = new Set(["queued", "running", "waiting", "waiting_approval"]);
/** A question or a failure stops waiting for the owner after this long (they let it be). */
export const WAIT_WINDOW_MS = 3 * 24 * 3600_000;
export const RECENT_MAX = 30;

const taskTime = (t: TaskOut) => t.completed_at ?? t.updated_at ?? t.created_at;

/**
 * The owner's work in one list, like Claude's sidebar: what waits for them, what is under
 * way, then recent chats and finished tasks together (newest first). Only top-level tasks;
 * an attempt that was continued or started over is replaced by the newer one; a task handed
 * off from a chat is that chat in «recent». Pure: tested.
 */
export function groupWork(
  tasks: TaskOut[],
  chats: ConversationOut[],
  approvals: ApprovalOut[],
  now: number = Date.now(),
): WorkGroups {
  const top = tasks.filter((t) => !t.parent_task_id);
  const replaced = new Set(top.map((t) => t.retry_of_id).filter(Boolean));
  // Approvals of a part count for its whole task.
  const parentOf = new Map(tasks.map((t) => [t.id, t.parent_task_id]));
  const asking = new Set<string>();
  for (const a of approvals) {
    if (a.status !== "pending" || !a.task_id) continue;
    let id: string | null | undefined = a.task_id;
    for (let hops = 0; id && hops < 10; hops += 1) {
      asking.add(id);
      id = parentOf.get(id);
    }
  }

  const groups: WorkGroups = { waiting: [], active: [], recent: [] };
  for (const task of top) {
    const inLine = task.status === "created" && task.status_reason === "waiting_for_agent";
    if (replaced.has(task.id) || (task.status === "created" && !inLine)) continue;
    const at = taskTime(task);
    const fresh = now - Date.parse(at) < WAIT_WINDOW_MS;
    const reason: WaitReason | undefined =
      task.status === "waiting_approval" || (ACTIVE.has(task.status) && asking.has(task.id))
        ? "approval"
        : task.status === "failed" && fresh
          ? "failed"
          : task.status === "completed" && fresh && ownerQuestion(task.result ?? "")
            ? "question"
            : undefined;
    if (reason) groups.waiting.push({ kind: "task", task, at, reason });
    else if (ACTIVE.has(task.status) || inLine) groups.active.push({ kind: "task", task, at });
    else if (typeof task.extra?.conversation_id !== "string") groups.recent.push({ kind: "task", task, at });
  }
  for (const chat of chats) groups.recent.push({ kind: "chat", chat, at: chat.last_message_at });
  const newest = (a: WorkItem, b: WorkItem) => Date.parse(b.at) - Date.parse(a.at);
  groups.waiting.sort(newest);
  groups.active.sort(newest);
  groups.recent = groups.recent.sort(newest).slice(0, RECENT_MAX);
  return groups;
}

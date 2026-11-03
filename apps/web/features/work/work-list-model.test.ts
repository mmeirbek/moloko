import type { ApprovalOut, ConversationOut, TaskOut } from "@moloko/shared-types";
import { describe, expect, it } from "vitest";

import { groupWork, RECENT_MAX } from "./work-list-model";

const now = Date.parse("2026-11-03T12:00:00Z");
const hoursAgo = (h: number) => new Date(now - h * 3600_000).toISOString();

function task(id: string, status: string, extra: Partial<TaskOut> = {}): TaskOut {
  return {
    id,
    title: id,
    status,
    parent_task_id: null,
    retry_of_id: null,
    result: null,
    extra: {},
    created_at: hoursAgo(10),
    updated_at: hoursAgo(1),
    completed_at: null,
    ...extra,
  } as TaskOut;
}
const chat = (id: string, h: number) => ({ id, title: id, last_message_at: hoursAgo(h) }) as ConversationOut;
const ids = (items: { kind: string; task?: TaskOut; chat?: ConversationOut }[]) =>
  items.map((i) => (i.kind === "task" ? i.task!.id : `chat:${i.chat!.id}`));

describe("the owner's work list", () => {
  it("puts what needs the owner first, then what runs, then chats and finished tasks", () => {
    const groups = groupWork(
      [
        task("asks", "waiting_approval"),
        task("question", "completed", { result: "Нашёл два сайта.\n\nКакой нужен?", completed_at: hoursAgo(2) }),
        task("broke", "failed", { completed_at: hoursAgo(3) }),
        task("old-broke", "failed", { completed_at: hoursAgo(24 * 5), updated_at: hoursAgo(24 * 5) }),
        task("runs", "running"),
        task("in-line", "created", { status_reason: "waiting_for_agent", updated_at: hoursAgo(2) }),
        task("done", "completed", { result: "Готово.", completed_at: hoursAgo(4) }),
        task("draft", "created"),
      ],
      [chat("talk", 0.5)],
      [],
      now,
    );
    expect(groups.waiting.map((i) => (i.kind === "task" ? [i.task.id, i.reason] : []))).toEqual([
      ["asks", "approval"],
      ["question", "question"],
      ["broke", "failed"],
    ]);
    expect(ids(groups.active)).toEqual(["runs", "in-line"]); // waiting for its busy agent
    expect(ids(groups.recent)).toEqual(["chat:talk", "done", "old-broke"]);
  });

  it("shows only the newest attempt, the chat of a hand-off, and a part's approval on its task", () => {
    const approval = { id: "a", status: "pending", task_id: "part" } as ApprovalOut;
    const groups = groupWork(
      [
        task("first", "failed", { completed_at: hoursAgo(2) }),
        task("second", "completed", { retry_of_id: "first", completed_at: hoursAgo(1) }),
        task("from-chat", "completed", { extra: { conversation_id: "c1" } }),
        task("boss", "running"),
        task("part", "waiting_approval", { parent_task_id: "boss" }),
      ],
      [chat("c1", 1)],
      [approval],
      now,
    );
    expect(ids(groups.waiting)).toEqual(["boss"]);
    expect(ids(groups.active)).toEqual([]);
    expect(ids(groups.recent)).toEqual(["second", "chat:c1"]);
  });

  it("keeps the recent list short", () => {
    const chats = Array.from({ length: RECENT_MAX + 5 }, (_, i) => chat(`c${i}`, i));
    expect(groupWork([], chats, [], now).recent).toHaveLength(RECENT_MAX);
  });
});

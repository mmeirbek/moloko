import type { EventEnvelope, SnapshotFrame } from "@moloko/shared-types";
import { beforeEach, describe, expect, it } from "vitest";

import { backoffDelay } from "./socket";
import { useRealtimeStore } from "./store";

const agent = (id: string, status: string) => ({ id, name: id, status }) as never;

function event(seq: number | null, type: string, payload: Record<string, unknown>): EventEnvelope {
  return {
    id: `e${seq}`,
    seq,
    type: type as EventEnvelope["type"],
    version: 1,
    timestamp: "",
    agent_id: null,
    task_id: null,
    run_id: "r1",
    payload,
  };
}

describe("realtime store", () => {
  beforeEach(() => useRealtimeStore.getState().reset());

  it("applies a snapshot then newer events, ignoring duplicates and old seqs", () => {
    const s = useRealtimeStore.getState();
    s.applySnapshot({ type: "snapshot", seq: 10, agents: [agent("a", "idle")], tasks: [], runs: [], approvals: [] } as SnapshotFrame);
    expect(useRealtimeStore.getState().agents.a!.status).toBe("idle");

    expect(s.applyEvent(event(11, "agent.status_changed", { agent: agent("a", "working") }))).toBe(true);
    expect(useRealtimeStore.getState().agents.a!.status).toBe("working");
    // duplicate / older events are not applied twice
    expect(s.applyEvent(event(11, "agent.status_changed", { agent: agent("a", "idle") }))).toBe(false);
    expect(s.applyEvent(event(5, "agent.status_changed", { agent: agent("a", "idle") }))).toBe(false);
    expect(useRealtimeStore.getState().agents.a!.status).toBe("working");
    expect(useRealtimeStore.getState().lastSeq).toBe(11);
  });

  it("stream-only events (no seq) never move lastSeq", () => {
    const s = useRealtimeStore.getState();
    s.applySnapshot({ type: "snapshot", seq: 3, agents: [], tasks: [], runs: [], approvals: [] } as SnapshotFrame);
    expect(s.applyEvent(event(null, "chat.message_delta", { text: "x" }))).toBe(true);
    expect(useRealtimeStore.getState().lastSeq).toBe(3);
  });

  it("keeps the latest agent message per run", () => {
    const s = useRealtimeStore.getState();
    s.applyEvent(event(1, "agent.message", { step: 1, text: "first" }));
    s.applyEvent(event(2, "agent.message", { step: 2, text: "second" }));
    expect(useRealtimeStore.getState().lastMessage.r1).toEqual({ step: 2, text: "second" });
  });
});

describe("backoff", () => {
  it("grows exponentially with jitter and is capped", () => {
    expect(backoffDelay(0, () => 0)).toBe(500);
    expect(backoffDelay(3, () => 1)).toBe(8000);
    expect(backoffDelay(20, () => 1)).toBe(30_000);
  });
});

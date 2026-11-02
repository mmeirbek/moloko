import { afterEach, describe, expect, it } from "vitest";

import { approvalActionOf, approvalChanges, focusRequestOf, postToNative } from "./bridge";

describe("island bridge", () => {
  afterEach(() => {
    delete (globalThis as { window?: unknown }).window;
  });

  it("reports each pending approval once and the ones that stopped being pending", () => {
    expect(approvalChanges(new Set(), ["a", "b"])).toEqual({ added: ["a", "b"], gone: [] });
    expect(approvalChanges(new Set(["a", "b"]), ["b", "c"])).toEqual({ added: ["c"], gone: ["a"] });
    expect(approvalChanges(new Set(["a"]), ["a"])).toEqual({ added: [], gone: [] });
    expect(approvalChanges(new Set(["a"]), [])).toEqual({ added: [], gone: ["a"] });
  });

  it("accepts only well-formed approval actions from the app", () => {
    expect(approvalActionOf({ action: "approve", approvalId: "id-1" })).toEqual({ action: "approve", approvalId: "id-1" });
    expect(approvalActionOf({ action: "reject", approvalId: "id-1" })).toEqual({ action: "reject", approvalId: "id-1" });
    // cancel-task stays a deliberate choice on the card, never one tap in a notification
    expect(approvalActionOf({ action: "cancel-task", approvalId: "id-1" })).toBeNull();
    expect(approvalActionOf({ action: "approve", approvalId: "" })).toBeNull();
    expect(approvalActionOf({ action: "approve", approvalId: 7 })).toBeNull();
    expect(approvalActionOf({ open: true })).toBeNull();
    expect(approvalActionOf(null)).toBeNull();
    expect(approvalActionOf("approve")).toBeNull();
  });

  it("reads the focus request of a hotkey open", () => {
    expect(focusRequestOf({ open: true, focus: "task" })).toBe("task");
    expect(focusRequestOf({ open: true })).toBeNull();
    expect(focusRequestOf(undefined)).toBeNull();
  });

  it("posts to the Mac app only inside its web view", () => {
    expect(() => postToNative({ type: "approvalGone", id: "a" })).not.toThrow(); // no window (server, tests)
    const sent: unknown[] = [];
    (globalThis as { window?: unknown }).window = {
      webkit: { messageHandlers: { molokoIsland: { postMessage: (m: unknown) => sent.push(m) } } },
    };
    postToNative({ type: "approval", id: "a", summary: "Удалить x.txt", agent: "Кодер" });
    expect(sent).toEqual([{ type: "approval", id: "a", summary: "Удалить x.txt", agent: "Кодер" }]);
  });
});

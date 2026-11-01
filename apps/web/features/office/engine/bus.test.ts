import { describe, expect, it, vi } from "vitest";

import { OfficeBus } from "./bus";

describe("office bus", () => {
  it("delivers typed events and unsubscribes", () => {
    const bus = new OfficeBus();
    const seen = vi.fn();
    const off = bus.on("selected", seen);
    bus.emit("selected", "a1");
    off();
    bus.emit("selected", "a2");
    expect(seen).toHaveBeenCalledTimes(1);
    expect(seen).toHaveBeenCalledWith("a1");
  });
});

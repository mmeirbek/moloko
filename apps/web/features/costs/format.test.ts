import { describe, expect, it } from "vitest";

import { budgetLevel, fillDays, usd } from "./format";

describe("costs formatting", () => {
  it("shows small amounts with more digits", () => {
    expect(usd("0.0042", "en")).toBe("$0.0042");
    expect(usd(12.5, "en")).toBe("$12.50");
  });
  it("rates the month against the limit", () => {
    expect(budgetLevel(null, 80)).toBe("none");
    expect(budgetLevel(50, 80)).toBe("ok");
    expect(budgetLevel(85, 80)).toBe("warning");
    expect(budgetLevel(120, 80)).toBe("over");
  });
  it("fills every day of the month", () => {
    const days = fillDays("2026-02", [{ day: "2026-02-03", cost_usd: "1.5" }]);
    expect(days).toHaveLength(28);
    expect(days[2]).toEqual({ day: "2026-02-03", cost: 1.5 });
    expect(days[0]!.cost).toBe(0);
  });
});

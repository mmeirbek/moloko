/** Money and token formatting for the Costs page. Pure: tested. */
export function usd(value: string | number, locale: string): string {
  const n = typeof value === "string" ? Number(value) : value;
  const digits = Math.abs(n) > 0 && Math.abs(n) < 0.01 ? 4 : 2;
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n);
}

export function tokens(n: number, locale: string): string {
  return new Intl.NumberFormat(locale, { notation: n >= 10_000 ? "compact" : "standard" }).format(n);
}

export type BudgetLevel = "none" | "ok" | "warning" | "over";

/** Where the month stands against the limit. */
export function budgetLevel(percent: number | null | undefined, warnPercent: number): BudgetLevel {
  if (percent === null || percent === undefined) return "none";
  if (percent >= 100) return "over";
  if (percent >= warnPercent) return "warning";
  return "ok";
}

/** Every day of the month (YYYY-MM-DD) with its cost; missing days are 0. */
export function fillDays(month: string, days: { day: string; cost_usd: string }[]): { day: string; cost: number }[] {
  const [y, m] = month.split("-").map(Number) as [number, number];
  const count = new Date(Date.UTC(y, m, 0)).getUTCDate();
  const byDay = new Map(days.map((d) => [d.day, Number(d.cost_usd)]));
  return Array.from({ length: count }, (_, i) => {
    const day = `${month}-${String(i + 1).padStart(2, "0")}`;
    return { day, cost: byDay.get(day) ?? 0 };
  });
}

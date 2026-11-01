import type { BudgetIn, BudgetOut, CostSummary } from "@moloko/shared-types";

import { api } from "./client";

export const costKeys = {
  all: ["costs"] as const,
  month: (month: string | null) => ["costs", month ?? "current"] as const,
};

export const getCosts = (month: string | null, signal?: AbortSignal) =>
  api.request<CostSummary>(month ? `/costs?month=${month}` : "/costs", { signal });
export const updateBudget = (body: BudgetIn) =>
  api.request<BudgetOut>("/costs/budget", { method: "PUT", body });

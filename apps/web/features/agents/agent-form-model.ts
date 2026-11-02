import type { AgentCreate, AgentOut, SystemLimits } from "@moloko/shared-types";

export const AUTONOMY = ["supervised", "balanced", "restricted"] as const;
export type Autonomy = (typeof AUTONOMY)[number];

/** What the form edits. Numbers stay strings while typing; "" = use the global limit. */
export type AgentFormValues = {
  name: string;
  description: string;
  specialization: string;
  modelId: string;
  systemPrompt: string;
  autonomy: Autonomy;
  maxSteps: string;
  timeoutMinutes: string;
  /** Monthly budget in USD; "" = no limit of its own. */
  monthlyBudget: string;
  memoryEnabled: boolean;
  includeShared: boolean;
  projects: string;
  maxContextChars: string;
  tools: string[];
  overrides: Record<string, ToolOverride>;
  workspaceId: string;
  contactMode: ContactMode;
  contactIds: string[];
};

export type ToolOverride = "approve" | "deny";

/** Which colleagues an agent may talk to directly (agents_list / agent_ask / agent_tell). */
export const CONTACT_MODES = ["all", "list", "none"] as const;
export type ContactMode = (typeof CONTACT_MODES)[number];
export type AgentContacts = { mode: ContactMode; agent_ids: string[] };
const DEFAULT_CONTACTS: AgentContacts = { mode: "all", agent_ids: [] };

/** The agent's `contacts` from the API (missing or unknown → everyone, the server default). */
export function contactsOf(agent?: AgentOut): AgentContacts {
  const c = (agent as { contacts?: Partial<AgentContacts> } | undefined)?.contacts;
  const mode = (CONTACT_MODES as readonly string[]).includes(c?.mode ?? "") ? (c!.mode as ContactMode) : "all";
  return { mode, agent_ids: mode === "list" ? [...(c?.agent_ids ?? [])] : [] };
}

export type FieldError = "required" | "number" | "money" | "tooHigh" | "tooLow";

/** Highest monthly budget the API accepts. */
export const MAX_BUDGET_USD = 1_000_000;
export type FormErrors = Partial<Record<keyof AgentFormValues, { error: FieldError; limit?: number }>>;

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export function fromAgent(agent?: AgentOut): AgentFormValues {
  const limits = (agent?.limits ?? {}) as { max_steps?: number; run_timeout_seconds?: number };
  const memory = (agent?.memory_settings ?? {}) as {
    enabled?: boolean;
    include_shared?: boolean;
    projects?: string[];
    max_context_chars?: number;
  };
  return {
    name: agent?.name ?? "",
    description: agent?.description ?? "",
    specialization: agent?.specialization ?? "",
    modelId: agent?.model_config_id ?? "",
    systemPrompt: agent?.system_prompt ?? "",
    autonomy: (AUTONOMY as readonly string[]).includes(agent?.autonomy_level ?? "")
      ? (agent!.autonomy_level as Autonomy)
      : "supervised",
    maxSteps: str(limits.max_steps),
    timeoutMinutes: limits.run_timeout_seconds ? str(Math.round(limits.run_timeout_seconds / 60)) : "",
    monthlyBudget: str(agent?.monthly_budget_usd),
    memoryEnabled: memory.enabled ?? true,
    includeShared: memory.include_shared ?? true,
    projects: (memory.projects ?? []).join(", "),
    maxContextChars: str(memory.max_context_chars),
    tools: [...(agent?.allowed_tools ?? [])],
    overrides: { ...(((agent?.permissions ?? {}) as { tools?: Record<string, ToolOverride> }).tools ?? {}) },
    workspaceId: agent?.workspace_id ?? "",
    contactMode: contactsOf(agent).mode,
    contactIds: contactsOf(agent).agent_ids,
  };
}

export function toggleContact(values: AgentFormValues, id: string, on: boolean): AgentFormValues {
  const contactIds = on ? [...new Set([...values.contactIds, id])] : values.contactIds.filter((x) => x !== id);
  return { ...values, contactIds };
}

/** Allowing a tool or removing it; overrides only matter for allowed tools. */
export function toggleTool(values: AgentFormValues, name: string, allowed: boolean): AgentFormValues {
  const tools = allowed ? [...new Set([...values.tools, name])] : values.tools.filter((t) => t !== name);
  const overrides = { ...values.overrides };
  if (!allowed) delete overrides[name];
  return { ...values, tools, overrides };
}

export function setOverride(values: AgentFormValues, name: string, value: ToolOverride | ""): AgentFormValues {
  const overrides = { ...values.overrides };
  if (value) overrides[name] = value;
  else delete overrides[name];
  return { ...values, overrides };
}

export function parseProjects(text: string): string[] {
  return [
    ...new Set(
      text
        .split(",")
        .map((p) => p.trim())
        .filter(Boolean),
    ),
  ];
}

function whole(text: string): number | null {
  const t = text.trim();
  if (!t) return null;
  return /^\d+$/.test(t) ? Number(t) : NaN;
}

/** Dollars with at most two decimals ("12", "12.5", "12,50" → "12.50"); null = empty; false = not a sum. */
export function money(text: string): string | null | false {
  const t = text.trim().replace(",", ".");
  if (!t) return null;
  return /^\d+(\.\d{1,2})?$/.test(t) ? Number(t).toFixed(2) : false;
}

/** Same rules as the API: per-agent limits may only be stricter than the global ones. */
export function validate(values: AgentFormValues, limits?: SystemLimits): FormErrors {
  const errors: FormErrors = {};
  if (!values.name.trim()) errors.name = { error: "required" };
  const check = (key: keyof AgentFormValues, value: number | null, min: number, max?: number) => {
    if (value === null) return;
    if (Number.isNaN(value)) errors[key] = { error: "number" };
    else if (value < min) errors[key] = { error: "tooLow", limit: min };
    else if (max !== undefined && value > max) errors[key] = { error: "tooHigh", limit: max };
  };
  check("maxSteps", whole(values.maxSteps), 1, limits?.max_steps_per_run);
  check(
    "timeoutMinutes",
    whole(values.timeoutMinutes),
    1,
    limits ? Math.floor(limits.run_timeout_seconds / 60) : undefined,
  );
  check("maxContextChars", whole(values.maxContextChars), 200, limits?.memory_context_max_chars);
  const budget = money(values.monthlyBudget);
  if (budget === false || (budget !== null && (Number(budget) <= 0 || Number(budget) > MAX_BUDGET_USD)))
    errors.monthlyBudget = { error: "money", limit: MAX_BUDGET_USD };
  return errors;
}

export function toPayload(values: AgentFormValues): Omit<AgentCreate, "agent_type"> & { contacts: AgentContacts } {
  const steps = whole(values.maxSteps);
  const minutes = whole(values.timeoutMinutes);
  const chars = whole(values.maxContextChars);
  return {
    name: values.name.trim(),
    description: values.description.trim(),
    specialization: values.specialization.trim() || null,
    model_config_id: values.modelId || null,
    system_prompt: values.systemPrompt,
    autonomy_level: values.autonomy,
    limits: {
      max_steps: steps ?? null,
      run_timeout_seconds: minutes === null ? null : minutes * 60,
    },
    memory_settings: {
      enabled: values.memoryEnabled,
      include_shared: values.includeShared,
      projects: parseProjects(values.projects),
      max_context_chars: chars ?? null,
    },
    allowed_tools: values.tools,
    tool_overrides: Object.fromEntries(
      Object.entries(values.overrides).filter(([name]) => values.tools.includes(name)),
    ),
    workspace_id: values.workspaceId || null,
    monthly_budget_usd: money(values.monthlyBudget) || null,
    contacts:
      values.contactMode === "list" ? { mode: "list", agent_ids: values.contactIds } : { ...DEFAULT_CONTACTS, mode: values.contactMode },
  };
}

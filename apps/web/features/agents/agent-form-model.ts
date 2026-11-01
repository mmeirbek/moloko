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
  memoryEnabled: boolean;
  includeShared: boolean;
  projects: string;
  maxContextChars: string;
  tools: string[];
  overrides: Record<string, ToolOverride>;
  workspaceId: string;
};

export type ToolOverride = "approve" | "deny";

export type FieldError = "required" | "number" | "tooHigh" | "tooLow";
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
    memoryEnabled: memory.enabled ?? true,
    includeShared: memory.include_shared ?? true,
    projects: (memory.projects ?? []).join(", "),
    maxContextChars: str(memory.max_context_chars),
    tools: [...(agent?.allowed_tools ?? [])],
    overrides: { ...(((agent?.permissions ?? {}) as { tools?: Record<string, ToolOverride> }).tools ?? {}) },
    workspaceId: agent?.workspace_id ?? "",
  };
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
  return errors;
}

export function toPayload(values: AgentFormValues): Omit<AgentCreate, "agent_type"> {
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
  };
}

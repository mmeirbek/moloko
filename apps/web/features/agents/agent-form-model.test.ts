import type { AgentOut, SystemLimits } from "@moloko/shared-types";
import { describe, expect, it } from "vitest";

import { fromAgent, parseProjects, setOverride, toggleTool, toPayload, validate } from "./agent-form-model";

const LIMITS: SystemLimits = {
  max_steps_per_run: 50,
  run_timeout_seconds: 1800,
  max_active_subagents_per_run: 5,
  max_subagent_depth: 2,
  memory_context_max_chars: 8000,
  memory_entry_max_chars: 4000,
};

describe("agent form", () => {
  it("starts with safe defaults", () => {
    const v = fromAgent();
    expect(v.autonomy).toBe("supervised");
    expect(v.memoryEnabled && v.includeShared).toBe(true);
    expect(validate(v, LIMITS)).toEqual({ name: { error: "required" } });
  });

  it("round-trips an agent", () => {
    const agent = {
      name: "Dev",
      description: "Writes code",
      specialization: "coding",
      model_config_id: "m1",
      system_prompt: "Be precise.",
      autonomy_level: "balanced",
      limits: { max_steps: 10, run_timeout_seconds: 600 },
      memory_settings: { include_shared: false, projects: ["moloko"], max_context_chars: 2000 },
      allowed_tools: ["fs_read", "fs_write"],
      permissions: { tools: { fs_write: "approve" } },
      workspace_id: "ws1",
    } as unknown as AgentOut;
    const payload = toPayload(fromAgent(agent));
    expect(payload).toEqual({
      name: "Dev",
      description: "Writes code",
      specialization: "coding",
      model_config_id: "m1",
      system_prompt: "Be precise.",
      autonomy_level: "balanced",
      limits: { max_steps: 10, run_timeout_seconds: 600 },
      memory_settings: { enabled: true, include_shared: false, projects: ["moloko"], max_context_chars: 2000 },
      allowed_tools: ["fs_read", "fs_write"],
      tool_overrides: { fs_write: "approve" },
      workspace_id: "ws1",
    });
  });

  it("empty limits mean the global ones", () => {
    const payload = toPayload({ ...fromAgent(), name: "A" });
    expect(payload.limits).toEqual({ max_steps: null, run_timeout_seconds: null });
    expect(payload.model_config_id).toBeNull();
  });

  it("limits can only be stricter than the global ones", () => {
    const v = { ...fromAgent(), name: "A", maxSteps: "51", timeoutMinutes: "31", maxContextChars: "100" };
    expect(validate(v, LIMITS)).toEqual({
      maxSteps: { error: "tooHigh", limit: 50 },
      timeoutMinutes: { error: "tooHigh", limit: 30 },
      maxContextChars: { error: "tooLow", limit: 200 },
    });
    expect(validate({ ...v, maxSteps: "2.5", timeoutMinutes: "", maxContextChars: "" }, LIMITS)).toEqual({
      maxSteps: { error: "number" },
    });
  });

  it("removing a tool drops its override; overrides of unknown tools are not sent", () => {
    let v = toggleTool({ ...fromAgent(), name: "A" }, "fs_delete", true);
    v = setOverride(v, "fs_delete", "deny");
    expect(toPayload(v).tool_overrides).toEqual({ fs_delete: "deny" });
    v = toggleTool(v, "fs_delete", false);
    expect(v.overrides).toEqual({});
    expect(toPayload({ ...v, overrides: { ghost: "deny" } }).tool_overrides).toEqual({});
    expect(setOverride(toggleTool(v, "x", true), "x", "").overrides).toEqual({});
  });

  it("splits projects", () => {
    expect(parseProjects(" moloko, home ,, moloko ")).toEqual(["moloko", "home"]);
  });
});

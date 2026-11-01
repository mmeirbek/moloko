import { execSync } from "node:child_process";

import { expect, test } from "@playwright/test";

import { api, newAgent, unique } from "./helpers";

// Restarts real containers: only when e2e.sh tells us how (E2E_COMPOSE).
const COMPOSE = process.env.E2E_COMPOSE;

type TaskDetail = { task: { id: string; status: string } };

async function waitForStatus(request: Parameters<typeof api>[0], taskId: string, statuses: string[], timeout = 90_000) {
  await expect
    .poll(async () => (await api<TaskDetail>(request, "GET", `/tasks/${taskId}`)).task.status, { timeout, intervals: [1000] })
    .toMatch(new RegExp(`^(${statuses.join("|")})$`));
}

async function waitForApi(request: Parameters<typeof api>[0]) {
  await expect
    .poll(async () => (await request.get("/api/v1/health").catch(() => null))?.status() ?? 0, { timeout: 120_000, intervals: [1000] })
    .toBe(200);
}

test.describe("recovery after restarts", () => {
  test.skip(!COMPOSE, "set by infrastructure/scripts/e2e.sh");

  test("a running task resumes after the worker and backend restart; an approval survives too", async ({ request }) => {
    const models = await api<{ id: string }[]>(request, "GET", "/models");
    const worker = await newAgent(request, { name: unique("Survivor"), model_config_id: models[0]!.id });
    const started = await api<{ task: { id: string } }>(request, "POST", `/agents/${worker.id}/run`, {
      title: "Long job [[mock:sleep:8]]",
      description: "",
    });
    await waitForStatus(request, started.task.id, ["running"]);

    const careful = await newAgent(request, {
      name: unique("Careful"),
      model_config_id: models[0]!.id,
      autonomy_level: "supervised",
      allowed_tools: ["fs_write"],
    });
    const waiting = await api<{ task: { id: string } }>(request, "POST", `/agents/${careful.id}/run`, {
      title: 'Approval test [[mock:tools]][["fs_write",{"path":"r.txt","content":"ok"}]][[/mock:tools]]',
      description: "",
    });
    await waitForStatus(request, waiting.task.id, ["waiting_approval"]);

    execSync(`${COMPOSE} restart worker backend`, { stdio: "inherit" });
    await waitForApi(request);

    // The interrupted run continues from its checkpoint and finishes (never shown as done early).
    await waitForStatus(request, started.task.id, ["completed"], 120_000);
    // The approval request is still there and still works.
    const pending = await api<{ id: string; task_id: string }[]>(request, "GET", `/approvals?status=pending&task_id=${waiting.task.id}`);
    expect(pending).toHaveLength(1);
    await api(request, "POST", `/approvals/${pending[0]!.id}/approve`);
    await waitForStatus(request, waiting.task.id, ["completed"]);
  });
});

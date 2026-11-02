import { expect, test } from "@playwright/test";

import { api, newAgent, unique, watchErrors } from "./helpers";

type Task = { id: string; status: string };
type Approval = { id: string; task_id: string; status: string };
type ToolCall = { tool_name: string; status: string };

test("full control: write to a working agent, stop it, continue from where it stopped", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const agent = await newAgent(request, {
    name: unique("Worker"),
    model_config_id: models[0]!.id,
    autonomy_level: "balanced", // writing runs at once, deleting waits for an approval
    allowed_tools: ["fs_write", "fs_delete"],
  });
  const script = `[[mock:tools]][["fs_write",{"path":"draft.txt","content":"x"}],["fs_delete",{"path":"draft.txt"}]][[/mock:tools]]`;
  const started = await api<{ task: Task }>(request, "POST", `/agents/${agent.id}/run`, { title: "Draft", description: script });
  const oldId = started.task.id;
  const statusOf = async (id: string) => (await api<{ task: Task }>(request, "GET", `/tasks/${id}`)).task.status;
  await expect.poll(() => statusOf(oldId), { timeout: 60_000 }).toBe("waiting_approval");

  // Write to it while it waits: the message is kept and shown in the history.
  await page.goto(`/tasks/${oldId}`);
  const box = page.getByTestId("message-agent");
  await box.getByRole("textbox").fill("Пиши коротко");
  await box.getByRole("button", { name: "Отправить" }).click();
  await expect(box.getByRole("status")).toContainText("Отправлено");
  await expect(page.getByText("Вы написали агенту: «Пиши коротко»")).toBeVisible();

  // Stop it, then continue from where it stopped, with an instruction.
  await page.getByRole("button", { name: "Отменить задачу" }).first().click();
  const resume = page.getByTestId("continue-task");
  await expect(resume).toBeVisible();
  await resume.getByRole("button", { name: "+ Указание" }).click();
  await resume.getByRole("textbox").fill("Удали черновик");
  await resume.getByRole("button", { name: "Продолжить с места остановки" }).click();
  await expect(page).not.toHaveURL(new RegExp(`/tasks/${oldId}$`));
  const newId = page.url().split("/tasks/")[1]!;
  await expect(page.getByRole("link", { name: "Продолжение остановленной задачи →" })).toBeVisible();

  // The continued attempt does not write the draft again: it goes on to the delete.
  await expect.poll(() => statusOf(newId), { timeout: 60_000 }).toBe("waiting_approval");
  const pending = await api<Approval[]>(request, "GET", "/approvals?status=pending");
  const approval = pending.find((a) => a.task_id === newId)!;
  await api(request, "POST", `/approvals/${approval.id}/approve`);
  await expect.poll(() => statusOf(newId), { timeout: 60_000 }).toBe("completed");
  const calls = await api<ToolCall[]>(request, "GET", `/tasks/${newId}/tool-calls`);
  expect(calls.map((c) => c.tool_name)).toEqual(["fs_delete"]);
  expect(errors).toEqual([]);
});

test("full control: the office inspector offers to continue the agent's stopped task", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const agent = await newAgent(request, { name: unique("Stopper"), model_config_id: models[0]!.id });
  const started = await api<{ task: Task }>(request, "POST", `/agents/${agent.id}/run`, {
    title: "Long one",
    description: "[[mock:sleep:30]]",
  });
  await api(request, "POST", `/tasks/${started.task.id}/cancel`);

  await page.goto(`/office/agents/${agent.id}`);
  const stopped = page.getByTestId("stopped-task");
  await expect(stopped).toContainText("Последняя задача остановилась");
  await expect(stopped.getByRole("link", { name: "Long one" })).toBeVisible();
  await expect(stopped.getByRole("button", { name: "Продолжить с места остановки" })).toBeVisible();
  await expect(stopped.getByRole("button", { name: "Начать заново" })).toBeVisible();
  expect(errors).toEqual([]);
});

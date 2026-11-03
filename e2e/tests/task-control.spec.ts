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
  await expect(page.getByTestId("agent-steps").getByText("Вы написали: «Пиши коротко»")).toBeVisible();

  // Stop it, then continue from where it stopped, with an instruction.
  await page.getByTestId("task-composer").getByRole("button", { name: "Отменить задачу" }).click();
  const resume = page.getByTestId("continue-task");
  await expect(resume).toBeVisible();
  await resume.getByRole("textbox").fill("Удали черновик"); // the chat's box: an instruction
  await resume.getByRole("button", { name: "Продолжить с места остановки" }).click();
  await expect(page).not.toHaveURL(new RegExp(`/tasks/${oldId}$`));
  const newId = page.url().split("/tasks/")[1]!;
  // one chat: the stopped attempt above, the instruction as the new message
  await expect(page.getByTestId("earlier-turn")).toBeVisible();
  await expect(page.getByTestId("task-request")).toHaveText("Удали черновик");

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

test("agent steps: a live line while it works, then one short line per step that opens fully", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const agent = await newAgent(request, { name: unique("Stepper"), model_config_id: models[0]!.id, autonomy_level: "balanced", allowed_tools: ["fs_write"] });
  const script = `[[mock:tools]][["fs_write",{"path":"notes/plan.md","content":"# Plan\\nline two"}]][[/mock:tools]] [[mock:sleep:4]]`;
  const started = await api<{ task: Task }>(request, "POST", `/agents/${agent.id}/run`, { title: "Steps", description: script });
  await page.goto(`/tasks/${started.task.id}`);
  const steps = page.getByTestId("agent-steps");
  await expect(steps.getByTestId("step-live")).toBeVisible(); // «Думает над следующим шагом…» / «В очереди»
  const write = steps.getByTestId("step-tool").filter({ hasText: "Записывает файл plan.md" });
  await expect(write).toBeVisible({ timeout: 60_000 });
  await expect.poll(async () => (await api<{ task: Task }>(request, "GET", `/tasks/${started.task.id}`)).task.status, { timeout: 60_000 }).toBe("completed");
  await expect(steps.getByTestId("step-live")).toHaveCount(0);
  await write.getByRole("button").click();
  await expect(write.getByText("Что передал инструменту")).toBeVisible();
  await expect(write.locator("pre").first()).toContainText("notes/plan.md");
  expect(errors).toEqual([]);
});

test("task chat: a reply after the result continues the task, and the chat shows both turns", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const agent = await newAgent(request, { name: unique("Replier"), model_config_id: models[0]!.id });
  const started = await api<{ task: Task }>(request, "POST", `/agents/${agent.id}/run`, { title: "Which site", description: "Improve the site" });
  const statusOf = async (id: string) => (await api<{ task: Task }>(request, "GET", `/tasks/${id}`)).task.status;
  await expect.poll(() => statusOf(started.task.id), { timeout: 60_000 }).toBe("completed");

  await page.goto(`/tasks/${started.task.id}`);
  const box = page.getByTestId("composer-reply");
  await expect(box).toContainText("Ответ продолжит задачу");
  await box.getByRole("textbox").fill("Сайт moloko на GitHub");
  await box.getByRole("textbox").press("Enter"); // like the chat: Enter sends
  await page.waitForURL((url) => !url.pathname.endsWith(started.task.id));
  // one chat: the first request and answer above, the reply as the new message
  await expect(page.getByTestId("earlier-turn")).toContainText("Echo:");
  await expect(page.getByTestId("task-request")).toHaveText("Сайт moloko на GitHub");
  const newId = page.url().split("/tasks/")[1]!;
  await expect.poll(() => statusOf(newId), { timeout: 60_000 }).toBe("completed");
  await expect(page.getByTestId("task-result")).toBeVisible();
  expect(errors).toEqual([]);
});

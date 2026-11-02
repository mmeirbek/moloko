import { expect, test } from "@playwright/test";

import { api, newAgent, unique, watchErrors } from "./helpers";

type Task = { id: string; status: string; task_type: string; parent_task_id: string | null };

test("agents talk directly: A asks B without the Orchestrator, waits, and finishes with B's answer", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const helper = await newAgent(request, { name: unique("Helper"), model_config_id: models[0]!.id, autonomy_level: "balanced" });
  const asker = await newAgent(request, {
    name: unique("Asker"),
    model_config_id: models[0]!.id,
    autonomy_level: "balanced", // a write tool without an approval
    allowed_tools: ["agents_list", "agent_ask", "agent_tell"],
  });

  // The asker's settings show who it may talk to (everyone by default).
  await page.goto(`/office/agents/${asker.id}`);
  const contacts = page.getByTestId("agent-contacts");
  await expect(contacts.getByRole("radio", { name: /Со всеми/ })).toBeChecked();

  const script = `Спроси коллегу [[mock:tools]][["agent_ask",{"agent":"${helper.name}","request":"Переведи: доброе утро"}]][[/mock:tools]]`;
  await page.getByLabel("Дайте задачу…").fill(script);
  await page.getByRole("button", { name: "Запустить" }).click();

  // The helper got a consult task, and the asker finishes after the answer comes back.
  await expect
    .poll(async () => (await api<{ items: Task[] }>(request, "GET", `/tasks?agent_id=${helper.id}&status=all&include_subtasks=true`)).items.filter((t) => t.task_type === "consult").length, { timeout: 60_000 })
    .toBe(1);
  await expect
    .poll(async () => (await api<{ items: Task[] }>(request, "GET", `/tasks?agent_id=${asker.id}&status=all`)).items[0]?.status, { timeout: 90_000 })
    .toBe("completed");

  // «Переписка»: the question out, the answer in — both with links to the consult task.
  await page.getByRole("tab", { name: "Переписка" }).click();
  const box = page.getByTestId("agent-messages");
  await expect(box.locator("[data-message-type=request]").getByText(helper.name)).toBeVisible();
  await expect(box.locator("[data-message-type=task_result]").getByText(helper.name)).toBeVisible();

  // The consult task says who asked.
  await box.locator("[data-message-type=request]").getByRole("link", { name: "Задача по вопросу" }).click();
  const line = page.getByTestId("team-line");
  await expect(line).toContainText("Спросил агент");
  await expect(line.getByRole("link", { name: asker.name })).toBeVisible();
  expect(errors).toEqual([]);
});

test("agents talk directly: «ни с кем» blocks it, and the refusal is shown with its reason", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const loner = await newAgent(request, { name: unique("Loner"), model_config_id: models[0]!.id, contacts: { mode: "none", agent_ids: [] } });
  const asker = await newAgent(request, {
    name: unique("Asker"),
    model_config_id: models[0]!.id,
    autonomy_level: "balanced",
    allowed_tools: ["agent_tell"],
  });
  await api(request, "POST", `/agents/${asker.id}/run`, {
    title: "Note",
    description: `[[mock:tools]][["agent_tell",{"agent":"${loner.name}","message":"привет"}]][[/mock:tools]]`,
  });
  await expect
    .poll(async () => (await api<{ items: Task[] }>(request, "GET", `/tasks?agent_id=${asker.id}&status=all`)).items[0]?.status, { timeout: 60_000 })
    .toMatch(/completed|failed/);
  await page.goto(`/office/agents/${asker.id}`);
  await page.getByRole("tab", { name: "Переписка" }).click();
  await expect(page.getByTestId("agent-messages").getByText(/Не доставлено/)).toBeVisible();
  expect(errors).toEqual([]);
});

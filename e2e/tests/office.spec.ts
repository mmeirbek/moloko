import { expect, test } from "@playwright/test";

import { newAgent, unique, waitForOffice, watchErrors } from "./helpers";

test("pixel office: real agents, status after reload, inspector, pause freezes, subagents come and go", async ({ page, request }) => {
  const errors = watchErrors(page);
  const agent = await newAgent(request, { name: unique("Office") });
  await page.goto("/office/agents");
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "rest");

  const card = page.locator(`li[data-agent-id="${agent.id}"]`);
  await card.getByPlaceholder("Дайте задачу…").fill("Office test [[mock:sleep:12]]");
  await card.getByRole("button", { name: "Запустить" }).click();
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "type", 20_000);
  await page.reload();
  await waitForOffice(page, (s) => ["working", "reviewing", "idle"].includes(s.find((a) => a.id === agent.id)?.status ?? ""));
  const resting = await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "rest", 40_000);

  const me = resting.find((a) => a.id === agent.id)!;
  const box = (await page.locator("[data-testid=pixel-office] canvas").boundingBox())!;
  await page.mouse.click(box.x + me.x, box.y + me.y);
  const inspector = page.getByRole("complementary", { name: `Агент ${agent.name}` });
  await expect(inspector).toBeVisible();
  await page.getByRole("button", { name: "Закрыть" }).click();

  await card.getByPlaceholder("Дайте задачу…").fill("Pause test [[mock:sleep:8]]");
  await card.getByRole("button", { name: "Запустить" }).click();
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.status === "working");
  await page.getByRole("button", { name: new RegExp(agent.name) }).last().click();
  await inspector.getByRole("button", { name: "Пауза" }).click();
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "frozen");
  await inspector.getByRole("button", { name: "Продолжить" }).click();
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.status === "idle", 60_000);

  await page.goto("/office/subagents");
  await page.getByLabel("Новая задача для Оркестратора").fill("Office crew [[mock:plan:3]] [[mock:slowparts]]");
  await page.getByRole("button", { name: "Запустить" }).click();
  await waitForOffice(page, (s) => s.filter((a) => a.status === "working").length >= 3, 40_000);
  await waitForOffice(page, (s) => s.filter((a) => a.status !== "idle").length === 0, 90_000);
  expect(errors).toEqual([]);
});

test("agent from a template rests in the office until it gets a task", async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto("/office/agents");
  await page.getByTestId("add-agent").click();
  await page.getByTestId("template-translator").click();
  const inspector = page.getByRole("complementary", { name: /Агент Переводчик/ });
  await expect(inspector).toBeVisible();
  const agents = (await (await request.get("/api/v1/agents")).json()) as { id: string; name: string; created_at: string }[];
  const agent = agents.filter((a) => a.name.startsWith("Переводчик")).sort((a, b) => b.created_at.localeCompare(a.created_at))[0]!;
  // no task: it just sits in the lounge, at a desk with its own pet waiting for it
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "rest");
  const tasks = (await (await request.get(`/api/v1/tasks?agent_id=${agent.id}&status=all`)).json()) as { items: unknown[] };
  expect(tasks.items).toEqual([]);

  const form = inspector.getByTestId("give-task");
  await form.getByRole("textbox").fill("Переведи: доброе утро [[mock:sleep:4]]");
  await form.getByRole("button", { name: "Дать задачу" }).click();
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "type", 20_000);
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.status === "idle", 40_000);
  expect(errors).toEqual([]);
});

import { expect, test } from "@playwright/test";

import { api, newAgent, unique, waitForOffice, watchErrors } from "./helpers";

test("pixel office: real agents, status after reload, inspector, pause freezes, the Orchestrator's helpers join and work", async ({ page, request }) => {
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

  // Parts of a plan are done by agents of this office (here: two new helpers it creates).
  await api(request, "POST", "/runs", { title: "Office crew", description: "[[mock:plan:2]] [[mock:spread]] [[mock:slowparts]]" });
  const helpers = async () =>
    (await api<{ id: string; name: string }[]>(request, "GET", "/agents")).filter((a) => /^Helper \d$/.test(a.name)).map((a) => a.id);
  await expect.poll(async () => (await helpers()).length, { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  const ids = await helpers();
  await waitForOffice(page, (s) => s.filter((a) => ids.includes(a.id) && a.status === "working").length >= 2, 40_000);
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
  // no task: it rests at its own desk (with its pet) until it gets one
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "rest");
  const tasks = (await (await request.get(`/api/v1/tasks?agent_id=${agent.id}&status=all`)).json()) as { items: unknown[] };
  expect(tasks.items).toEqual([]);

  const form = inspector.getByTestId("give-task");
  await form.getByRole("textbox").fill("Переведи: доброе утро [[mock:sleep:12]]");
  await form.getByRole("button", { name: "Дать задачу" }).click();
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.pose === "type", 20_000);
  await waitForOffice(page, (s) => s.find((a) => a.id === agent.id)?.status === "idle", 60_000);
  expect(errors).toEqual([]);
});

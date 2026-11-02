import { expect, test, type APIRequestContext } from "@playwright/test";

import { api, newAgent, unique, watchErrors } from "./helpers";

type Agent = { id: string; name: string; created_at: string };

async function researchers(request: APIRequestContext): Promise<Agent[]> {
  const agents = await api<Agent[]>(request, "GET", "/agents");
  return agents.filter((a) => a.name.startsWith("Исследователь")).sort((a, b) => b.created_at.localeCompare(a.created_at));
}

test("island: opens over the page; a template dragged onto the map joins the office", async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto("/tasks");
  const island = page.getByTestId("dynamic-island");
  await island.getByRole("button", { name: "Открыть островок" }).click();
  const map = island.getByTestId("pixel-office");
  await expect(map).toBeVisible();

  const before = (await researchers(request)).length;
  await island.getByTestId("template-researcher").dragTo(map);
  await expect.poll(async () => (await researchers(request)).length).toBe(before + 1);

  await page.keyboard.press("Escape");
  await expect(map).toHaveCount(0);
  expect(errors).toEqual([]);
});

test("island page (Mac notch app): an agent removed from the office is dragged back in", async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto("/island");
  await expect(page.getByTestId("pixel-office")).toBeVisible();
  // a fresh agent from a template, then removed from the office
  await page.getByTestId("template-researcher").click();
  await expect.poll(async () => (await researchers(request)).length).toBeGreaterThan(0);
  const agent = (await researchers(request))[0]!;
  await api(request, "DELETE", `/agents/${agent.id}`);

  await page.reload();
  const card = page.getByTestId(`restore-${agent.id}`);
  await expect(card).toBeVisible();
  await card.dragTo(page.getByTestId("pixel-office"));
  await expect.poll(async () => (await researchers(request)).some((a) => a.id === agent.id)).toBe(true);
  await expect(card).toHaveCount(0); // no longer among the removed ones
  expect(errors).toEqual([]);
});

test("island: a task to the Orchestrator, and to one agent picked in the list", async ({ page, request }) => {
  const errors = watchErrors(page);
  const agent = await newAgent(request, { name: unique("Island") });
  await page.goto("/island");
  const form = page.getByTestId("island-task");
  const input = form.getByLabel("Задача", { exact: true });

  await input.fill(`What time zone is Almaty in? ${unique("island")}`);
  await form.getByRole("button", { name: "Запустить" }).click();
  await expect(form.getByText(/^Отправлено/)).toBeVisible();
  await expect(input).toHaveValue("");

  await form.getByLabel("Кому").selectOption({ label: agent.name });
  await input.fill("Заметка из островка [[mock:sleep:1]]");
  await form.getByRole("button", { name: "Запустить" }).click();
  await expect(form.getByText(/^Отправлено/)).toBeVisible();
  await expect
    .poll(async () => (await api<{ items: { title: string }[] }>(request, "GET", `/tasks?agent_id=${agent.id}&status=all`)).items.length)
    .toBe(1);
  expect(errors).toEqual([]);
});

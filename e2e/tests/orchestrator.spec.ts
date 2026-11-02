import { expect, test } from "@playwright/test";

import { api, unique, watchErrors } from "./helpers";

test("orchestrator: gives the parts to agents (creating them when none fits), merges, answers simple requests directly, chat hand-off", async ({ page, request }) => {
  const errors = watchErrors(page);
  await page.goto("/office/agents");
  /** The cow button → «Новая задача» → the task's own page. */
  const startTask = async (text: string) => {
    const title = `${text} ${unique("run")}`;
    await page.getByTestId("new-task-sidebar").click();
    const dialog = page.getByTestId("new-task-dialog");
    await dialog.getByRole("textbox").fill(title);
    await dialog.getByRole("button", { name: "Начать" }).click(); // waits while the Orchestrator is busy
    await page.waitForURL(/\/tasks\/[0-9a-f-]{36}$/);
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  };
  await startTask("Compare three laptops [[mock:plan:3]] [[mock:slowparts]]");
  const parts = page.getByTestId("part-agent");
  await expect(parts).toHaveCount(3, { timeout: 30_000 });
  await expect(parts.filter({ hasText: "Researcher" })).toHaveCount(2);
  await expect(parts.filter({ hasText: "Analyst" })).toHaveCount(1);
  await expect(page.getByText(/Final answer combining/)).toBeVisible({ timeout: 90_000 });
  // No temporary subagents: the agents it needed are ordinary agents of the office.
  const agents = await api<{ name: string; agent_type: string; archived_at: string | null }[]>(request, "GET", "/agents");
  expect(agents.some((a) => a.agent_type === "subagent")).toBe(false);
  for (const name of ["Researcher", "Analyst"]) {
    expect(agents.some((a) => a.name === name && a.agent_type === "autonomous" && !a.archived_at)).toBe(true);
  }

  await startTask("What time zone is Almaty in?");
  await expect(page.getByText(/^Direct answer:/)).toBeVisible({ timeout: 60_000 });

  // The old Subagent Office address leads to the office.
  await page.goto("/office/subagents");
  await page.waitForURL(/\/office\/agents$/);

  await page.goto("/chat");
  await page.getByRole("link", { name: "Новый чат" }).first().click();
  await page.waitForURL(/\/chat\/new$/);
  const agentsSwitch = page.getByRole("switch", { name: "Отдать агентам" });
  await agentsSwitch.click();
  await expect(agentsSwitch).toHaveAttribute("aria-checked", "true");
  const input = page.getByPlaceholder("Опишите задачу для агентов…"); // the composer shows the mode
  await input.fill("Plan a trip [[mock:plan:2]]");
  await input.press("Enter");
  await page.waitForURL(/\/chat\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Агенты работают над этим…")).toBeVisible();
  await expect(page.getByText(/Final answer combining/)).toBeVisible({ timeout: 90_000 });
  await page.getByText("Сделано агентами — открыть запуск").click();
  await page.waitForURL(/\/tasks\/[0-9a-f-]{36}$/); // the run's task page
  expect(errors).toEqual([]);
});

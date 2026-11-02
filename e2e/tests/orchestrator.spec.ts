import { expect, test } from "@playwright/test";

import { unique, watchErrors } from "./helpers";

test("orchestrator: splits work, merges results, answers simple requests directly, chat hand-off", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/office/subagents");
  /** Starts a run and waits until the page shows it (not an earlier run with the same words). */
  const startRun = async (text: string) => {
    const title = `${text} ${unique("run")}`;
    await page.getByLabel("Новая задача для Оркестратора").fill(title);
    await page.getByRole("button", { name: "Запустить" }).click(); // waits while the Orchestrator is busy
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
  };
  await startRun("Compare three laptops [[mock:plan:3]] [[mock:slowparts]]");
  await expect(page.getByText("Субагенты (3)")).toBeVisible();
  await expect(page.getByText(/Final answer combining/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Сообщения между агентами")).toBeVisible();

  await startRun("What time zone is Almaty in?");
  await expect(page.getByText("Ответил сам — субагенты не понадобились.")).toBeVisible({ timeout: 60_000 });

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
  await expect(page.getByText("Сделано агентами — открыть запуск")).toBeVisible();
  expect(errors).toEqual([]);
});

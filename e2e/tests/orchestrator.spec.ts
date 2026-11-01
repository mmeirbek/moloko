import { expect, test } from "@playwright/test";

import { watchErrors } from "./helpers";

test("orchestrator: splits work, merges results, answers simple requests directly, chat hand-off", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/office/subagents");
  await page.getByLabel("Новая задача для Оркестратора").fill("Compare three laptops [[mock:plan:3]] [[mock:slowparts]]");
  await page.getByRole("button", { name: "Запустить" }).click();
  await expect(page.getByText("Субагенты (3)")).toBeVisible();
  await expect(page.getByText(/Final answer combining/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Сообщения между агентами")).toBeVisible();

  await page.getByLabel("Новая задача для Оркестратора").fill("What time zone is Almaty in?");
  await page.getByRole("button", { name: "Запустить" }).click();
  await expect(page.getByText("Ответил сам — субагенты не понадобились.")).toBeVisible({ timeout: 60_000 });

  await page.goto("/chat");
  await page.getByRole("button", { name: "Новый чат" }).first().click();
  await page.waitForURL(/\/chat\/[0-9a-f-]{36}/);
  await page.getByLabel(/Отдать агентам/).check();
  const input = page.getByPlaceholder("Опишите задачу для агентов…"); // the composer shows the mode
  await input.fill("Plan a trip [[mock:plan:2]]");
  await input.press("Enter");
  await expect(page.getByText("Агенты работают над этим…")).toBeVisible();
  await expect(page.getByText(/Final answer combining/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Сделано агентами — открыть запуск")).toBeVisible();
  expect(errors).toEqual([]);
});

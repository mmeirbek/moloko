import { expect, test } from "@playwright/test";

import { watchErrors } from "./helpers";

const PAGES = ["/chat", "/chat/new", "/office/agents", "/tasks", "/schedules", "/integrations", "/approvals", "/settings", "/settings/ai", "/settings/notifications", "/settings/agents", "/settings/appearance", "/settings/system", "/settings/audit", "/settings/costs", "/search"];

test("phone: every section fits the screen and the bottom bar works", async ({ page }) => {
  const errors = watchErrors(page);
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    // clientWidth, not innerWidth: a phone browser zooms out to fit wide content, so innerWidth grows with it.
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1);
  }
  // The first screen is the message box.
  await page.goto("/");
  await expect(page.getByPlaceholder(/Спросите или поручите работу/)).toBeVisible();
  // «Работа»: the tasks and chats, and the other sections, one tap away.
  await page.getByTestId("work-tab").click();
  const sheet = page.getByTestId("work-sheet");
  await expect(sheet.getByTestId("work-list")).toBeVisible();
  await sheet.getByRole("link", { name: "Все задачи" }).click();
  await expect(page).toHaveURL(/\/tasks$/);
  await expect(sheet).not.toBeVisible();
  await page.getByTestId("work-tab").click();
  await sheet.getByRole("link", { name: /Интеграции/ }).click();
  await expect(page).toHaveURL(/\/integrations/);
  await page.getByRole("navigation", { name: "Основная навигация" }).last().getByRole("link", { name: "Офис агентов" }).click();
  await expect(page).toHaveURL(/\/office\/agents/);
  await page.getByTestId("new-cow").click(); // «Новое»
  await expect(page).toHaveURL(/\/chat\/new$/);
  expect(errors).toEqual([]);
});

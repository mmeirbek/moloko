import { expect, test } from "@playwright/test";

import { watchErrors } from "./helpers";

const PAGES = ["/chat", "/office/subagents", "/office/agents", "/tasks", "/integrations", "/approvals", "/settings", "/settings/audit", "/settings/costs"];

test("phone: every section fits the screen and the tab bar works", async ({ page }) => {
  const errors = watchErrors(page);
  for (const path of PAGES) {
    await page.goto(path);
    await page.waitForLoadState("networkidle");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `horizontal overflow on ${path}`).toBeLessThanOrEqual(1);
  }
  await page.goto("/chat");
  await page.getByRole("navigation", { name: "Основная навигация" }).last().getByRole("link", { name: "Задачи" }).click();
  await expect(page).toHaveURL(/\/tasks/);
  expect(errors).toEqual([]);
});

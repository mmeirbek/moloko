import { expect, test } from "@playwright/test";

import { watchErrors } from "./helpers";

const PAGES = ["/chat", "/office/subagents", "/office/agents", "/tasks", "/integrations", "/approvals", "/settings", "/settings/audit", "/settings/costs", "/search"];

test("phone: every section fits the screen and the tab bar works", async ({ page }) => {
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
  await page.goto("/chat");
  await page.getByRole("navigation", { name: "Основная навигация" }).last().getByRole("link", { name: "Задачи" }).click();
  await expect(page).toHaveURL(/\/tasks/);
  // The rest of the sections are one tap away under "More".
  await page.getByTestId("more-tab").click();
  await page.getByTestId("more-sheet").getByRole("link", { name: /Интеграции/ }).click();
  await expect(page).toHaveURL(/\/integrations/);
  await expect(page.getByTestId("more-sheet")).not.toBeVisible();
  expect(errors).toEqual([]);
});

import { expect, test } from "@playwright/test";

import { watchErrors } from "./helpers";

test("sidebar: drag to resize, keys, fold into the rail, remembered after reload", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/tasks");
  const sidebar = page.locator("#app-sidebar");
  const width = async () => Math.round((await sidebar.boundingBox())!.width);
  await expect.poll(width).toBe(256);

  const edge = page.getByTestId("sidebar-resizer");
  const box = (await edge.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + 300);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 100, box.y + 300, { steps: 8 });
  await page.mouse.up();
  await expect.poll(width).toBe(356);
  await page.reload();
  await expect.poll(width).toBe(356); // applied before the first paint, no jump back

  await edge.focus();
  await page.keyboard.press("Home");
  await expect.poll(width).toBe(208);
  await page.keyboard.press("End");
  await expect.poll(width).toBe(440);
  await edge.dblclick();
  await expect.poll(width).toBe(256);

  // Folded: icons only, every section still reachable by its name.
  await page.getByTestId("sidebar-toggle").click();
  await expect.poll(width).toBe(64);
  await page.reload();
  await expect.poll(width).toBe(64);
  await sidebar.getByRole("link", { name: "Настройки" }).click();
  await expect(page).toHaveURL(/\/settings/);
  await page.getByRole("button", { name: "Развернуть боковую панель" }).click();
  await expect.poll(width).toBe(256);
  expect(errors).toEqual([]);
});

test("wide screen: reading pages sit in the middle, not against the left edge", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 900 });
  for (const path of ["/tasks", "/settings", "/integrations"]) {
    await page.goto(path);
    const main = (await page.locator("main").boundingBox())!;
    const column = (await page.getByTestId("page").boundingBox())!;
    const left = column.x - main.x;
    const right = main.x + main.width - (column.x + column.width);
    expect(Math.abs(left - right), `${path}: left ${left}px, right ${right}px`).toBeLessThanOrEqual(2);
  }
});

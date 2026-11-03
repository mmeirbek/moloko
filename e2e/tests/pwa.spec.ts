import { expect, test } from "@playwright/test";

import { watchErrors } from "./helpers";

test("PWA and security headers", async ({ page, request }) => {
  const errors = watchErrors(page);
  const response = await page.goto("/chat");
  const csp = response!.headers()["content-security-policy"] ?? "";
  expect(csp).toMatch(/script-src 'self' 'nonce-[^']+' 'strict-dynamic'/);
  expect(csp).not.toContain("unsafe-eval");
  expect(csp).toContain("frame-ancestors 'none'");
  expect(response!.headers()["x-frame-options"]).toBe("DENY");
  expect(response!.headers()["x-content-type-options"]).toBe("nosniff");

  const manifest = await (await request.get("/manifest.webmanifest")).json();
  expect(manifest.name).toBe("moloko");
  expect(manifest.display).toBe("standalone");
  expect(manifest.icons.some((i: { sizes: string }) => i.sizes === "512x512")).toBe(true);
  expect((await request.get("/icons/icon-192.png")).headers()["content-type"]).toBe("image/png");

  await expect.poll(() => page.evaluate(async () => !!(await navigator.serviceWorker.getRegistration()))).toBe(true);
  // API responses are never cached (state lives on the server).
  expect((await request.get("/api/v1/health")).headers()["cache-control"]).toContain("no-store");
  expect((await request.get("/offline.html")).ok()).toBe(true);

  // Settings: a short list; each section opens on its own page (old #links still lead there).
  await page.goto("/settings");
  await expect(page.getByTestId("settings-row")).toHaveCount(7);
  await page.getByRole("link", { name: /Уведомления/ }).click();
  await expect(page).toHaveURL(/\/settings\/notifications$/);
  await expect(page.getByTestId("push-settings")).toBeVisible(); // Web Push option for this device
  await page.goto("/settings#system");
  await expect(page).toHaveURL(/\/settings\/system$/);
  await expect(page.getByRole("heading", { name: "Резервные копии" })).toBeVisible();
  await page.goto("/integrations");
  await expect(page.getByTestId("github-mcp")).toBeVisible(); // official GitHub MCP preset
  expect(errors).toEqual([]);
});

test("costs page: totals, per-day chart and the monthly limit", async ({ page }) => {
  await page.goto("/settings/costs");
  await expect(page.getByTestId("costs-spent")).toBeVisible();
  await page.getByLabel("Лимит в месяц, $").fill("100");
  await page.getByTestId("budget-settings").getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByText("Сохранено.")).toBeVisible();
  await expect(page.getByRole("meter")).toBeVisible();
});

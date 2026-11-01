import { expect, test } from "@playwright/test";

import { api, newAgent, unique } from "./helpers";

/** Spec 25.3 targets on a normal home network: main page ≤ 3 s, saved chat ≤ 2 s,
 *  realtime event shown ≤ 1 s. Measured here on the server's own network (a lower bound);
 *  the numbers are printed for docs/performance.md. */
test("performance targets", async ({ page, request }) => {
  const results: Record<string, number> = {};

  let started = Date.now();
  await page.goto("/chat");
  await expect(page.getByRole("button", { name: "Новый чат" }).first()).toBeVisible();
  results.mainPageMs = Date.now() - started;

  const chat = await api<{ id: string }>(request, "POST", "/chats", {});
  started = Date.now();
  await page.goto(`/chat/${chat.id}`);
  await expect(page.getByPlaceholder("Сообщение для moloko…")).toBeVisible();
  results.savedChatMs = Date.now() - started;

  await page.goto("/office/agents");
  await expect(page.getByRole("link", { name: "Новый агент" })).toBeVisible();
  await page.waitForTimeout(1000); // the realtime socket is connected
  const name = unique("Realtime");
  started = Date.now();
  await newAgent(request, { name });
  await expect(page.getByRole("link", { name })).toBeVisible({ timeout: 5000 });
  results.realtimeEventMs = Date.now() - started;

  started = Date.now();
  await page.getByRole("link", { name: "Задачи" }).first().click();
  await expect(page).toHaveURL(/\/tasks/);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  results.sectionSwitchMs = Date.now() - started;

  console.log("PERF", JSON.stringify(results));
  expect(results.mainPageMs).toBeLessThanOrEqual(3000);
  expect(results.savedChatMs).toBeLessThanOrEqual(2000);
  expect(results.realtimeEventMs).toBeLessThanOrEqual(1000);
});

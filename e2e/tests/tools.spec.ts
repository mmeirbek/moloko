import { expect, test } from "@playwright/test";

import { api, newAgent, unique, watchErrors } from "./helpers";

test("tools: every action is approved once, runs in the sandbox, is visible and audited", async ({ page, request }) => {
  const errors = watchErrors(page);
  page.on("dialog", (d) => d.accept());
  // No leftovers from earlier runs.
  for (const a of await api<{ id: string }[]>(request, "GET", "/approvals?status=pending")) {
    await api(request, "POST", `/approvals/${a.id}/cancel-task`);
  }
  await page.goto("/integrations");
  await expect(page.getByText("Песочница работает.")).toBeVisible();
  await expect(page.locator("[data-tool=fs_write]").getByText("Записать файл")).toBeVisible();

  const models = await api<{ id: string; provider_kind: string }[]>(request, "GET", "/models");
  const agent = await newAgent(request, {
    name: unique("Toolsmith"),
    model_config_id: models[0]!.id,
    autonomy_level: "supervised",
    allowed_tools: ["fs_write", "terminal_run", "fs_read"],
  });
  await page.goto(`/office/agents/${agent.id}`);
  await expect(page.locator("[data-agent-tool=terminal_run] input[type=checkbox]")).toBeChecked();
  const script =
    `Sandbox test [[mock:tools]][["fs_write",{"path":"hello.py","content":"print('hi from sandbox')"}],` +
    `["terminal_run",{"command":"python hello.py"}]][[/mock:tools]]`;
  await page.getByLabel("Дайте задачу…").fill(script);
  await page.getByRole("button", { name: "Запустить" }).click();

  const badge = page.getByTestId("approvals-badge").first();
  await expect(badge).toHaveText("1");
  await badge.click();
  const pending = page.locator("section[aria-labelledby=pending-title] [data-approval-id]");
  const first = pending.filter({ hasText: "Записать файл hello.py" });
  await expect(first.getByText("workspace:hello.py")).toBeVisible();
  await expect(first.getByText(`Просит: ${agent.name}`)).toBeVisible();
  const taskHref = await first.locator("a[href^='/tasks/']").getAttribute("href");
  await first.getByRole("button", { name: "Одобрить" }).click();
  await pending.filter({ hasText: "Выполнить: python hello.py" }).getByRole("button", { name: "Одобрить" }).click();
  await expect(page.getByText("Сейчас ничего не ждёт одобрения.")).toBeVisible();
  await expect(page.getByTestId("approvals-badge")).toHaveCount(0);

  await page.goto(taskHref!);
  await expect(page.getByText("Готово").first()).toBeVisible({ timeout: 60_000 });
  const call = page.locator("[data-tool-call=terminal_run]");
  await call.getByText("Параметры и результат").click();
  await expect(call.getByText(/hi from sandbox/).first()).toBeVisible();
  await expect(page.getByTestId("file-browser").getByText("hello.py")).toBeVisible();

  await page.goto("/settings/audit");
  await page.getByLabel("Раздел").selectOption("tool.");
  await expect(page.locator("[data-audit-action='tool.executed']").first()).toBeVisible();
  expect(errors).toEqual([]);
});

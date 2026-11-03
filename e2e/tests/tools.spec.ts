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

  // The task waits for the owner: at the top of the work list, with why.
  await expect(page.getByTestId("work-waiting").getByText("нужно ваше одобрение")).toBeVisible();
  await page.goto("/approvals");
  const pending = page.locator("section[aria-labelledby=pending-title] [data-approval-id]");
  const first = pending.filter({ hasText: "Записать файл hello.py" });
  await expect(first.getByText("workspace:hello.py")).toBeVisible();
  await expect(first.getByText(`Просит: ${agent.name}`)).toBeVisible();
  const taskHref = await first.locator("a[href^='/tasks/']").getAttribute("href");
  await first.getByRole("button", { name: "Одобрить", exact: true }).click();
  await pending.filter({ hasText: "Выполнить: python hello.py" }).getByRole("button", { name: "Одобрить", exact: true }).click();
  await expect(page.getByText("Сейчас ничего не ждёт одобрения.")).toBeVisible();
  await expect(page.getByTestId("work-list").getByText("нужно ваше одобрение")).toHaveCount(0);

  await page.goto(taskHref!);
  await expect(page.getByText("Готово").first()).toBeVisible({ timeout: 60_000 });
  // The agent's steps: one line per action, a click shows everything it passed and got back.
  const call = page.getByTestId("step-tool").filter({ hasText: "Скрипт python" }); // what it is for, not the command
  await expect(call).toContainText("hi from sandbox"); // the first line of the output, collapsed
  await call.getByRole("button").click();
  await expect(call.getByText("Что получилось")).toBeVisible();
  await expect(call.locator("pre").filter({ hasText: /hi from sandbox/ })).toBeVisible();
  await expect(call.locator("pre").filter({ hasText: "python hello.py" })).toBeVisible(); // the command itself
  await expect(page.getByTestId("file-browser").getByText("hello.py")).toBeVisible();
  // «Что получилось» under the answer: the file it wrote, one tap away.
  await page.getByTestId("task-outcome").getByRole("button", { name: "hello.py" }).click();
  await expect(page.getByTestId("outcome-file").getByText("print('hi from sandbox')")).toBeVisible();
  await page.keyboard.press("Escape");

  await page.goto("/settings/audit");
  await page.getByLabel("Раздел").selectOption("tool.");
  await expect(page.locator("[data-audit-action='tool.executed']").first()).toBeVisible();
  expect(errors).toEqual([]);
});

import { expect, test } from "@playwright/test";

import { api, newAgent, unique, watchErrors } from "./helpers";

test("work list: «@agent» makes a task, work from the chat goes to the agents, a question waits for the owner", async ({ page, request }) => {
  const errors = watchErrors(page);
  const models = await api<{ id: string }[]>(request, "GET", "/models");
  const writer = await newAgent(request, { name: unique("Writer"), model_config_id: models[0]!.id });

  // «@Wri…» suggests the agent; the message becomes its task and the task opens.
  await page.goto("/chat/new");
  const input = page.getByPlaceholder(/Спросите или поручите работу/);
  await input.fill("@Wri");
  await page.getByRole("list", { name: "Кому поручить" }).getByRole("button", { name: writer.name }).click();
  await expect(input).toHaveValue(`@${writer.name} `);
  await input.pressSequentially("Какой сайт нужен?");
  await expect(page.getByTestId("mention-target")).toContainText(writer.name);
  await input.press("Enter");
  await page.waitForURL(/\/tasks\/[0-9a-f-]{36}$/);
  await expect(page.getByTestId("task-request")).toContainText("Какой сайт нужен?");
  await expect(page.getByTestId("task-result")).toContainText("Echo:", { timeout: 60_000 });
  // Its answer ends with a question: the task waits for the owner, at the top of the list.
  const waiting = page.getByTestId("work-waiting");
  await expect(waiting.getByTestId("work-task").filter({ hasText: "Какой сайт нужен?" })).toBeVisible();
  await expect(waiting).toContainText("ждёт вашего ответа");

  // A plain request for work goes to the agents by itself; their answer comes into the chat.
  await page.getByTestId("new-chat-sidebar").click();
  await page.waitForURL(/\/chat\/new$/);
  await input.fill("Почини форму входа [[mock:work]]");
  await input.press("Enter");
  await page.waitForURL(/\/chat\/[0-9a-f-]{36}$/);
  await expect(page.getByText("Агенты работают над этим…").or(page.getByText("Сделано агентами — открыть запуск"))).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByText("[[agents]]")).toHaveCount(0); // the chat's marker answer is never shown
  await expect(page.getByText(/Direct answer|Final answer/).first()).toBeVisible({ timeout: 90_000 });
  // The chat stands for that work in «Недавние» (no second entry for its task).
  await expect(page.getByTestId("work-recent").getByTestId("work-chat").filter({ hasText: "Почини форму входа" })).toBeVisible();
  await expect(page.getByTestId("work-list").getByTestId("work-task").filter({ hasText: "Почини форму входа" })).toHaveCount(0);
  expect(errors).toEqual([]);
});

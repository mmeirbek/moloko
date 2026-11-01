import { expect, test } from "@playwright/test";

import { unique, watchErrors } from "./helpers";

test("agents: create with limits, edit, memory with history, run/pause/resume, delete", async ({ page }) => {
  const errors = watchErrors(page);
  page.on("dialog", (d) => d.accept());
  await page.goto("/office/agents/new");
  const name = unique("Writer");
  await page.getByLabel("Имя", { exact: true }).fill(name);
  const model = page.getByLabel("Модель", { exact: true });
  const mockOption = model.locator("option", { hasText: /mock/i }).first();
  await expect(mockOption).toBeAttached(); // models load asynchronously
  await model.selectOption((await mockOption.getAttribute("value"))!);
  await page.getByLabel("Инструкции").fill("Отвечай кратко.");
  await page.getByText("Сбалансированно").click();
  await page.getByLabel("Максимум шагов").fill("60");
  await page.getByRole("button", { name: "Создать агента" }).click();
  await expect(page.getByText("Не больше 50 (общий лимит).")).toBeVisible(); // stricter only
  await page.getByLabel("Максимум шагов").fill("10");
  await page.getByRole("button", { name: "Создать агента" }).click();
  await page.waitForURL(/\/office\/agents\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();

  await page.getByLabel("Инструкции").fill("Отвечай кратко и по делу.");
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Сохранено" })).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Инструкции")).toHaveValue("Отвечай кратко и по делу.");

  await page.getByRole("tab", { name: "Память" }).click();
  await page.getByRole("button", { name: "Добавить запись" }).click();
  await page.getByLabel("Заголовок").fill("Стиль");
  await page.getByLabel("Текст").fill("Пиши коротко.");
  await page.getByRole("button", { name: "Сохранить" }).click();
  const item = page.locator("[data-memory-id]").filter({ hasText: "Стиль" });
  await expect(item).toBeVisible();
  await expect(page.getByTestId("memory-context")).toContainText("В промпт агента");
  await item.getByRole("button", { name: "Изменить" }).click();
  await page.getByLabel("Текст").fill("Пиши очень коротко.");
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(item).toContainText("версия 2");

  await page.getByLabel("Дайте задачу…").fill("Заметка [[mock:sleep:8]]");
  await page.getByRole("button", { name: "Запустить" }).click();
  await page.getByRole("button", { name: "Пауза" }).click();
  await page.getByRole("button", { name: "Продолжить" }).click();
  await page.getByRole("tab", { name: "История задач" }).click();
  await expect(page.getByRole("list", { name: "Задачи агента" }).getByText("Готово")).toBeVisible({ timeout: 60_000 });

  await page.getByRole("button", { name: "Удалить" }).click();
  await page.waitForURL(/\/office\/agents$/);
  await expect(page.getByRole("link", { name })).toHaveCount(0);
  expect(errors).toEqual([]);
});

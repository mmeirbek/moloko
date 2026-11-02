import { expect, test } from "@playwright/test";

import { OWNER, watchErrors } from "./helpers";

test("settings: the owner changes how long a sign-in lasts, confirmed with the password", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/settings#system");
  const card = page.getByTestId("session-lifetime");
  await expect(card).toContainText("по умолчанию");

  await card.getByLabel("Срок входа").selectOption({ label: "1 день" });
  await card.getByLabel("Ваш пароль moloko").fill("not the password");
  await card.getByRole("button", { name: "Сохранить срок" }).click();
  await expect(card.getByRole("alert")).toHaveText("Пароль не подошёл.");
  await expect(card.getByLabel("Ваш пароль moloko")).toHaveValue(""); // never kept after a try

  await card.getByLabel("Ваш пароль moloko").fill(OWNER.password);
  await card.getByRole("button", { name: "Сохранить срок" }).click();
  await expect(card.getByRole("status")).toContainText("Сохранено");
  await expect(card).toContainText("Сейчас: 1 день.");
  await page.reload();
  await expect(page.getByTestId("session-lifetime")).toContainText("Сейчас: 1 день.");

  // Back to the default, so the other tests keep the usual sign-in length.
  const again = page.getByTestId("session-lifetime");
  await again.getByLabel("Срок входа").selectOption("default");
  await again.getByLabel("Ваш пароль moloko").fill(OWNER.password);
  await again.getByRole("button", { name: "Сохранить срок" }).click();
  await expect(again).toContainText("(по умолчанию)");
  expect(errors).toEqual([]);
});

import { expect, test } from "@playwright/test";

import { OWNER, api, watchErrors } from "./helpers";

test("settings: the owner changes how long a sign-in lasts, confirmed with the password", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/settings/system");
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

test("settings: moloko addresses the owner the way he asks", async ({ page, request }) => {
  const errors = watchErrors(page);
  await api(request, "PATCH", "/auth/profile", { address_as: null }); // start from no form of address
  await page.goto("/settings/system");
  const field = page.getByLabel("Как moloko к вам обращается");
  await field.fill("Мейрбек Максатович");
  await field.press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Сохранено." })).toBeVisible();
  await page.goto("/chat/new");
  await expect(page.getByRole("heading", { name: "Чем помочь, Мейрбек Максатович?" })).toBeVisible();

  await page.goto("/settings/system"); // back to no special form of address
  await page.getByLabel("Как moloko к вам обращается").fill("");
  await page.getByLabel("Как moloko к вам обращается").press("Enter");
  await expect(page.getByRole("status").filter({ hasText: "Сохранено." })).toBeVisible();
  expect(errors).toEqual([]);
});

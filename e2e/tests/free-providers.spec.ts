import { expect, test } from "@playwright/test";

import { watchErrors } from "./helpers";

test("free models: official platforms with a link for the key and a field to paste it", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/settings/ai");
  const card = page.getByTestId("free-providers");
  await expect(card.getByRole("heading", { name: "Бесплатные модели" })).toBeVisible();
  const groq = card.getByTestId("free-groq");
  await expect(groq).toContainText("Groq");
  await expect(groq.getByRole("link", { name: /Получить ключ/ })).toHaveAttribute("href", "https://console.groq.com/keys");
  await groq.getByRole("button", { name: "Подключить" }).click();
  await expect(groq.getByLabel("Ключ API")).toBeVisible();
  await expect(groq.getByRole("button", { name: "Подключить" })).toBeDisabled(); // no key yet
  await groq.getByRole("button", { name: "Отмена" }).click();
  // Cloudflare's address needs the account id too
  await card.getByTestId("free-cloudflare").getByRole("button", { name: "Подключить" }).click();
  await expect(card.getByTestId("free-cloudflare").getByLabel("ID аккаунта Cloudflare")).toBeVisible();
  await expect(card.getByTestId("free-cohere")).toHaveCount(0); // its terms forbid personal use
  expect(errors).toEqual([]);
});

test("codex: the ChatGPT sign-in card says what to run on the server", async ({ page }) => {
  const errors = watchErrors(page);
  await page.goto("/settings/ai");
  const card = page.getByTestId("codex-card");
  await expect(card.getByRole("heading", { name: "Codex — вход через ChatGPT" })).toBeVisible();
  // the throwaway stack's codex service runs, nobody signed in there
  await expect(card.getByRole("status")).toContainText("Вход ещё не выполнен", { timeout: 30_000 });
  await expect(card.getByTestId("codex-login-command")).toHaveText("docker compose exec codex codex login --device-auth");
  await expect(card.getByRole("button", { name: "Подключить" })).toBeDisabled();
  expect(errors).toEqual([]);
});


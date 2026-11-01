import { devices, expect, test } from "@playwright/test";

import { OWNER, watchErrors } from "./helpers";

test("chat: streaming, markdown, history, attachments, stop, errors, second device", async ({ page, browser }) => {
  const errors = watchErrors(page);
  await page.goto("/chat");
  await page.getByRole("button", { name: "Новый чат" }).first().click();
  await page.waitForURL(/\/chat\/[0-9a-f-]{36}/);
  const chatUrl = page.url();
  const input = page.getByPlaceholder("Сообщение для moloko…");
  /** The composer accepts a message only when no answer is running (Send button shown). */
  const say = async (text: string) => {
    await expect(page.getByRole("button", { name: "Отправить" })).toBeVisible({ timeout: 30_000 });
    await input.fill(text);
    await input.press("Enter");
    await expect(input).toHaveValue("");
  };

  await say("Привет, **moloko**!");
  await expect(page.getByText("Echo: Привет, ")).toBeVisible();
  await expect(page.locator(".markdown strong", { hasText: "moloko" }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText("Echo: Привет, ")).toBeVisible(); // history survives reload

  // Attach a text file; it is sent with the message and shown on it.
  await page.locator("input[type=file]").setInputFiles({ name: "notes.md", mimeType: "text/markdown", buffer: Buffer.from("# Notes") });
  await expect(page.locator("[data-attachment='notes.md']")).toBeVisible();
  await say("Что в файле?");
  await expect(page.getByRole("list", { name: "Прикреплённые файлы" }).getByText("notes.md").first()).toBeVisible();
  await expect(page.getByText("Echo: Что в файле?")).toBeVisible(); // wait for the answer before the next message

  // A picture: shown as a thumbnail served by the API (same origin, CSP-safe).
  const png = Buffer.from(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d4944415478da63f8cfc0f01f0005000201a0a2b6e30000000049454e44ae426082",
    "hex",
  );
  await page.locator("input[type=file]").setInputFiles({ name: "cow.png", mimeType: "image/png", buffer: png });
  await expect(page.locator("[data-attachment='cow.png'] img")).toBeVisible();
  await say("Что на картинке?");
  await expect(page.getByText("Echo: Что на картинке?")).toBeVisible();
  const thumb = page.getByRole("list", { name: "Прикреплённые файлы" }).getByRole("img", { name: "cow.png" }).first();
  await expect(thumb).toBeVisible();
  expect(await thumb.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBe(1);

  // A slow answer started here is visible live on a phone that opens the chat mid-stream.
  await say("[[mock:slow]] раз два три четыре пять шесть семь восемь");
  // A second device with its OWN session (new contexts inherit the saved one otherwise).
  const phone = await browser.newContext({
    ...devices["iPhone 13"],
    locale: "ru-RU",
    storageState: { cookies: [], origins: [] },
  });
  const ppage = await phone.newPage();
  await ppage.goto("/login");
  await ppage.getByLabel("Имя пользователя").fill(OWNER.username);
  await ppage.getByLabel("Пароль").fill(OWNER.password);
  await ppage.getByRole("button", { name: "Войти" }).click();
  await ppage.waitForURL(/\/chat/);
  await ppage.goto(chatUrl);
  await expect(ppage.getByText("Echo: раз два три четыре пять шесть семь восемь")).toBeVisible();
  await phone.close();
  await expect(page.getByText("Echo: раз два три четыре пять шесть семь восемь")).toBeVisible();

  // Stop, and an honest provider error.
  await say("[[mock:slow]] a b c d e f g h i j k l m n o p");
  await page.getByRole("button", { name: "Остановить" }).click({ delay: 800 });
  await expect(page.getByText("Остановлено.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Отправить" })).toBeVisible();
  await say("[[mock:error:rate_limited]]");
  await expect(page.getByText("Провайдер ограничивает частоту запросов")).toBeVisible();
  await expect(page.getByText(/Код ошибки:/).first()).toBeVisible();
  expect(errors).toEqual([]);
});

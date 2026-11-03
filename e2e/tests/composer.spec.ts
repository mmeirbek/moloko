import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

import { watchErrors } from "./helpers";

const fixture = (name: string) => path.resolve(__dirname, "../fixtures", name);

async function newChat(page: Page) {
  await page.goto("/chat/new");
  return page.getByPlaceholder(/Спросите или поручите работу/);
}

test("composer: any number of files of any type and size go with one message", async ({ page }) => {
  const errors = watchErrors(page);
  const input = await newChat(page);
  const files = [
    ...Array.from({ length: 6 }, (_, i) => ({ name: `note-${i + 1}.md`, mimeType: "text/markdown", buffer: Buffer.from(`# Note ${i + 1}`) })),
    // a 3 MB binary of an unknown type: stored, shown, and given to the model as a short note
    { name: "archive.bin", mimeType: "application/octet-stream", buffer: Buffer.alloc(3 * 1024 * 1024, 7) },
    { name: "data.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") },
  ];
  await page.locator("input[type=file]").setInputFiles(files);
  const chips = page.getByTestId("composer-files").locator("li");
  await expect(chips).toHaveCount(files.length);
  await expect(page.getByTestId("composer-files").locator("li[data-status=done]")).toHaveCount(files.length, { timeout: 30_000 });

  await input.fill("Что в файлах?");
  await input.press("Enter");
  await page.waitForURL(/\/chat\/[0-9a-f-]{36}$/);
  const sent = page.getByRole("list", { name: "Прикреплённые файлы" }).first();
  for (const f of files) await expect(sent.getByText(f.name)).toBeVisible();
  expect(errors).toEqual([]);
});

for (const [lang, file, words] of [
  ["Russian", "speech-ru.wav", /проверк/i],
  ["English", "speech-en.wav", /test/i],
] as const) {
  test(`voice: a ${lang} phrase becomes text in the composer`, async ({ playwright, baseURL }) => {
    // Its own browser: Chromium plays the file as the microphone (a launch option, so it
    // cannot be set per test with test.use).
    const browser = await playwright.chromium.launch({
      executablePath: process.env.E2E_CHROMIUM_PATH,
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        `--use-file-for-fake-audio-capture=${fixture(file)}`,
      ],
    });
    try {
      const context = await browser.newContext({
        baseURL,
        locale: "ru-RU",
        viewport: { width: 1280, height: 900 },
        permissions: ["microphone"],
        storageState: path.resolve(__dirname, "../.auth/owner.json"),
      });
      const page = await context.newPage();
      const errors = watchErrors(page);
      // The local speech model really hears the phrase; without it (the default e2e stack)
      // the mock provider answers with a fixed phrase — the round trip is still checked.
      const settings = (await (await page.request.get("/api/v1/ai/settings")).json()) as { voice_engine?: string | null };
      const expected = settings.voice_engine === "local" ? words : /moloko/i;
      const input = await newChat(page);
      await page.getByTestId("mic").click();
      const strip = page.getByTestId("mic-recording");
      await expect(strip).toBeVisible();
      await page.waitForTimeout(4500); // the phrase is ~3 s
      await strip.getByRole("button", { name: /Готово/ }).click();
      await expect(input).toHaveValue(expected, { timeout: 60_000 });
      expect(errors).toEqual([]);
    } finally {
      await browser.close();
    }
  });
}

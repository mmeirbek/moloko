import { defineConfig, devices } from "@playwright/test";

// The stack must be running (infrastructure/scripts/e2e.sh starts a throwaway one).
const baseURL = process.env.E2E_BASE_URL ?? "http://127.0.0.1:8080";
const executablePath = process.env.E2E_CHROMIUM_PATH; // e.g. a pre-installed browser

export default defineConfig({
  testDir: "./tests",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1, // one owner, shared state: run in order
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never", outputFolder: "playwright-report" }]],
  use: {
    baseURL,
    locale: "ru-RU",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    launchOptions: executablePath ? { executablePath } : {},
  },
  projects: [
    { name: "setup", testMatch: /setup\.ts/ },
    {
      name: "desktop",
      dependencies: ["setup"],
      testIgnore: /mobile\.spec\.ts/,
      use: { ...devices["Desktop Chrome"], viewport: { width: 1280, height: 900 }, storageState: ".auth/owner.json" },
    },
    {
      name: "phone",
      dependencies: ["setup"],
      testMatch: /mobile\.spec\.ts/,
      use: { ...devices["iPhone 13"], browserName: "chromium", storageState: ".auth/owner.json" },
    },
  ],
});

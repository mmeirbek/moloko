import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const OWNER = {
  username: process.env.E2E_USERNAME ?? "owner",
  password: process.env.E2E_PASSWORD ?? "e2e owner password 123",
};

/** Page errors and CSP violations must never happen. */
export function watchErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error" && /Content Security Policy|Refused to/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

export async function csrf(request: APIRequestContext): Promise<string> {
  const resp = await request.get("/api/v1/auth/csrf");
  return (await resp.json()).csrf_token as string;
}

export async function api<T = unknown>(
  request: APIRequestContext,
  method: "GET" | "POST" | "PATCH" | "PUT" | "DELETE",
  path: string,
  data?: unknown,
): Promise<T> {
  const headers: Record<string, string> = method === "GET" ? {} : { "X-CSRF-Token": await csrf(request) };
  const resp = await request.fetch(`/api/v1${path}`, { method, data, headers });
  expect(resp.ok(), `${method} ${path}: ${resp.status()} ${await resp.text()}`).toBeTruthy();
  return (resp.status() === 204 ? undefined : await resp.json()) as T;
}

export async function newAgent(
  request: APIRequestContext,
  body: Record<string, unknown>,
): Promise<{ id: string; name: string }> {
  return api(request, "POST", "/agents", { system_prompt: "Be brief.", ...body });
}

/** The Pixel Office test hook: characters with status, pose and screen position. */
export async function officeState(page: Page): Promise<{ id: string; status: string; pose: string; x: number; y: number }[]> {
  return page.evaluate(() => {
    const c = document.querySelector<HTMLCanvasElement>("[data-testid=pixel-office] canvas");
    return c?.dataset.agents ? JSON.parse(c.dataset.agents) : [];
  });
}

export async function waitForOffice(
  page: Page,
  predicate: (s: Awaited<ReturnType<typeof officeState>>) => boolean,
  timeout = 30_000,
) {
  await expect.poll(async () => predicate(await officeState(page)), { timeout }).toBe(true);
  return officeState(page);
}

export const unique = (prefix: string) => `${prefix} ${Date.now().toString().slice(-6)}`;

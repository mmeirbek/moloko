import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "./client";
import { ApiError } from "./errors";

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const errorBody = (code: string) => ({ error: { id: "err-1", code, message: "msg" } });

describe("api client", () => {
  it("sends the CSRF cookie value as a header on mutating requests", async () => {
    const fetchMock = vi.fn(async () => json(200, { ok: true }));
    const client = createApiClient({ fetch: fetchMock, readCookie: () => "tok.sig" });
    await client.request("/auth/login", { method: "POST", body: { a: 1 } });

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/auth/login");
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("tok.sig");
    expect(init.credentials).toBe("same-origin");
    expect(init.body).toBe('{"a":1}');
  });

  it("does not send CSRF on GET", async () => {
    const fetchMock = vi.fn(async () => json(200, {}));
    const client = createApiClient({ fetch: fetchMock, readCookie: () => "tok.sig" });
    await client.request("/auth/me");
    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBeUndefined();
  });

  it("fetches a CSRF token first when the cookie is missing", async () => {
    let cookie: string | null = null;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/auth/csrf")) {
        cookie = "fresh.sig";
        return json(200, { csrf_token: "fresh.sig" });
      }
      return json(200, { ok: true });
    });
    const client = createApiClient({ fetch: fetchMock as typeof fetch, readCookie: () => cookie });
    await client.request("/auth/logout", { method: "POST" });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, init] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
    expect((init.headers as Record<string, string>)["X-CSRF-Token"]).toBe("fresh.sig");
  });

  it("refreshes the token and retries once after csrf_failed", async () => {
    let cookie = "stale.sig";
    let attempts = 0;
    const fetchMock = vi.fn(async (url: string) => {
      if (url.endsWith("/auth/csrf")) {
        cookie = "fresh.sig";
        return json(200, { csrf_token: "fresh.sig" });
      }
      attempts += 1;
      return attempts === 1 ? json(403, errorBody("csrf_failed")) : json(200, { ok: true });
    });
    const client = createApiClient({ fetch: fetchMock as typeof fetch, readCookie: () => cookie });
    await expect(client.request("/x", { method: "POST" })).resolves.toEqual({ ok: true });
    expect(attempts).toBe(2);
  });

  it("turns error envelopes into ApiError with the server error id", async () => {
    const client = createApiClient({
      fetch: async () => json(401, errorBody("invalid_credentials")),
      readCookie: () => "t.s",
    });
    const err = await client.request<never>("/auth/login", { method: "POST" }).catch((e: unknown) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(401);
    expect(err.code).toBe("invalid_credentials");
    expect(err.errorId).toBe("err-1");
    expect(err.isUnauthenticated).toBe(true);
  });

  it("maps network failures to network_error", async () => {
    const client = createApiClient({
      fetch: async () => {
        throw new TypeError("Failed to fetch");
      },
      readCookie: () => null,
    });
    const err = await client.request<never>("/auth/me").catch((e: unknown) => e as ApiError);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe("network_error");
    expect(err.status).toBe(0);
  });

  it("handles non-JSON error bodies", async () => {
    const client = createApiClient({
      fetch: async () => new Response("<html>bad gateway</html>", { status: 502 }),
      readCookie: () => null,
    });
    const err = await client.request<never>("/auth/me").catch((e: unknown) => e as ApiError);
    expect(err.code).toBe("server_error");
  });

  it("returns the body for explicitly accepted statuses (503 health)", async () => {
    const client = createApiClient({
      fetch: async () => json(503, { status: "degraded" }),
      readCookie: () => null,
    });
    await expect(client.request("/health", { acceptStatuses: [503] })).resolves.toEqual({
      status: "degraded",
    });
  });
});

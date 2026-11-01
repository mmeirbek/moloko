import type { CsrfResponse } from "@moloko/shared-types";

import { API_BASE, CSRF_COOKIE, CSRF_HEADER } from "./config";
import { ApiError } from "./errors";

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  method?: Method;
  body?: unknown;
  signal?: AbortSignal;
  /** Return the parsed body even for non-2xx statuses listed here (e.g. 503 health). */
  acceptStatuses?: number[];
  /** Return the raw Response (for streaming bodies such as SSE) instead of parsed JSON. */
  raw?: boolean;
}

export interface ClientDeps {
  fetch: typeof fetch;
  readCookie: (name: string) => string | null;
}

export function readBrowserCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  for (const part of document.cookie.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) return decodeURIComponent(rest.join("="));
  }
  return null;
}

const MUTATING = new Set<Method>(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * Thin fetch wrapper used by every API call:
 *  - same-origin cookies (session) are sent automatically;
 *  - state-changing requests carry the CSRF token (fetched on demand);
 *  - a rejected CSRF token is refreshed and the request retried once;
 *  - every failure becomes an ApiError with the server's error id.
 */
export function createApiClient(deps: ClientDeps) {
  let csrfInFlight: Promise<string> | null = null;

  async function fetchCsrf(): Promise<string> {
    csrfInFlight ??= (async () => {
      try {
        const data = await send<CsrfResponse>("/auth/csrf", {}, false);
        return data.csrf_token;
      } finally {
        csrfInFlight = null;
      }
    })();
    return csrfInFlight;
  }

  async function send<T>(path: string, opts: RequestOptions, withCsrf: boolean): Promise<T> {
    const method = opts.method ?? "GET";
    const headers: Record<string, string> = {
      Accept: opts.raw ? "text/event-stream" : "application/json",
    };
    const isForm = typeof FormData !== "undefined" && opts.body instanceof FormData;
    if (opts.body !== undefined && !isForm) headers["Content-Type"] = "application/json";
    if (withCsrf) {
      headers[CSRF_HEADER] = deps.readCookie(CSRF_COOKIE) ?? (await fetchCsrf());
    }

    let response: Response;
    try {
      response = await deps.fetch(`${API_BASE}${path}`, {
        method,
        headers,
        body: opts.body === undefined ? undefined : isForm ? (opts.body as FormData) : JSON.stringify(opts.body),
        credentials: "same-origin",
        signal: opts.signal,
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
      throw ApiError.network(cause);
    }

    if (opts.raw && response.ok) return response as T;
    if (response.status === 204) return undefined as T;
    let body: unknown = null;
    try {
      body = await response.json();
    } catch {
      body = null;
    }
    if (response.ok || opts.acceptStatuses?.includes(response.status)) return body as T;
    throw ApiError.fromBody(response.status, body);
  }

  async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
    const mutating = MUTATING.has(opts.method ?? "GET");
    try {
      return await send<T>(path, opts, mutating);
    } catch (err) {
      if (mutating && err instanceof ApiError && err.code === "csrf_failed") {
        await fetchCsrf(); // sets a fresh cookie bound to the current session
        return send<T>(path, opts, true);
      }
      throw err;
    }
  }

  /** Like request(), but resolves to the streaming Response once headers arrive. */
  function stream(path: string, opts: Omit<RequestOptions, "raw"> = {}): Promise<Response> {
    return request<Response>(path, { ...opts, raw: true });
  }

  return { request, stream };
}

export const api = createApiClient({
  fetch: (...args) => fetch(...args),
  readCookie: readBrowserCookie,
});

import type { ErrorResponse } from "@moloko/shared-types";

/** Every failed API call surfaces as an ApiError — one place to handle errors. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly errorId: string | null;
  readonly details: unknown;

  constructor(opts: {
    status: number;
    code: string;
    message: string;
    errorId?: string | null;
    details?: unknown;
  }) {
    super(opts.message);
    this.name = "ApiError";
    this.status = opts.status;
    this.code = opts.code;
    this.errorId = opts.errorId ?? null;
    this.details = opts.details;
  }

  static network(cause: unknown): ApiError {
    const err = new ApiError({
      status: 0,
      code: "network_error",
      message: "The server could not be reached.",
    });
    err.cause = cause;
    return err;
  }

  static fromBody(status: number, body: unknown): ApiError {
    if (isErrorResponse(body)) {
      const { id, code, message, details } = body.error;
      return new ApiError({ status, code, message, errorId: id, details });
    }
    return new ApiError({
      status,
      code: status >= 500 ? "server_error" : "http_error",
      message: `Request failed with status ${status}.`,
    });
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }
}

function isErrorResponse(body: unknown): body is ErrorResponse {
  if (typeof body !== "object" || body === null || !("error" in body)) return false;
  const error = (body as { error: unknown }).error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

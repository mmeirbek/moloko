/**
 * Types shared between the API and the web app.
 *
 * `api.gen.ts` is generated from `../openapi.json` (exported from the FastAPI app).
 * Do not edit it by hand: run `npm run generate:types` after changing API schemas.
 */
import type { components, paths } from "./api.gen";

export type { components, paths };

type Schemas = components["schemas"];

export type ErrorResponse = Schemas["ErrorResponse"];
export type ErrorBody = Schemas["ErrorBody"];
export type UserOut = Schemas["UserOut"];
export type SessionOut = Schemas["SessionOut"];
export type MeResponse = Schemas["MeResponse"];
export type LoginRequest = Schemas["LoginRequest"];
export type CsrfResponse = Schemas["CsrfResponse"];
export type HealthResponse = Schemas["HealthResponse"];

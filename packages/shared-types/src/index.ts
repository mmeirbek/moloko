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

// Sprint 2 — chat, providers, models
export type ConversationOut = Schemas["ConversationOut"];
export type ConversationCreate = Schemas["ConversationCreate"];
export type ConversationUpdate = Schemas["ConversationUpdate"];
export type MessageOut = Schemas["MessageOut"];
export type MessageCreate = Schemas["MessageCreate"];
export type CancelResult = Schemas["CancelResult"];
export type ConversationPage = Schemas["Page_ConversationOut_"];
export type MessagePage = Schemas["Page_MessageOut_"];
export type ProviderOut = Schemas["ProviderOut"];
export type ProviderCreate = Schemas["ProviderCreate"];
export type ProviderUpdate = Schemas["ProviderUpdate"];
export type ProviderTestResult = Schemas["ProviderTestResult"];
export type SyncModelsResult = Schemas["SyncModelsResult"];
export type ModelOut = Schemas["ModelOut"];
export type ModelCreate = Schemas["ModelCreate"];
export type ModelUpdate = Schemas["ModelUpdate"];

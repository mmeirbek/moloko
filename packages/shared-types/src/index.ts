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
export type ProfileUpdate = Schemas["ProfileUpdate"];
export type SessionSettingsOut = Schemas["SessionSettingsOut"];
export type SessionSettingsUpdate = Schemas["SessionSettingsUpdate"];
export type LoginRequest = Schemas["LoginRequest"];
export type CsrfResponse = Schemas["CsrfResponse"];
export type HealthResponse = Schemas["HealthResponse"];
// Passkeys (sign in with Face ID / Touch ID)
export type PasskeyOut = Schemas["PasskeyOut"];
export type PasskeyListOut = Schemas["PasskeyListOut"];
export type PasskeyOptionsOut = Schemas["PasskeyOptionsOut"];
export type PasskeyRegisterVerify = Schemas["PasskeyRegisterVerify"];
export type PasskeyRename = Schemas["PasskeyRename"];
export type PasskeyLoginVerify = Schemas["PasskeyLoginVerify"];
export type PasswordConfirm = Schemas["PasswordConfirm"];

// Sprint 2 — chat, providers, models
export type ConversationOut = Schemas["ConversationOut"];
export type ConversationCreate = Schemas["ConversationCreate"];
export type ConversationUpdate = Schemas["ConversationUpdate"];
export type MessageOut = Schemas["MessageOut"];
export type MessageCreate = Schemas["MessageCreate"];
export type CancelResult = Schemas["CancelResult"];
export type ConversationPage = Schemas["Page_ConversationOut_"];
// Chats never forget: the summary of older messages, recall from earlier chats and work
export type ConversationSummaryOut = Schemas["ConversationSummaryOut"];
export type RecalledSourceOut = Schemas["RecalledSourceOut"];
export type MessagePage = Schemas["Page_MessageOut_"];
export type FreeProviderOut = Schemas["FreeProviderOut"];
export type CodexStatusOut = Schemas["CodexStatusOut"];
export type ProviderOut = Schemas["ProviderOut"];
export type ProviderCreate = Schemas["ProviderCreate"];
export type ProviderUpdate = Schemas["ProviderUpdate"];
export type ProviderTestResult = Schemas["ProviderTestResult"];
export type SyncModelsResult = Schemas["SyncModelsResult"];
export type ModelOut = Schemas["ModelOut"];
export type ModelCreate = Schemas["ModelCreate"];
export type ModelUpdate = Schemas["ModelUpdate"];

// Sprint 3 — agents, tasks, runs, events
export type AgentOut = Schemas["AgentOut"];
export type AgentTemplateOut = Schemas["AgentTemplateOut"];
export type AgentFromTemplate = Schemas["AgentFromTemplate"];
export type AgentRestore = Schemas["AgentRestore"];
export type AgentFullAccessUpdate = Schemas["AgentFullAccessUpdate"];
export type FullAccessForAllOut = Schemas["FullAccessForAllOut"];
export type SaveAsTemplate = Schemas["SaveAsTemplate"];
export type AgentBudgetOut = Schemas["AgentBudgetOut"];
export type AgentCreate = Schemas["AgentCreate"];
export type AgentUpdate = Schemas["AgentUpdate"];
export type AgentRunRequest = Schemas["AgentRunRequest"];
export type StartedRun = Schemas["StartedRun"];
export type RunOut = Schemas["RunOut"];
export type TaskOut = Schemas["TaskOut"];
export type TaskFileOut = Schemas["TaskFileOut"];
export type TaskCreate = Schemas["TaskCreate"];
export type TaskUpdate = Schemas["TaskUpdate"];
export type TaskDetail = Schemas["TaskDetail"];
export type TaskPage = Schemas["Page_TaskOut_"];
export type EventOut = Schemas["EventOut"];
export type SystemState = Schemas["SystemState"];
export type StopAllResult = Schemas["StopAllResult"];

export type * from "./events";

// Sprint 4 — orchestrated runs
export type RunCreate = Schemas["RunCreate"];
export type RunTree = Schemas["RunTree"];
export type AgentMessageOut = Schemas["AgentMessageOut"];
// Agents talking directly (agent_ask / agent_tell): contacts and the agent's correspondence
export type AgentContacts = Schemas["AgentContacts"];
export type AgentMessageItem = Schemas["AgentMessageItem"];
export type AgentMessagePage = Schemas["Page_AgentMessageItem_"];
export type HandoffRequest = Schemas["HandoffRequest"];

// Sprint 6 — autonomous agents, memory
export type AgentLimits = Schemas["AgentLimits"];
export type MemorySettings = Schemas["MemorySettings"];
export type MemoryType = MemoryCreate["memory_type"];
export type MemoryOut = Schemas["MemoryOut"];
export type MemoryCreate = Schemas["MemoryCreate"];
export type MemoryUpdate = Schemas["MemoryUpdate"];
export type MemoryRevisionOut = Schemas["MemoryRevisionOut"];
export type MemoryContextOut = Schemas["MemoryContextOut"];
export type SystemLimits = Schemas["SystemLimits"];

// Sprint 7 — tools, approvals, integrations, workspaces, audit
export type ToolOut = Schemas["ToolOut"];
export type ToolUpdate = Schemas["ToolUpdate"];
export type ApprovalOut = Schemas["ApprovalOut"];
export type ToolCallOut = Schemas["ToolCallOut"];
export type GitHubIntegrationOut = Schemas["GitHubIntegrationOut"];
export type GitHubIntegrationUpdate = Schemas["GitHubIntegrationUpdate"];
export type IntegrationsStatus = Schemas["IntegrationsStatus"];
export type McpServerOut = Schemas["McpServerOut"];
export type McpServerCreate = Schemas["McpServerCreate"];
export type McpServerUpdate = Schemas["McpServerUpdate"];
export type WorkspaceOut = Schemas["WorkspaceOut"];
export type WorkspaceEntry = Schemas["WorkspaceEntry"];
export type WorkspaceFileContent = Schemas["WorkspaceFileContent"];
export type AuditOut = Schemas["AuditOut"];
export type AuditPage = Schemas["AuditPage"];

// Sprint 8 — chat attachments
export type AttachmentOut = Schemas["AttachmentOut"];
export type StorageStatus = Schemas["StorageStatus"];
export type CostSummary = Schemas["CostSummary"];
export type BudgetIn = Schemas["BudgetIn"];
export type BudgetOut = Schemas["BudgetOut"];
export type SearchOut = Schemas["SearchOut"];
export type SearchHitOut = Schemas["SearchHitOut"];
export type SearchStatus = Schemas["SearchStatus"];
export type AiServicesOut = Schemas["AiServicesOut"];
export type AiServicesIn = Schemas["AiServicesIn"];

// Scheduled tasks (owner request)
export type ScheduleOut = Schemas["ScheduleOut"];
export type ScheduleList = Schemas["ScheduleList"];
export type ScheduleCreate = Schemas["ScheduleCreate"];
export type ScheduleUpdate = Schemas["ScheduleUpdate"];
export type ScheduleStarted = Schemas["ScheduleStarted"];
export type SchedulePreview = Schemas["SchedulePreview"];
export type SchedulePreviewIn = Schemas["SchedulePreviewIn"];
export type RecurrenceIn = Schemas["RecurrenceIn"];
export type RecurrenceOut = Schemas["RecurrenceOut"];

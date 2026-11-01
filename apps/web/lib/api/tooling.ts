import type {
  ApprovalOut,
  AuditPage,
  GitHubIntegrationOut,
  GitHubIntegrationUpdate,
  IntegrationsStatus,
  McpServerCreate,
  McpServerOut,
  McpServerUpdate,
  ToolCallOut,
  ToolOut,
  ToolUpdate,
  WorkspaceEntry,
  WorkspaceFileContent,
  WorkspaceOut,
} from "@moloko/shared-types";

import { api } from "./client";
import { API_BASE } from "./config";

export const toolingKeys = {
  tools: ["tools"] as const,
  status: ["integrations", "status"] as const,
  github: ["integrations", "github"] as const,
  mcp: ["mcp-servers"] as const,
  workspaces: ["workspaces"] as const,
  files: (ws: string, path: string) => ["workspaces", ws, "files", path] as const,
  file: (ws: string, path: string) => ["workspaces", ws, "file", path] as const,
  approvals: (status: string) => ["approvals", status] as const,
  taskCalls: (taskId: string) => ["tasks", "tool-calls", taskId] as const,
  taskWorkspace: (taskId: string) => ["tasks", "workspace", taskId] as const,
  audit: (action: string, outcome: string) => ["audit", action, outcome] as const,
};

export const listTools = (signal?: AbortSignal) => api.request<ToolOut[]>("/tools", { signal });
export const updateTool = (name: string, body: ToolUpdate) =>
  api.request<ToolOut>(`/tools/${name}`, { method: "PATCH", body });

export const listApprovals = (status: string, signal?: AbortSignal) =>
  api.request<ApprovalOut[]>(`/approvals?${new URLSearchParams(status ? { status } : {})}`, { signal });
export const resolveApproval = (id: string, action: "approve" | "reject" | "cancel-task") =>
  api.request<ApprovalOut>(`/approvals/${id}/${action}`, { method: "POST" });

export const integrationsStatus = (signal?: AbortSignal) =>
  api.request<IntegrationsStatus>("/integrations/status", { signal });
export const getGitHub = (signal?: AbortSignal) =>
  api.request<GitHubIntegrationOut>("/integrations/github", { signal });
export const putGitHub = (body: GitHubIntegrationUpdate) =>
  api.request<GitHubIntegrationOut>("/integrations/github", { method: "PUT", body });
export const testGitHub = () => api.request<GitHubIntegrationOut>("/integrations/github/test", { method: "POST" });

export const listMcpServers = (signal?: AbortSignal) => api.request<McpServerOut[]>("/mcp-servers", { signal });
export const addMcpServer = (body: McpServerCreate) =>
  api.request<McpServerOut>("/mcp-servers", { method: "POST", body });
export const addGitHubMcp = (body: { readonly: boolean; toolsets: string[] }) =>
  api.request<McpServerOut>("/mcp-servers/github", { method: "POST", body });
export const updateMcpServer = (id: string, body: McpServerUpdate) =>
  api.request<McpServerOut>(`/mcp-servers/${id}`, { method: "PATCH", body });
export const refreshMcpServer = (id: string) =>
  api.request<McpServerOut>(`/mcp-servers/${id}/refresh`, { method: "POST" });
export const deleteMcpServer = (id: string) => api.request<void>(`/mcp-servers/${id}`, { method: "DELETE" });

export const listWorkspaces = (kind?: "task" | "project", signal?: AbortSignal) =>
  api.request<WorkspaceOut[]>(`/workspaces?${new URLSearchParams(kind ? { kind } : {})}`, { signal });
export const createWorkspace = (name: string) =>
  api.request<WorkspaceOut>("/workspaces", { method: "POST", body: { name } });
export const workspaceFiles = (id: string, path: string, signal?: AbortSignal) =>
  api.request<WorkspaceEntry[]>(`/workspaces/${id}/files?${new URLSearchParams({ path })}`, { signal });
export const workspaceFile = (id: string, path: string, signal?: AbortSignal) =>
  api.request<WorkspaceFileContent>(`/workspaces/${id}/file?${new URLSearchParams({ path })}`, { signal });
export const taskWorkspace = (taskId: string, signal?: AbortSignal) =>
  api.request<WorkspaceOut | null>(`/tasks/${taskId}/workspace`, { signal });
export const taskToolCalls = (taskId: string, signal?: AbortSignal) =>
  api.request<ToolCallOut[]>(`/tasks/${taskId}/tool-calls`, { signal });

export function auditLog(action: string, outcome: string, cursor: string | null, signal?: AbortSignal) {
  const params = new URLSearchParams({ limit: "50" });
  if (action) params.set("action", action);
  if (outcome) params.set("outcome", outcome);
  if (cursor) params.set("cursor", cursor);
  return api.request<AuditPage>(`/audit?${params}`, { signal });
}

/** A screenshot or PDF in a workspace, served by the API (same origin). */
export const workspaceRawUrl = (workspaceId: string, path: string) =>
  `${API_BASE}/workspaces/${workspaceId}/raw?path=${encodeURIComponent(path)}`;


import { api } from "./client";
import { API_BASE } from "./config";

export const taskMarkdownUrl = (taskId: string) => `${API_BASE}/tasks/${taskId}/export.md`;

/** PDF of a task's result, printed on the server (sandbox browser, no network). */
export async function exportTaskPdf(taskId: string): Promise<Blob> {
  const response = await api.request<Response>(`/tasks/${taskId}/export.pdf`, { method: "POST", raw: true });
  return response.blob();
}

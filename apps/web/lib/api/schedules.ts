import type {
  ScheduleCreate,
  ScheduleList,
  ScheduleOut,
  SchedulePreview,
  SchedulePreviewIn,
  ScheduleStarted,
  ScheduleUpdate,
} from "@moloko/shared-types";

import { api } from "./client";

// Under the "tasks" prefix: task events (a scheduled task finished) refresh the list too.
export const scheduleKeys = {
  all: ["tasks", "schedules"] as const,
  detail: (id: string) => ["tasks", "schedules", id] as const,
  preview: (body: SchedulePreviewIn) => ["schedules-preview", body] as const,
};

export const listSchedules = (signal?: AbortSignal) => api.request<ScheduleList>("/schedules", { signal });
export const getSchedule = (id: string, signal?: AbortSignal) =>
  api.request<ScheduleOut>(`/schedules/${id}`, { signal });
export const createSchedule = (body: ScheduleCreate) =>
  api.request<ScheduleOut>("/schedules", { method: "POST", body });
export const updateSchedule = (id: string, body: ScheduleUpdate) =>
  api.request<ScheduleOut>(`/schedules/${id}`, { method: "PATCH", body });
export const deleteSchedule = (id: string) => api.request<void>(`/schedules/${id}`, { method: "DELETE" });
export const runScheduleNow = (id: string) =>
  api.request<ScheduleStarted>(`/schedules/${id}/run-now`, { method: "POST" });
/** The next runs of a rule as the server computes them (nothing is saved). */
export const previewSchedule = (body: SchedulePreviewIn, signal?: AbortSignal) =>
  api.request<SchedulePreview>("/schedules/preview", { method: "POST", body, signal });

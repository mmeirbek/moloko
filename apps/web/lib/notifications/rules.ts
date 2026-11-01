import type { EventEnvelope } from "@moloko/shared-types";

export type NotificationKind = "approval" | "taskDone" | "taskFailed";
export type NotificationPrefs = Record<NotificationKind, boolean> & { system: boolean };

export const DEFAULT_PREFS: NotificationPrefs = { approval: true, taskDone: true, taskFailed: true, system: false };
const KEY = "moloko.notifications";
const MAX_AGE_MS = 15 * 60_000; // replayed events older than this are not announced

export function loadPrefs(): NotificationPrefs {
  try {
    const raw = window.localStorage.getItem(KEY);
    return raw ? { ...DEFAULT_PREFS, ...(JSON.parse(raw) as Partial<NotificationPrefs>) } : DEFAULT_PREFS;
  } catch {
    return DEFAULT_PREFS;
  }
}

export function savePrefs(prefs: NotificationPrefs): void {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* private mode: preferences just don't persist */
  }
  cached = prefs;
  window.dispatchEvent(new Event(CHANGED));
}

// useSyncExternalStore plumbing (per-device preferences, also synced across tabs).
const CHANGED = "moloko:notification-prefs";
let cached: NotificationPrefs | null = null;

export function subscribePrefs(onChange: () => void): () => void {
  const handler = () => {
    cached = null;
    onChange();
  };
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", handler);
  };
}

export function prefsSnapshot(): NotificationPrefs {
  cached ??= loadPrefs();
  return cached;
}

export interface Notice {
  kind: NotificationKind;
  key: string; // one notice per thing (dedupe across tabs/replays)
  title: string;
  url: string;
  /** i18n params */
  subject: string;
}

/** Which events deserve the owner's attention. Pure: tested. */
export function noticeFor(event: EventEnvelope, now: number = Date.now()): Notice | null {
  if (event.timestamp && now - Date.parse(event.timestamp) > MAX_AGE_MS) return null;
  const p = event.payload as Record<string, unknown>;
  if (event.type === "approval.required") {
    const a = p.approval as { id: string; summary: string } | undefined;
    if (!a) return null;
    return { kind: "approval", key: `approval:${a.id}`, title: "approval", subject: a.summary, url: "/approvals" };
  }
  if (event.type === "task.completed" || event.type === "task.failed") {
    const task = p.task as { id: string; title: string; parent_task_id: string | null } | undefined;
    if (!task || task.parent_task_id) return null; // subtasks are part of a bigger job
    const done = event.type === "task.completed";
    return {
      kind: done ? "taskDone" : "taskFailed",
      key: `task:${task.id}:${event.type}`,
      title: done ? "taskDone" : "taskFailed",
      subject: task.title,
      url: `/tasks/${task.id}`,
    };
  }
  return null;
}

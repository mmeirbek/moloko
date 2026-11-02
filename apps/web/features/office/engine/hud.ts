/**
 * Progress over the agents' heads ("heads-up display"). Pure: tested, no Phaser.
 *
 * React derives one `AgentHud` per busy agent from the realtime store (task progress, the
 * run's step and latest message, pending approvals) and sends it over the bus; the scene
 * only draws it. Which statuses show a bar at all is decided in behavior.ts (`hud`).
 *
 * The latest message is untrusted model text: it is reduced to a few words of plain text
 * here (no markup, links, control or direction-override characters) before anything shows it.
 */
import { hudModeFor } from "./behavior";
import type { AgentHud } from "./bus";

/** Inner width of the bar in art pixels (the frame adds one pixel on each side). */
export const BAR_INNER = 14;
/** Words and letters of the activity label. */
export const ACTIVITY_WORDS = 4;
export const ACTIVITY_CHARS = 24;

const TERMINAL_TASK = new Set(["completed", "failed", "cancelled"]);
const BUSY_TASK = ["running", "waiting_approval", "waiting", "queued"];

/** The parts of the store this needs (structural, so the generated API types fit). */
export interface HudAgent {
  id: string;
  status: string;
  current_task_id: string | null;
}
export interface HudTask {
  id: string;
  status: string;
  progress: number;
  title: string;
  run_id: string | null;
  parent_task_id: string | null;
  agent_id: string | null;
}
export interface HudSource {
  tasks: Record<string, HudTask>;
  runs: Record<string, { steps: number }>;
  lastMessage: Record<string, { step: number; text: string }>;
  approvals: Record<string, { agent_id: string; status: string }>;
}
/** Localised captions (React passes next-intl messages). */
export interface HudWords {
  step: (step: number) => string;
  approval: string;
}

const DIRECTION_AND_INVISIBLE = /[\u0000-\u001f\u007f-\u009f­؜​-‏‪-‮⁠-⁩﻿]/g;
const PICTOGRAPHS = /[\p{Extended_Pictographic}\u{1f3fb}-\u{1f3ff}\u{fe0e}\u{fe0f}\u{20e3}]/gu;

/**
 * A few words of plain text from untrusted model text (or a task title): the first line /
 * sentence, without HTML, Markdown, links, emoji, control or bidi characters. null if
 * nothing readable is left.
 */
export function cleanActivity(
  text: unknown,
  { words = ACTIVITY_WORDS, chars = ACTIVITY_CHARS }: { words?: number; chars?: number } = {},
): string | null {
  if (typeof text !== "string") return null;
  let s = text.slice(0, 2000);
  s = s.replace(/```[\s\S]*?(```|$)/g, " "); // code blocks say nothing short
  s = s.replace(/<(script|style)\b[^>]*>[\s\S]*?(<\/\1\s*>|$)/gi, " "); // with their contents
  s = s.replace(/<\/?[a-z!?][^>]*>/gi, " "); // other HTML tags (a stray "<" goes below)
  s = s.replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1"); // [text](url) → text
  s = s.replace(/\b(?:https?|ftp|file|data|javascript):\S*/gi, " ");
  s = s.replace(/&(?:[a-z]+|#\d+|#x[0-9a-f]+);/gi, " "); // HTML entities
  s = s.replace(DIRECTION_AND_INVISIBLE, (ch) => (ch === "\n" ? "\n" : " "));
  s = s.replace(PICTOGRAPHS, " ");
  s = s.replace(/[*`#>|~\\{}[\]<]/g, " ");
  s = s.replace(/(^|\s)_+|_+(?=\s|$)/g, "$1");
  const line = s
    .split("\n")
    .map((l) => l.replace(/^\s*(?:[-+•·]|\d+[.)])\s+/, "").trim())
    .find((l) => /[\p{L}\p{N}]/u.test(l));
  if (!line) return null;
  // the first sentence, if the line goes on
  const sentence = line.split(/(?<=[.!?…])\s+/)[0]!.replace(/\s+/g, " ").trim();
  const all = sentence.split(" ").filter((w) => /[\p{L}\p{N}]/u.test(w));
  let out = all.slice(0, Math.max(1, words)).join(" ");
  let cut = all.length > words;
  if (out.length > chars) {
    out = out.slice(0, chars - 1);
    const space = out.lastIndexOf(" ");
    if (space > chars / 2) out = out.slice(0, space);
    cut = true;
  }
  // a cut ends in "…"; a whole one keeps "!" or "?" but not a trailing full stop or comma
  out = out.replace(cut ? /[\s,.:;!?…–—-]+$/u : /[\s,.:;–—-]+$/u, "");
  if (!/[\p{L}\p{N}]/u.test(out)) return null;
  return cut ? `${out}…` : out;
}

/**
 * The task's progress in % when it is known: from its subtasks (done / all — the same rule
 * as the server's scheduler, which updates the parent without an event of its own) or from
 * the task's own `progress` when that is above 0. null = unknown.
 */
export function taskPercent(task: HudTask, children: HudTask[]): number | null {
  const own = Number.isFinite(task.progress) ? task.progress : 0;
  const max = task.status === "completed" ? 100 : 99;
  if (children.length > 0) {
    const done = children.filter((c) => TERMINAL_TASK.has(c.status)).length;
    const fromChildren = Math.floor((done * 100) / children.length);
    return Math.max(0, Math.min(max, Math.max(own, fromChildren)));
  }
  if (own > 0) return Math.min(max, Math.round(own));
  return null;
}

/** Filled pixels of the bar for a percentage (never full before 100 %, never empty after 0 %). */
export function barFill(percent: number, width = BAR_INNER): number {
  if (!(percent > 0)) return 0;
  if (percent >= 100) return width;
  return Math.min(width - 1, Math.max(1, Math.round((width * percent) / 100)));
}

/** The agent's task: the one it reports, else its newest busy task in the store. */
function currentTask(agent: HudAgent, tasks: Record<string, HudTask>): HudTask | null {
  if (agent.current_task_id && tasks[agent.current_task_id]) return tasks[agent.current_task_id]!;
  let best: HudTask | null = null;
  for (const task of Object.values(tasks)) {
    if (task.agent_id !== agent.id || !BUSY_TASK.includes(task.status)) continue;
    if (!best || BUSY_TASK.indexOf(task.status) < BUSY_TASK.indexOf(best.status)) best = task;
  }
  return best;
}

/** One agent's HUD, or null when nothing shows over its head. */
export function agentHud(
  agent: HudAgent,
  source: HudSource,
  words: HudWords,
  index: { children: Map<string, HudTask[]>; approving: Set<string> } = indexSource(source),
): AgentHud | null {
  const mode = hudModeFor(agent.status);
  const task = currentTask(agent, source.tasks);
  const approval = index.approving.has(agent.id) || task?.status === "waiting_approval";
  if (mode === "none" && !approval) return null;

  const percent = task ? taskPercent(task, index.children.get(task.id) ?? []) : null;
  const run = task?.run_id ? source.runs[task.run_id] : undefined;
  const message = task?.run_id ? source.lastMessage[task.run_id] : undefined;
  const step = Math.max(0, Math.floor(Math.max(message?.step ?? 0, run?.steps ?? 0)));
  const progress = percent !== null ? `${percent}%` : step > 0 ? words.step(step) : null;
  return {
    percent,
    tag: approval ? words.approval : progress,
    activity: cleanActivity(message?.text) ?? cleanActivity(task?.title),
    tone: approval ? "approval" : mode === "frozen" ? "paused" : "work",
  };
}

function indexSource(source: HudSource): { children: Map<string, HudTask[]>; approving: Set<string> } {
  const children = new Map<string, HudTask[]>();
  for (const task of Object.values(source.tasks)) {
    if (!task.parent_task_id) continue;
    const list = children.get(task.parent_task_id) ?? [];
    list.push(task);
    children.set(task.parent_task_id, list);
  }
  const approving = new Set<string>();
  for (const approval of Object.values(source.approvals)) {
    if (approval.status === "pending") approving.add(approval.agent_id);
  }
  return { children, approving };
}

/** HUDs of the shown agents, by id (agents with nothing to show are left out). */
export function officeHud(agents: HudAgent[], source: HudSource, words: HudWords): Record<string, AgentHud> {
  const index = indexSource(source);
  const out: Record<string, AgentHud> = {};
  for (const agent of agents) {
    const hud = agentHud(agent, source, words, index);
    if (hud) out[agent.id] = hud;
  }
  return out;
}

/** The caption the scene draws: the short tag, plus what it is doing for the focused agent. */
export function hudText(hud: AgentHud | null, focused: boolean): string | null {
  if (!hud) return null;
  const lines = focused ? [hud.tag, hud.activity] : [hud.tag];
  const text = lines.filter((line): line is string => !!line).join("\n");
  return text || null;
}

import { DEFAULT_GROUPS } from "./agents/defaults.js";
import { emit } from "./bus.js";
import {
  all,
  get,
  run,
  type GroupRow,
  type MessageKind,
  type MessageRow,
  type QuestionRow,
  type RunRow,
  type SubagentRow,
  type TaskRow,
  type TaskStatus,
} from "./db.js";

// ---------- Настройки ----------

export function getSetting(key: string): string | undefined {
  return get<{ value: string }>("SELECT value FROM settings WHERE key = ?", key)?.value;
}

export function setSetting(key: string, value: string) {
  run("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", key, value);
}

// Пустая строка — модель по умолчанию для подписки/ключа (так решает сам Claude Code).
export function defaultModel(): string {
  return getSetting("default_model") ?? "";
}

// ---------- Отделы и субагенты ----------

export function seedOffice() {
  if (get<{ n: number }>("SELECT COUNT(*) AS n FROM groups")!.n > 0) return;
  DEFAULT_GROUPS.forEach((g, gi) => {
    run(
      "INSERT INTO groups (id, name, motto, color, lead_prompt, position) VALUES (?, ?, ?, ?, ?, ?)",
      g.id, g.name, g.motto, g.color, g.lead_prompt, gi,
    );
    g.subagents.forEach((s, si) => {
      run(
        `INSERT INTO subagents (id, group_id, name, role, description, prompt, web, files, position)
         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)`,
        s.id, g.id, s.name, s.role, s.description, s.prompt, s.web ? 1 : 0, s.files ? 1 : 0, si,
      );
    });
  });
}

export function listGroupRows(): GroupRow[] {
  return all<GroupRow>("SELECT * FROM groups ORDER BY position, created_at");
}

export function getGroup(id: string) {
  return get<GroupRow>("SELECT * FROM groups WHERE id = ?", id);
}

export function listSubagents(groupId?: string): SubagentRow[] {
  return groupId
    ? all<SubagentRow>("SELECT * FROM subagents WHERE group_id = ? ORDER BY position, rowid", groupId)
    : all<SubagentRow>("SELECT * FROM subagents ORDER BY group_id, position, rowid");
}

export function getSubagent(id: string) {
  return get<SubagentRow>("SELECT * FROM subagents WHERE id = ?", id);
}

export type GroupStatus = "idle" | "working" | "waiting" | "queued";

export interface GroupView extends GroupRow {
  status: GroupStatus;
  subagents: (SubagentRow & { run: Pick<RunRow, "id" | "status" | "description" | "activity"> | null })[];
  current_task: Pick<TaskRow, "id" | "title" | "status" | "started_at"> | null;
  queued: number;
  done_total: number;
  done_today: number;
}

export function groupView(group: GroupRow): GroupView {
  const current = get<TaskRow>(
    "SELECT * FROM tasks WHERE group_id = ? AND status IN ('working','waiting') ORDER BY id LIMIT 1",
    group.id,
  );
  const queued = get<{ n: number }>("SELECT COUNT(*) AS n FROM tasks WHERE group_id = ? AND status = 'queued'", group.id)!.n;
  const done = get<{ total: number; today: number }>(
    `SELECT COUNT(*) AS total, SUM(CASE WHEN finished_at >= date('now') THEN 1 ELSE 0 END) AS today
     FROM tasks WHERE group_id = ? AND status = 'done'`,
    group.id,
  )!;
  // Последний «выход» каждого субагента в текущей задаче — по нему рисуем, кто сейчас за столом.
  const runs = current ? all<RunRow>("SELECT * FROM runs WHERE task_id = ? ORDER BY id", current.id) : [];
  const subagents = listSubagents(group.id).map((s) => {
    const r = [...runs].reverse().find((x) => x.subagent_id === s.id);
    return { ...s, run: r ? { id: r.id, status: r.status, description: r.description, activity: r.activity } : null };
  });
  let status: GroupStatus = "idle";
  if (current) status = current.status === "waiting" ? "waiting" : "working";
  else if (queued) status = "queued";
  return {
    ...group,
    status,
    subagents,
    current_task: current ? { id: current.id, title: current.title, status: current.status, started_at: current.started_at } : null,
    queued,
    done_total: done.total,
    done_today: done.today ?? 0,
  };
}

export function listGroups(): GroupView[] {
  return listGroupRows().map(groupView);
}

export function emitGroup(id: string) {
  const g = getGroup(id);
  if (g) emit({ type: "group", group: groupView(g) });
}

// ---------- Задачи ----------

export function getTask(id: number) {
  return get<TaskRow>("SELECT * FROM tasks WHERE id = ?", id);
}

export function createTask(groupId: string, title: string, instructions: string): TaskRow {
  const res = run("INSERT INTO tasks (group_id, title, instructions) VALUES (?, ?, ?)", groupId, title, instructions);
  const task = getTask(Number(res.lastInsertRowid))!;
  emit({ type: "task", task });
  emitGroup(groupId);
  return task;
}

export function setTaskStatus(id: number, status: TaskStatus, result?: string) {
  const finished = status === "done" || status === "failed" || status === "cancelled";
  run(
    `UPDATE tasks SET status = ?,
       result = COALESCE(?, result),
       started_at = CASE WHEN ? = 'working' AND started_at IS NULL THEN datetime('now') ELSE started_at END,
       finished_at = CASE WHEN ? THEN datetime('now') ELSE finished_at END
     WHERE id = ?`,
    status, result ?? null, status, finished ? 1 : 0, id,
  );
  const task = getTask(id)!;
  emit({ type: "task", task });
  emitGroup(task.group_id);
  return task;
}

export function setTaskUsage(id: number, costUsd: number, turns: number) {
  run("UPDATE tasks SET cost_usd = ?, turns = ? WHERE id = ?", costUsd, turns, id);
  emit({ type: "task", task: getTask(id) });
}

export function spentTodayUsd(): number {
  return get<{ s: number | null }>("SELECT SUM(cost_usd) AS s FROM tasks WHERE created_at >= datetime('now', '-1 day')")!.s ?? 0;
}

// ---------- Выходы субагентов ----------

export function getRunByToolUse(taskId: number, toolUseId: string) {
  return get<RunRow>("SELECT * FROM runs WHERE task_id = ? AND tool_use_id = ?", taskId, toolUseId);
}

export function startRun(task: TaskRow, subagentId: string, toolUseId: string, description: string) {
  const existing = getRunByToolUse(task.id, toolUseId);
  if (existing) return existing;
  run("INSERT INTO runs (task_id, subagent_id, tool_use_id, description) VALUES (?, ?, ?, ?)", task.id, subagentId, toolUseId, description);
  const r = getRunByToolUse(task.id, toolUseId)!;
  emitGroup(task.group_id);
  return r;
}

export function updateRun(task: TaskRow, runId: number, patch: { status?: RunRow["status"]; activity?: string; summary?: string }) {
  run(
    `UPDATE runs SET status = COALESCE(?, status), activity = COALESCE(?, activity), summary = COALESCE(?, summary),
       finished_at = CASE WHEN ? IN ('done','failed') THEN datetime('now') ELSE finished_at END
     WHERE id = ?`,
    patch.status ?? null, patch.activity ?? null, patch.summary ?? null, patch.status ?? null, runId,
  );
  emitGroup(task.group_id);
}

export function finishOpenRuns(task: TaskRow, status: "done" | "failed") {
  run("UPDATE runs SET status = ?, finished_at = datetime('now') WHERE task_id = ? AND status = 'working'", status, task.id);
  emitGroup(task.group_id);
}

// ---------- Лента ----------

export function addMessage(input: { taskId?: number | null; groupId?: string | null; subagentId?: string | null; kind: MessageKind; text: string }) {
  const res = run(
    "INSERT INTO messages (task_id, group_id, subagent_id, kind, text) VALUES (?, ?, ?, ?, ?)",
    input.taskId ?? null, input.groupId ?? null, input.subagentId ?? null, input.kind, input.text,
  );
  const message = get<MessageRow>("SELECT * FROM messages WHERE id = ?", Number(res.lastInsertRowid))!;
  emit({ type: "message", message });
  return message;
}

// ---------- Вопросы боссу ----------

export function getQuestion(id: number) {
  return get<QuestionRow>("SELECT * FROM questions WHERE id = ?", id);
}

export function createQuestion(task: TaskRow, subagentId: string | null, question: string) {
  const res = run(
    "INSERT INTO questions (task_id, group_id, subagent_id, question) VALUES (?, ?, ?, ?)",
    task.id, task.group_id, subagentId, question,
  );
  const q = getQuestion(Number(res.lastInsertRowid))!;
  emit({ type: "question", question: q });
  return q;
}

export function answerQuestion(id: number, answer: string) {
  run("UPDATE questions SET answer = ?, answered_at = datetime('now') WHERE id = ?", answer, id);
  const q = getQuestion(id)!;
  emit({ type: "question", question: q });
  return q;
}

export function pendingQuestions() {
  return all<QuestionRow>("SELECT * FROM questions WHERE answer IS NULL ORDER BY id");
}

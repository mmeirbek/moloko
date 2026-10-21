import { DEFAULT_TEAM } from "./agents/defaults.js";
import { emit } from "./bus.js";
import { config } from "./config.js";
import {
  all,
  get,
  run,
  type AgentRow,
  type FileRow,
  type MessageKind,
  type MessageRow,
  type QuestionRow,
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

// Модель, выбранная в приложении, важнее переменной окружения MODEL.
export function defaultModel(): string {
  return getSetting("default_model") || config.defaultModel;
}

export function modelFor(agent: AgentRow): string {
  return agent.model || defaultModel();
}

// ---------- Агенты ----------

export type AgentStatus = "idle" | "working" | "waiting" | "queued";

export interface AgentView extends AgentRow {
  status: AgentStatus;
  current_task: Pick<TaskRow, "id" | "title" | "status"> | null;
  queued: number;
}

export function seedTeam() {
  const count = get<{ n: number }>("SELECT COUNT(*) AS n FROM agents")!.n;
  if (count > 0) return;
  DEFAULT_TEAM.forEach((a, i) => {
    run(
      `INSERT INTO agents (id, name, role, emoji, color, system_prompt, effort, web, can_delegate, position)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      a.id, a.name, a.role, a.emoji, a.color, a.system_prompt, a.effort, a.web ? 1 : 0, a.can_delegate ? 1 : 0, i,
    );
  });
}

export function listAgentRows(): AgentRow[] {
  return all<AgentRow>("SELECT * FROM agents ORDER BY position, created_at");
}

export function getAgent(id: string): AgentRow | undefined {
  return get<AgentRow>("SELECT * FROM agents WHERE id = ?", id);
}

export function agentView(agent: AgentRow): AgentView {
  const current = get<TaskRow>(
    "SELECT * FROM tasks WHERE agent_id = ? AND status IN ('working','waiting') ORDER BY id LIMIT 1",
    agent.id,
  );
  const queued = get<{ n: number }>(
    "SELECT COUNT(*) AS n FROM tasks WHERE agent_id = ? AND status = 'queued'",
    agent.id,
  )!.n;
  let status: AgentStatus = "idle";
  if (current) status = current.status === "waiting" ? "waiting" : "working";
  else if (queued > 0) status = "queued";
  return {
    ...agent,
    status,
    current_task: current ? { id: current.id, title: current.title, status: current.status } : null,
    queued,
  };
}

export function listAgents(): AgentView[] {
  return listAgentRows().map(agentView);
}

export function emitAgent(id: string) {
  const agent = getAgent(id);
  if (agent) emit({ type: "agent", agent: agentView(agent) });
}

// ---------- Задачи ----------

export function getTask(id: number): TaskRow | undefined {
  return get<TaskRow>("SELECT * FROM tasks WHERE id = ?", id);
}

export function createTask(input: {
  agentId: string;
  title: string;
  instructions: string;
  parentId?: number | null;
  createdBy: string;
}): TaskRow {
  const res = run(
    "INSERT INTO tasks (agent_id, parent_id, title, instructions, created_by) VALUES (?, ?, ?, ?, ?)",
    input.agentId, input.parentId ?? null, input.title, input.instructions, input.createdBy,
  );
  const task = getTask(Number(res.lastInsertRowid))!;
  emit({ type: "task", task });
  emitAgent(task.agent_id);
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
  emitAgent(task.agent_id);
  return task;
}

export function addTaskUsage(id: number, inputTokens: number, outputTokens: number, costUsd: number) {
  run(
    "UPDATE tasks SET input_tokens = input_tokens + ?, output_tokens = output_tokens + ?, cost_usd = cost_usd + ? WHERE id = ?",
    inputTokens, outputTokens, costUsd, id,
  );
  emit({ type: "task", task: getTask(id) });
}

export function spentTodayUsd(): number {
  return get<{ s: number | null }>(
    "SELECT SUM(cost_usd) AS s FROM tasks WHERE created_at >= datetime('now', '-1 day')",
  )!.s ?? 0;
}

// ---------- Сообщения (лента офиса) ----------

export function addMessage(input: { taskId?: number | null; agentId?: string | null; kind: MessageKind; text: string }) {
  const res = run(
    "INSERT INTO messages (task_id, agent_id, kind, text) VALUES (?, ?, ?, ?)",
    input.taskId ?? null, input.agentId ?? null, input.kind, input.text,
  );
  const message = get<MessageRow>("SELECT * FROM messages WHERE id = ?", Number(res.lastInsertRowid))!;
  emit({ type: "message", message });
  return message;
}

// ---------- Вопросы боссу ----------

export function getQuestion(id: number) {
  return get<QuestionRow>("SELECT * FROM questions WHERE id = ?", id);
}

export function createQuestion(taskId: number, agentId: string, question: string) {
  const res = run("INSERT INTO questions (task_id, agent_id, question) VALUES (?, ?, ?)", taskId, agentId, question);
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

// ---------- Общий диск офиса ----------

export function normalizePath(p: string): string {
  const clean = p
    .replace(/\\/g, "/")
    .split("/")
    .filter((s) => s && s !== "." && s !== "..")
    .join("/");
  if (!clean) throw new Error("Пустой путь к файлу");
  if (clean.length > 200) throw new Error("Слишком длинный путь");
  return clean;
}

export function listFiles() {
  return all<Omit<FileRow, "content"> & { size: number }>(
    "SELECT path, updated_by, updated_at, length(content) AS size FROM files ORDER BY path",
  );
}

export function readFile(p: string) {
  return get<FileRow>("SELECT * FROM files WHERE path = ?", normalizePath(p));
}

export function writeFile(p: string, content: string, by: string) {
  const path = normalizePath(p);
  run(
    `INSERT INTO files (path, content, updated_by) VALUES (?, ?, ?)
     ON CONFLICT(path) DO UPDATE SET content = excluded.content, updated_by = excluded.updated_by, updated_at = datetime('now')`,
    path, content, by,
  );
  emit({ type: "file", path });
  return path;
}

export function deleteFile(p: string) {
  const path = normalizePath(p);
  run("DELETE FROM files WHERE path = ?", path);
  emit({ type: "file", path, deleted: true });
}

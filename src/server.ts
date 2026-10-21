import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express, { type Request, type Response } from "express";
import { z } from "zod";
import { MODELS } from "./agents/pricing.js";
import { cancelTask, pump, recoverAfterRestart } from "./agents/runner.js";
import { isAuthed, login, logout, requireAuth } from "./auth.js";
import { bus, emit, type OfficeEvent } from "./bus.js";
import { config } from "./config.js";
import { all, get, run, type MessageRow, type QuestionRow, type RunRow, type TaskRow } from "./db.js";
import { deleteDrive, listDrive, readDrive, writeDrive } from "./drive.js";
import {
  addMessage,
  answerQuestion,
  createTask,
  defaultModel,
  emitGroup,
  getGroup,
  getQuestion,
  getSetting,
  getSubagent,
  getTask,
  listGroups,
  initOffice,
  listSubagents,
  MAX_SUBAGENTS,
  pendingQuestions,
  setSetting,
  spentTodayUsd,
} from "./office.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(here, "..", "public");

initOffice();

const app = express();
app.set("trust proxy", 1);
app.use(express.json({ limit: "2mb" }));

app.get("/api/health", (_req, res) => res.json({ ok: true }));
app.post("/api/login", login);
app.post("/api/logout", logout);
app.get("/api/me", (req, res) => res.json({ authed: isAuthed(req) }));

const api = express.Router();
api.use(requireAuth);

function rateLimit() {
  try {
    return JSON.parse(getSetting("rate_limit") ?? "null");
  } catch {
    return null;
  }
}

// ---------- Общее состояние офиса ----------

api.get("/state", (_req, res) => {
  const streak = all<{ d: string }>(
    "SELECT DISTINCT date(finished_at) AS d FROM tasks WHERE status = 'done' AND finished_at IS NOT NULL ORDER BY d DESC LIMIT 60",
  ).map((r) => r.d);
  res.json({
    groups: listGroups(),
    tasks: all<TaskRow>("SELECT * FROM tasks ORDER BY id DESC LIMIT 100"),
    messages: all<MessageRow>("SELECT * FROM (SELECT * FROM messages ORDER BY id DESC LIMIT 150) ORDER BY id"),
    questions: pendingQuestions(),
    stats: {
      auth: config.auth,
      spent_today_usd: spentTodayUsd(),
      daily_budget_usd: config.dailyBudgetUsd,
      default_model: defaultModel(),
      max_parallel: config.maxParallel,
      rate_limit: rateLimit(),
      done_days: streak,
    },
    models: MODELS,
  });
});

// Живые обновления: браузер держит одно SSE-соединение и получает все события офиса.
api.get("/stream", (req: Request, res: Response) => {
  res.writeHead(200, {
    "Content-Type": "text/event-stream",
    "Cache-Control": "no-cache, no-transform",
    Connection: "keep-alive",
    "X-Accel-Buffering": "no",
  });
  res.write("retry: 3000\n\n");
  const send = (e: OfficeEvent) => res.write(`data: ${JSON.stringify(e)}\n\n`);
  const ping = setInterval(() => res.write(": ping\n\n"), 25_000);
  bus.on("office", send);
  req.on("close", () => {
    clearInterval(ping);
    bus.off("office", send);
  });
});

// ---------- Команды: одна задача или сразу пачка в разные отделы ----------

const Command = z.object({ text: z.string().trim().min(1).max(20_000), group_id: z.string() });

function dispatch(groupId: string, text: string): TaskRow {
  const group = getGroup(groupId);
  if (!group) throw new Error("Отдел не найден");
  const firstLine = text.split("\n")[0];
  const title = firstLine.length > 80 ? firstLine.slice(0, 77) + "…" : firstLine;
  const task = createTask(group.id, title, text);
  addMessage({ taskId: task.id, groupId: group.id, kind: "boss", text });
  return task;
}

api.post("/command", (req, res) => {
  const parsed = Command.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: "Пустая команда" });
  try {
    const task = dispatch(parsed.data.group_id, parsed.data.text);
    pump();
    res.json({ task });
  } catch (err) {
    res.status(400).json({ error: (err as Error).message });
  }
});

api.post("/commands", (req, res) => {
  const parsed = z.object({ items: z.array(Command).min(1).max(20) }).safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: "Нет задач для отправки" });
  try {
    const tasks = parsed.data.items.map((i) => dispatch(i.group_id, i.text));
    pump();
    res.json({ tasks });
  } catch (err) {
    res.status(400).json({ error: (err as Error).message });
  }
});

api.get("/tasks/:id", (req, res) => {
  const id = Number(req.params.id);
  const task = getTask(id);
  if (!task) return res.status(404).json({ error: "Задача не найдена" });
  res.json({
    task,
    messages: all<MessageRow>("SELECT * FROM messages WHERE task_id = ? ORDER BY id", id),
    runs: all<RunRow>("SELECT * FROM runs WHERE task_id = ? ORDER BY id", id),
    questions: all<QuestionRow>("SELECT * FROM questions WHERE task_id = ? ORDER BY id", id),
  });
});

api.post("/tasks/:id/cancel", (req, res) => {
  cancelTask(Number(req.params.id));
  res.json({ ok: true });
});

api.post("/questions/:id/answer", (req, res) => {
  const answer = typeof req.body?.answer === "string" ? req.body.answer.trim() : "";
  const q = getQuestion(Number(req.params.id));
  if (!q) return res.status(404).json({ error: "Вопрос не найден" });
  if (q.answer !== null) return res.status(409).json({ error: "На вопрос уже ответили" });
  if (!answer) return res.status(400).json({ error: "Пустой ответ" });
  addMessage({ taskId: q.task_id, groupId: q.group_id, subagentId: q.subagent_id, kind: "answer", text: answer });
  res.json({ question: answerQuestion(q.id, answer) });
});

api.delete("/messages", (_req, res) => {
  run("DELETE FROM messages");
  res.json({ ok: true });
});

// ---------- Диск офиса ----------

api.get("/files", (_req, res) => res.json({ files: listDrive() }));

api.get("/file", (req, res) => {
  try {
    const file = readDrive(String(req.query.path ?? ""));
    if (!file) return res.status(404).json({ error: "Файл не найден" });
    res.json({ file });
  } catch (err) {
    res.status(400).json({ error: (err as Error).message });
  }
});

api.put("/file", (req, res) => {
  const body = z.object({ path: z.string(), content: z.string() }).safeParse(req.body);
  if (!body.success) return res.status(400).json({ error: "Нужны path и content" });
  try {
    res.json({ path: writeDrive(body.data.path, body.data.content) });
  } catch (err) {
    res.status(400).json({ error: (err as Error).message });
  }
});

api.delete("/file", (req, res) => {
  try {
    deleteDrive(String(req.query.path ?? ""));
    res.json({ ok: true });
  } catch (err) {
    res.status(400).json({ error: (err as Error).message });
  }
});

// ---------- Настройки ----------

api.put("/settings", (req, res) => {
  const model = typeof req.body?.default_model === "string" ? req.body.default_model.trim() : "";
  if (model && !/^claude-[a-z0-9-]+$/.test(model)) return res.status(400).json({ error: "Некорректная модель" });
  setSetting("default_model", model);
  res.json({ default_model: defaultModel() });
});

// ---------- Отделы и субагенты ----------

const ModelField = z
  .string()
  .trim()
  .max(60)
  .regex(/^(claude-[a-z0-9-]+)?$/, "Некорректная модель")
  .nullable()
  .optional();

const GroupInput = z.object({
  name: z.string().trim().min(1).max(40),
  motto: z.string().trim().max(80).default(""),
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  lead_prompt: z.string().max(4000).default(""),
  model: ModelField,
});

const SubagentInput = z.object({
  name: z.string().trim().min(1).max(30),
  role: z.string().trim().min(1).max(50),
  description: z.string().trim().min(1).max(500),
  prompt: z.string().trim().min(1).max(20_000),
  web: z.boolean(),
  files: z.boolean(),
  model: ModelField,
});

function bad(res: Response, err: z.ZodError) {
  return res.status(400).json({ error: err.issues[0]?.message ?? "Некорректные данные" });
}

function hasActiveTasks(groupId: string) {
  return !!get("SELECT 1 FROM tasks WHERE group_id = ? AND status IN ('working','waiting') LIMIT 1", groupId);
}

api.post("/groups", (req, res) => {
  const p = GroupInput.safeParse(req.body);
  if (!p.success) return bad(res, p.error);
  const id = "g" + crypto.randomBytes(3).toString("hex");
  const position = (get<{ p: number | null }>("SELECT MAX(position) AS p FROM groups")!.p ?? 0) + 1;
  run(
    "INSERT INTO groups (id, name, motto, color, lead_prompt, model, position) VALUES (?, ?, ?, ?, ?, ?, ?)",
    id, p.data.name, p.data.motto, p.data.color, p.data.lead_prompt, p.data.model || null, position,
  );
  emitGroup(id);
  res.json({ group: getGroup(id) });
});

api.put("/groups/:id", (req, res) => {
  const g = getGroup(req.params.id);
  if (!g) return res.status(404).json({ error: "Отдел не найден" });
  const p = GroupInput.safeParse(req.body);
  if (!p.success) return bad(res, p.error);
  run(
    "UPDATE groups SET name = ?, motto = ?, color = ?, lead_prompt = ?, model = ? WHERE id = ?",
    p.data.name, p.data.motto, p.data.color, p.data.lead_prompt, p.data.model || null, g.id,
  );
  emitGroup(g.id);
  res.json({ group: getGroup(g.id) });
});

api.delete("/groups/:id", (req, res) => {
  const g = getGroup(req.params.id);
  if (!g) return res.status(404).json({ error: "Отдел не найден" });
  if (listSubagents(g.id).some((s) => s.source_file)) {
    return res.status(400).json({ error: "В отделе есть агенты из .claude/agents — сначала переведите их в другие отделы." });
  }
  for (const t of all<TaskRow>("SELECT * FROM tasks WHERE group_id = ? AND status IN ('queued','working','waiting')", g.id)) cancelTask(t.id);
  run("DELETE FROM groups WHERE id = ?", g.id);
  emit({ type: "group_deleted", id: g.id });
  res.json({ ok: true });
});

api.post("/groups/:id/subagents", (req, res) => {
  const g = getGroup(req.params.id);
  if (!g) return res.status(404).json({ error: "Отдел не найден" });
  if (listSubagents(g.id).length >= MAX_SUBAGENTS) {
    return res.status(400).json({ error: `В отделе максимум ${MAX_SUBAGENTS} субагента — так каждый остаётся узким специалистом.` });
  }
  if (hasActiveTasks(g.id)) return res.status(409).json({ error: "Отдел сейчас работает — дождитесь окончания задачи." });
  const p = SubagentInput.safeParse(req.body);
  if (!p.success) return bad(res, p.error);
  const id = `${g.id}-${crypto.randomBytes(2).toString("hex")}`;
  const position = (get<{ p: number | null }>("SELECT MAX(position) AS p FROM subagents WHERE group_id = ?", g.id)!.p ?? 0) + 1;
  const s = p.data;
  run(
    `INSERT INTO subagents (id, group_id, name, role, description, prompt, web, files, model, position)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    id, g.id, s.name, s.role, s.description, s.prompt, s.web ? 1 : 0, s.files ? 1 : 0, s.model || null, position,
  );
  emitGroup(g.id);
  res.json({ subagent: getSubagent(id) });
});

const FROM_FILE = "Этот агент описан в файле .claude/agents — правьте файл, офис подхватит изменения после перезапуска.";

// Перевести субагента в другой отдел — можно и для агентов из файлов.
api.put("/subagents/:id/group", (req, res) => {
  const s = getSubagent(req.params.id);
  const target = getGroup(String(req.body?.group_id ?? ""));
  if (!s || !target) return res.status(404).json({ error: "Не найдено" });
  if (s.group_id === target.id) return res.json({ subagent: s });
  if (listSubagents(target.id).length >= MAX_SUBAGENTS) return res.status(400).json({ error: `В отделе «${target.name}» уже ${MAX_SUBAGENTS} субагента.` });
  if (listSubagents(s.group_id).length <= 1) return res.status(400).json({ error: "В отделе должен остаться хотя бы один субагент." });
  if (hasActiveTasks(s.group_id) || hasActiveTasks(target.id)) return res.status(409).json({ error: "Один из отделов сейчас работает — дождитесь окончания задачи." });
  const position = (get<{ p: number | null }>("SELECT MAX(position) AS p FROM subagents WHERE group_id = ?", target.id)!.p ?? -1) + 1;
  run("UPDATE subagents SET group_id = ?, position = ? WHERE id = ?", target.id, position, s.id);
  emitGroup(s.group_id);
  emitGroup(target.id);
  res.json({ subagent: getSubagent(s.id) });
});

api.put("/subagents/:id", (req, res) => {
  const existing = getSubagent(req.params.id);
  if (!existing) return res.status(404).json({ error: "Субагент не найден" });
  if (existing.source_file) return res.status(400).json({ error: FROM_FILE });
  const p = SubagentInput.safeParse(req.body);
  if (!p.success) return bad(res, p.error);
  const s = p.data;
  run(
    "UPDATE subagents SET name = ?, role = ?, description = ?, prompt = ?, web = ?, files = ?, model = ? WHERE id = ?",
    s.name, s.role, s.description, s.prompt, s.web ? 1 : 0, s.files ? 1 : 0, s.model || null, existing.id,
  );
  emitGroup(existing.group_id);
  res.json({ subagent: getSubagent(existing.id) });
});

api.delete("/subagents/:id", (req, res) => {
  const s = getSubagent(req.params.id);
  if (!s) return res.status(404).json({ error: "Субагент не найден" });
  if (s.source_file) return res.status(400).json({ error: FROM_FILE + " Чтобы убрать агента, удалите его файл." });
  if (listSubagents(s.group_id).length <= 1) return res.status(400).json({ error: "В отделе должен остаться хотя бы один субагент." });
  if (hasActiveTasks(s.group_id)) return res.status(409).json({ error: "Отдел сейчас работает — дождитесь окончания задачи." });
  run("DELETE FROM subagents WHERE id = ?", s.id);
  emitGroup(s.group_id);
  res.json({ ok: true });
});

app.use("/api", api);

// ---------- Фронтенд ----------

app.use(express.static(publicDir, { extensions: ["html"], maxAge: config.isProd ? "1h" : 0 }));
app.get("*", (_req, res) => res.sendFile(path.join(publicDir, "index.html")));

recoverAfterRestart();

app.listen(config.port, () => {
  console.log(`🏢 Офис открыт на http://localhost:${config.port}`);
  const how = { subscription: "подписка Claude (CLAUDE_CODE_OAUTH_TOKEN)", api: "API-ключ (ANTHROPIC_API_KEY)", none: "НЕ ПОДКЛЮЧЕНО" }[config.auth];
  console.log(`🔌 Claude: ${how}`);
  if (!process.env.APP_PASSWORD) console.warn("⚠️  APP_PASSWORD не задан — используется пароль «dev».");
});

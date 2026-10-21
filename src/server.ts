import crypto from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";
import express, { type Request, type Response } from "express";
import { z } from "zod";
import { cancelTask, pump, recoverAfterRestart } from "./agents/runner.js";
import { isAuthed, login, logout, requireAuth } from "./auth.js";
import { bus, emit, type OfficeEvent } from "./bus.js";
import { config } from "./config.js";
import { all, get, run, type MessageRow, type QuestionRow, type TaskRow } from "./db.js";
import {
  addMessage,
  answerQuestion,
  createTask,
  deleteFile,
  emitAgent,
  getAgent,
  getQuestion,
  getTask,
  listAgentRows,
  listAgents,
  listFiles,
  pendingQuestions,
  readFile,
  seedTeam,
  spentTodayUsd,
  writeFile,
} from "./office.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.resolve(here, "..", "public");

seedTeam();

const app = express();
app.set("trust proxy", 1);
app.use(express.json({ limit: "2mb" }));

app.get("/api/health", (_req, res) => res.json({ ok: true }));
app.post("/api/login", login);
app.post("/api/logout", logout);
app.get("/api/me", (req, res) => res.json({ authed: isAuthed(req) }));

const api = express.Router();
api.use(requireAuth);

// ---------- Общее состояние офиса ----------

api.get("/state", (_req, res) => {
  res.json({
    agents: listAgents(),
    tasks: all<TaskRow>("SELECT * FROM tasks ORDER BY id DESC LIMIT 100"),
    messages: all<MessageRow>(
      "SELECT * FROM (SELECT * FROM messages WHERE kind != 'thinking' ORDER BY id DESC LIMIT 150) ORDER BY id",
    ),
    questions: pendingQuestions(),
    stats: {
      spent_today_usd: spentTodayUsd(),
      daily_budget_usd: config.dailyBudgetUsd,
      total_usd: get<{ s: number | null }>("SELECT SUM(cost_usd) AS s FROM tasks")!.s ?? 0,
      default_model: config.defaultModel,
    },
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

// ---------- Команды и задачи ----------

const CommandInput = z.object({
  text: z.string().trim().min(1).max(20_000),
  agent_id: z.string().optional(),
});

api.post("/command", (req, res) => {
  const parsed = CommandInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: "Пустая команда" });
  const { text, agent_id } = parsed.data;
  const agents = listAgentRows();
  const agent =
    (agent_id && agents.find((a) => a.id === agent_id)) || agents.find((a) => a.can_delegate) || agents[0];
  if (!agent) return res.status(400).json({ error: "В офисе нет ни одного сотрудника" });

  const firstLine = text.split("\n")[0];
  const title = firstLine.length > 80 ? firstLine.slice(0, 77) + "…" : firstLine;
  const task = createTask({ agentId: agent.id, title, instructions: text, createdBy: "boss" });
  addMessage({ taskId: task.id, agentId: agent.id, kind: "boss", text });
  pump();
  res.json({ task });
});

api.get("/tasks/:id", (req, res) => {
  const id = Number(req.params.id);
  const task = getTask(id);
  if (!task) return res.status(404).json({ error: "Задача не найдена" });
  res.json({
    task,
    messages: all<MessageRow>("SELECT * FROM messages WHERE task_id = ? ORDER BY id", id),
    subtasks: all<TaskRow>("SELECT * FROM tasks WHERE parent_id = ? ORDER BY id", id),
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
  addMessage({ taskId: q.task_id, agentId: q.agent_id, kind: "answer", text: answer });
  res.json({ question: answerQuestion(q.id, answer) });
});

api.delete("/messages", (_req, res) => {
  // Очищает только ленту; задачи и файлы остаются.
  run("DELETE FROM messages");
  res.json({ ok: true });
});

// ---------- Диск офиса ----------

api.get("/files", (_req, res) => res.json({ files: listFiles() }));

api.get("/file", (req, res) => {
  try {
    const file = readFile(String(req.query.path ?? ""));
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
    res.json({ path: writeFile(body.data.path, body.data.content, "boss") });
  } catch (err) {
    res.status(400).json({ error: (err as Error).message });
  }
});

api.delete("/file", (req, res) => {
  try {
    deleteFile(String(req.query.path ?? ""));
    res.json({ ok: true });
  } catch (err) {
    res.status(400).json({ error: (err as Error).message });
  }
});

// ---------- Команда ----------

const AgentInput = z.object({
  name: z.string().trim().min(1).max(40),
  role: z.string().trim().min(1).max(80),
  emoji: z.string().trim().min(1).max(16),
  color: z.string().regex(/^#[0-9a-fA-F]{6}$/),
  system_prompt: z.string().max(20_000),
  model: z.string().trim().max(60).nullable().optional(),
  effort: z.enum(["low", "medium", "high", "xhigh", "max"]),
  web: z.boolean(),
  can_delegate: z.boolean(),
});

api.post("/agents", (req, res) => {
  const parsed = AgentInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0]?.message ?? "Некорректные данные" });
  const a = parsed.data;
  const id = "a_" + crypto.randomBytes(3).toString("hex");
  const position = (get<{ p: number | null }>("SELECT MAX(position) AS p FROM agents")!.p ?? 0) + 1;
  run(
    `INSERT INTO agents (id, name, role, emoji, color, system_prompt, model, effort, web, can_delegate, position)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    id, a.name, a.role, a.emoji, a.color, a.system_prompt, a.model || null, a.effort, a.web ? 1 : 0, a.can_delegate ? 1 : 0, position,
  );
  emitAgent(id);
  res.json({ agent: getAgent(id) });
});

api.put("/agents/:id", (req, res) => {
  const existing = getAgent(req.params.id);
  if (!existing) return res.status(404).json({ error: "Сотрудник не найден" });
  const parsed = AgentInput.safeParse(req.body);
  if (!parsed.success) return res.status(400).json({ error: parsed.error.issues[0]?.message ?? "Некорректные данные" });
  const a = parsed.data;
  run(
    `UPDATE agents SET name = ?, role = ?, emoji = ?, color = ?, system_prompt = ?, model = ?, effort = ?, web = ?, can_delegate = ?
     WHERE id = ?`,
    a.name, a.role, a.emoji, a.color, a.system_prompt, a.model || null, a.effort, a.web ? 1 : 0, a.can_delegate ? 1 : 0, existing.id,
  );
  emitAgent(existing.id);
  res.json({ agent: getAgent(existing.id) });
});

api.delete("/agents/:id", (req, res) => {
  const agent = getAgent(req.params.id);
  if (!agent) return res.status(404).json({ error: "Сотрудник не найден" });
  const active = all<TaskRow>(
    "SELECT * FROM tasks WHERE agent_id = ? AND status IN ('queued','working','waiting')",
    agent.id,
  );
  for (const t of active) cancelTask(t.id);
  run("DELETE FROM agents WHERE id = ?", agent.id);
  emit({ type: "agent_deleted", id: agent.id });
  res.json({ ok: true });
});

app.use("/api", api);

// ---------- Фронтенд ----------

app.use(express.static(publicDir, { extensions: ["html"], maxAge: config.isProd ? "1h" : 0 }));
app.get("*", (_req, res) => res.sendFile(path.join(publicDir, "index.html")));

recoverAfterRestart();

app.listen(config.port, () => {
  console.log(`🏢 Офис открыт на http://localhost:${config.port}`);
  if (!process.env.ANTHROPIC_API_KEY) console.warn("⚠️  ANTHROPIC_API_KEY не задан — агенты не смогут работать.");
  if (!process.env.APP_PASSWORD) console.warn("⚠️  APP_PASSWORD не задан — используется пароль «dev».");
});


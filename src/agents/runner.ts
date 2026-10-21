import Anthropic from "@anthropic-ai/sdk";
import { bus, type OfficeEvent } from "../bus.js";
import { config } from "../config.js";
import { all, run, type AgentRow, type QuestionRow, type TaskRow } from "../db.js";
import {
  addMessage,
  addTaskUsage,
  answerQuestion,
  createQuestion,
  createTask,
  emitAgent,
  getAgent,
  getTask,
  listAgentRows,
  listFiles,
  modelFor,
  readFile,
  setTaskStatus,
  spentTodayUsd,
  writeFile,
} from "../office.js";
import { estimateCostUsd, isHaiku } from "./pricing.js";
import { buildTools, inputs, isToolName } from "./tools.js";

const client = new Anthropic();

const FINISHED = new Set(["done", "failed", "cancelled"]);

// Задачи, которые сейчас выполняются: по ним можно нажать «Стоп».
const running = new Map<number, AbortController>();
const busyAgents = new Set<string>();

// ---------- Ограничение параллельных запросов к API ----------
// Слот занимается только на время запроса к модели. Агент, который ждёт коллегу или ответ босса,
// слот не держит — поэтому менеджер с тремя поручениями не может заблокировать сам себя.

let inFlight = 0;
const slotWaiters: (() => void)[] = [];

async function withSlot<T>(fn: () => Promise<T>): Promise<T> {
  if (inFlight >= config.maxParallel) await new Promise<void>((r) => slotWaiters.push(r));
  inFlight++;
  try {
    return await fn();
  } finally {
    inFlight--;
    slotWaiters.shift()?.();
  }
}

// ---------- Ожидание событий ----------

function waitFor<T>(check: () => T | undefined, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    const ready = check();
    if (ready !== undefined) return resolve(ready);
    const onEvent = (_e: OfficeEvent) => {
      const value = check();
      if (value !== undefined) {
        cleanup();
        resolve(value);
      }
    };
    const onAbort = () => {
      cleanup();
      reject(new CancelledError());
    };
    const cleanup = () => {
      bus.off("office", onEvent);
      signal.removeEventListener("abort", onAbort);
    };
    bus.on("office", onEvent);
    signal.addEventListener("abort", onAbort, { once: true });
  });
}

class CancelledError extends Error {
  constructor() {
    super("Задача отменена");
  }
}

// ---------- Очередь ----------

export function pump() {
  const queued = all<TaskRow>("SELECT * FROM tasks WHERE status = 'queued' ORDER BY id");
  for (const task of queued) {
    if (busyAgents.has(task.agent_id)) continue;
    const agent = getAgent(task.agent_id);
    if (!agent) {
      setTaskStatus(task.id, "failed", "Сотрудник удалён из команды");
      continue;
    }
    if (spentTodayUsd() >= config.dailyBudgetUsd) {
      setTaskStatus(task.id, "failed", `Дневной лимит расходов ($${config.dailyBudgetUsd}) исчерпан. Поднимите DAILY_BUDGET_USD или подождите.`);
      addMessage({ taskId: task.id, agentId: agent.id, kind: "system", text: "⛔ Дневной лимит расходов исчерпан — задача не запущена." });
      continue;
    }
    void runTask(task, agent);
  }
}

export function cancelTask(id: number) {
  const task = getTask(id);
  if (!task || FINISHED.has(task.status)) return;
  // Сначала отменяем поручения, которые задача успела раздать.
  for (const sub of all<TaskRow>("SELECT * FROM tasks WHERE parent_id = ?", id)) cancelTask(sub.id);
  for (const q of all<QuestionRow>("SELECT * FROM questions WHERE task_id = ? AND answer IS NULL", id)) {
    answerQuestion(q.id, "(задача отменена)");
  }
  const controller = running.get(id);
  if (controller) controller.abort();
  else setTaskStatus(id, "cancelled", "Отменено боссом");
}

// После перезапуска сервера незавершённые задачи «повисли» бы навсегда — честно помечаем их.
export function recoverAfterRestart() {
  for (const t of all<TaskRow>("SELECT * FROM tasks WHERE status IN ('working','waiting')")) {
    setTaskStatus(t.id, "failed", "Прервано перезапуском сервера. Отправьте задачу ещё раз.");
  }
  for (const t of all<TaskRow>("SELECT * FROM tasks WHERE status = 'queued' AND parent_id IS NOT NULL")) {
    setTaskStatus(t.id, "cancelled", "Родительская задача прервана перезапуском сервера");
  }
  run("UPDATE questions SET answer = '(сервер перезапущен)', answered_at = datetime('now') WHERE answer IS NULL");
  pump();
}

async function runTask(task: TaskRow, agent: AgentRow) {
  busyAgents.add(agent.id);
  const controller = new AbortController();
  running.set(task.id, controller);
  setTaskStatus(task.id, "working");
  try {
    const result = await agentLoop(getTask(task.id)!, agent, controller.signal);
    setTaskStatus(task.id, "done", result);
    addMessage({ taskId: task.id, agentId: agent.id, kind: "agent", text: result });
  } catch (err) {
    if (controller.signal.aborted || err instanceof CancelledError) {
      setTaskStatus(task.id, "cancelled", "Отменено боссом");
      addMessage({ taskId: task.id, agentId: agent.id, kind: "system", text: `⏹ Задача «${task.title}» остановлена.` });
    } else {
      const text = describeError(err);
      console.error(`[task ${task.id}]`, err);
      setTaskStatus(task.id, "failed", text);
      addMessage({ taskId: task.id, agentId: agent.id, kind: "system", text: `⚠️ ${agent.name}: задача «${task.title}» не выполнена — ${text}` });
    }
  } finally {
    running.delete(task.id);
    busyAgents.delete(agent.id);
    emitAgent(agent.id);
    pump();
  }
}

function describeError(err: unknown): string {
  if (err instanceof Anthropic.AuthenticationError) return "неверный ANTHROPIC_API_KEY";
  if (err instanceof Anthropic.RateLimitError) return "превышен лимит запросов к API, попробуйте позже";
  if (err instanceof Anthropic.BadRequestError) return `API отклонил запрос: ${err.message}`;
  if (err instanceof Anthropic.APIError) return `ошибка API ${err.status ?? ""}: ${err.message}`;
  return err instanceof Error ? err.message : String(err);
}

// ---------- Промпты ----------

function systemPrompt(agent: AgentRow, team: AgentRow[]): string {
  const roster = team
    .map((a) => `- ${a.id}: ${a.name} — ${a.role}${a.id === agent.id ? " (это ты)" : ""}`)
    .join("\n");
  return `Ты — ${agent.name}, ${agent.role} в виртуальном офисе. Владелец офиса (босс) ставит задачи и читает результаты с телефона.

Команда офиса:
${roster}

У офиса есть общий диск (инструменты write_file / read_file / list_files) — это общая память команды между задачами. Объёмные результаты сохраняй туда, а в ответе указывай путь к файлу.
Финальный ответ — это то, что увидит постановщик задачи. Пиши его коротко и по делу, чтобы удобно читалось на телефоне; можно использовать простой markdown.
Отвечай на языке задачи (по умолчанию — по-русски).

${agent.system_prompt}`.trim();
}

function taskPrompt(task: TaskRow, agent: AgentRow): string {
  const from = task.created_by === "boss" ? "босса" : `коллеги ${getAgent(task.created_by)?.name ?? task.created_by}`;
  const parts = [`Задача #${task.id} от ${from}: ${task.title}`, "", task.instructions];

  // У каждой задачи свежий контекст, поэтому даём агенту короткую память о недавних поручениях босса.
  if (task.created_by === "boss") {
    const recent = all<TaskRow>(
      `SELECT * FROM tasks WHERE agent_id = ? AND created_by = 'boss' AND id < ? AND status = 'done'
       ORDER BY id DESC LIMIT 5`,
      agent.id, task.id,
    ).reverse();
    if (recent.length) {
      parts.push("", "Недавние задачи от босса (для контекста, если текущая на них ссылается):");
      for (const r of recent) parts.push(`- #${r.id} «${r.title}» → ${truncate(r.result ?? "", 600)}`);
    }
  }

  const files = listFiles();
  if (files.length) {
    parts.push("", "Файлы на общем диске:", ...files.slice(0, 60).map((f) => `- ${f.path}`));
  }
  return parts.join("\n");
}

function truncate(s: string, n: number) {
  const flat = s.replace(/\s+/g, " ").trim();
  return flat.length > n ? flat.slice(0, n) + "…" : flat;
}

// ---------- Цикл агента ----------

async function agentLoop(task: TaskRow, agent: AgentRow, signal: AbortSignal): Promise<string> {
  const team = listAgentRows();
  const model = modelFor(agent);
  const tools = buildTools(agent, task, team, model);
  // Если классификатор безопасности ложно сработает, API сам повторит запрос на запасной модели.
  // У Haiku серверного запасного варианта нет, поэтому параметр ему не передаём.
  const fallback = isHaiku(model)
    ? {}
    : { betas: ["server-side-fallback-2026-07-01"] as Anthropic.Beta.AnthropicBeta[], fallbacks: "default" as const };
  const system = systemPrompt(agent, team);
  const messages: Anthropic.Beta.BetaMessageParam[] = [{ role: "user", content: taskPrompt(task, agent) }];
  let jsonRetries = 0;

  for (let turn = 0; turn < config.maxTurns; turn++) {
    if (signal.aborted) throw new CancelledError();

    let message: Anthropic.Beta.BetaMessage;
    try {
      message = await withSlot(() =>
        client.beta.messages
          .stream(
            {
              model,
              max_tokens: 64000,
              system,
              tools,
              messages,
              thinking: { type: "adaptive", display: "summarized" },
              output_config: { effort: agent.effort },
              cache_control: { type: "ephemeral" },
              ...fallback,
            },
            { signal },
          )
          .finalMessage(),
      );
      jsonRetries = 0;
    } catch (err) {
      if (signal.aborted) throw new CancelledError();
      // С eager_input_streaming вход инструмента может прийти невалидным JSON — тогда просто повторяем ход.
      if (err instanceof Anthropic.APIError || jsonRetries++ >= 2) throw err;
      continue;
    }

    addTaskUsage(task.id, message.usage.input_tokens + (message.usage.cache_read_input_tokens ?? 0) + (message.usage.cache_creation_input_tokens ?? 0), message.usage.output_tokens, estimateCostUsd(model, message.usage));

    if (message.stop_reason === "refusal") {
      throw new Error("модель отказалась выполнять этот запрос");
    }

    const toolUses = message.content.filter((b): b is Anthropic.Beta.BetaToolUseBlock => b.type === "tool_use");
    const text = message.content
      .filter((b): b is Anthropic.Beta.BetaTextBlock => b.type === "text")
      .map((b) => b.text)
      .join("\n")
      .trim();

    logBlocks(task, agent, message, toolUses.length > 0 ? text : "");

    if (message.stop_reason === "pause_turn") {
      messages.push({ role: "assistant", content: message.content });
      continue;
    }

    if (toolUses.length === 0) {
      if (message.stop_reason === "max_tokens") return (text || "(пусто)") + "\n\n…(ответ обрезан по длине)";
      return text || "Готово.";
    }

    messages.push({ role: "assistant", content: message.content });

    if (message.stop_reason === "max_tokens") {
      // Вход инструмента обрезан — не выполняем его, а просим модель разбить работу на части.
      messages.push({
        role: "user",
        content: toolUses.map((t) => ({
          type: "tool_result" as const,
          tool_use_id: t.id,
          is_error: true,
          content: "Ответ обрезан по лимиту длины, инструмент не выполнен. Разбей содержимое на несколько файлов поменьше.",
        })),
      });
      continue;
    }

    // Все вызовы инструментов из одного ответа выполняем параллельно и возвращаем одним сообщением.
    const results = await Promise.all(toolUses.map((t) => executeTool(t, task, agent, signal)));
    messages.push({ role: "user", content: results });
  }

  throw new Error(`превышен лимит шагов (${config.maxTurns}) — задача оказалась слишком длинной`);
}

function logBlocks(task: TaskRow, agent: AgentRow, message: Anthropic.Beta.BetaMessage, interimText: string) {
  for (const block of message.content) {
    if (block.type === "thinking" && block.thinking.trim()) {
      addMessage({ taskId: task.id, agentId: agent.id, kind: "thinking", text: block.thinking.trim() });
    } else if (block.type === "server_tool_use") {
      const input = block.input as { query?: string; url?: string };
      if (block.name === "web_search") addMessage({ taskId: task.id, agentId: agent.id, kind: "tool", text: `🔎 Ищет в интернете: ${input.query ?? ""}` });
      if (block.name === "web_fetch") addMessage({ taskId: task.id, agentId: agent.id, kind: "tool", text: `🌐 Открывает страницу: ${input.url ?? ""}` });
    }
  }
  if (interimText) addMessage({ taskId: task.id, agentId: agent.id, kind: "thinking", text: interimText });
}

async function executeTool(
  call: Anthropic.Beta.BetaToolUseBlock,
  task: TaskRow,
  agent: AgentRow,
  signal: AbortSignal,
): Promise<Anthropic.Beta.BetaToolResultBlockParam> {
  const fail = (content: string): Anthropic.Beta.BetaToolResultBlockParam => ({
    type: "tool_result",
    tool_use_id: call.id,
    is_error: true,
    content,
  });
  const ok = (content: string): Anthropic.Beta.BetaToolResultBlockParam => ({
    type: "tool_result",
    tool_use_id: call.id,
    content,
  });

  if (!isToolName(call.name)) return fail(`Неизвестный инструмент ${call.name}`);
  const parsed = inputs[call.name].safeParse(call.input);
  if (!parsed.success) return fail(`Некорректные параметры: ${parsed.error.message}`);

  try {
    switch (call.name) {
      case "write_file": {
        const { path, content } = inputs.write_file.parse(call.input);
        const saved = writeFile(path, content, agent.id);
        addMessage({ taskId: task.id, agentId: agent.id, kind: "tool", text: `📝 Файл сохранён: ${saved}` });
        return ok(`Файл ${saved} сохранён (${content.length} символов).`);
      }
      case "read_file": {
        const { path } = inputs.read_file.parse(call.input);
        const file = readFile(path);
        if (!file) return fail(`Файл ${path} не найден`);
        addMessage({ taskId: task.id, agentId: agent.id, kind: "tool", text: `📖 Читает файл: ${file.path}` });
        return ok(file.content);
      }
      case "list_files": {
        const files = listFiles();
        return ok(files.length ? files.map((f) => `${f.path} (${f.size} симв., ${f.updated_at})`).join("\n") : "Диск пуст.");
      }
      case "ask_boss": {
        const { question } = inputs.ask_boss.parse(call.input);
        const q = createQuestion(task.id, agent.id, question);
        addMessage({ taskId: task.id, agentId: agent.id, kind: "question", text: question });
        setTaskStatus(task.id, "waiting");
        try {
          const answered = await waitFor(() => {
            const row = all<QuestionRow>("SELECT * FROM questions WHERE id = ?", q.id)[0];
            return row?.answer != null ? row : undefined;
          }, signal);
          return ok(`Ответ босса: ${answered.answer}`);
        } finally {
          if (!signal.aborted) setTaskStatus(task.id, "working");
        }
      }
      case "delegate_task": {
        const { agent_id, title, instructions } = inputs.delegate_task.parse(call.input);
        const colleague = getAgent(agent_id);
        if (!colleague || colleague.id === agent.id) return fail(`Нет такого коллеги: ${agent_id}`);
        const sub = createTask({ agentId: colleague.id, title, instructions, parentId: task.id, createdBy: agent.id });
        addMessage({ taskId: task.id, agentId: agent.id, kind: "tool", text: `👉 Поручение для: ${colleague.name} — ${title}` });
        pump();
        const finished = await waitFor(() => {
          const row = getTask(sub.id);
          return row && FINISHED.has(row.status) ? row : undefined;
        }, signal);
        if (finished.status === "done") return ok(`Результат (${colleague.name}, задача #${sub.id}):\n${finished.result}`);
        return fail(`Задача #${sub.id} (${colleague.name}) не выполнена: ${finished.result ?? finished.status}`);
      }
    }
  } catch (err) {
    if (err instanceof CancelledError) throw err;
    return fail(err instanceof Error ? err.message : String(err));
  }
}

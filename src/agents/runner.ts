import path from "node:path";
import {
  createSdkMcpServer,
  query,
  tool,
  type AgentDefinition,
  type HookCallback,
  type SDKMessage,
} from "@anthropic-ai/claude-agent-sdk";
import { z } from "zod";
import { bus, emit } from "../bus.js";
import { config } from "../config.js";
import { all, run, type GroupRow, type QuestionRow, type SubagentRow, type TaskRow } from "../db.js";
import { driveDir, insideDrive } from "../drive.js";
import {
  addMessage,
  answerQuestion,
  createQuestion,
  defaultModel,
  finishOpenRuns,
  getGroup,
  getQuestion,
  getRunByToolUse,
  getSubagent,
  getTask,
  listSubagents,
  setSetting,
  setTaskStatus,
  setTaskUsage,
  spentTodayUsd,
  startRun,
  updateRun,
} from "../office.js";

const FINISHED = new Set(["done", "failed", "cancelled"]);
const AGENT_TOOLS = new Set(["Agent", "Task"]);
const ASK_TOOL = "mcp__office__ask_boss";

// Задачи, которые сейчас выполняются: по ним работает кнопка «Стоп».
const running = new Map<number, AbortController>();
const busyGroups = new Set<string>();

class CancelledError extends Error {
  constructor() {
    super("Задача отменена");
  }
}

// ---------- Очередь: отделы работают параллельно, внутри отдела — по одной задаче ----------

export function pump() {
  const queued = all<TaskRow>("SELECT * FROM tasks WHERE status = 'queued' ORDER BY id");
  for (const task of queued) {
    if (busyGroups.size >= config.maxParallel) return;
    if (busyGroups.has(task.group_id)) continue;
    const group = getGroup(task.group_id);
    if (!group) {
      setTaskStatus(task.id, "failed", "Отдел удалён");
      continue;
    }
    if (config.auth === "none") {
      setTaskStatus(task.id, "failed", "Офис не подключён к Claude: задайте CLAUDE_CODE_OAUTH_TOKEN (подписка) или ANTHROPIC_API_KEY.");
      addMessage({ taskId: task.id, groupId: group.id, kind: "system", text: "⛔ Офис не подключён к Claude — см. «Отделы → Подключение»." });
      continue;
    }
    if (config.auth === "api" && spentTodayUsd() >= config.dailyBudgetUsd) {
      setTaskStatus(task.id, "failed", `Дневной лимит расходов ($${config.dailyBudgetUsd}) исчерпан.`);
      addMessage({ taskId: task.id, groupId: group.id, kind: "system", text: "⛔ Дневной лимит расходов исчерпан — задача не запущена." });
      continue;
    }
    void runTask(task, group);
  }
}

export function cancelTask(id: number) {
  const task = getTask(id);
  if (!task || FINISHED.has(task.status)) return;
  for (const q of all<QuestionRow>("SELECT * FROM questions WHERE task_id = ? AND answer IS NULL", id)) {
    answerQuestion(q.id, "(задача отменена)");
  }
  const controller = running.get(id);
  if (controller) controller.abort();
  else setTaskStatus(id, "cancelled", "Отменено боссом");
}

export function recoverAfterRestart() {
  for (const t of all<TaskRow>("SELECT * FROM tasks WHERE status IN ('working','waiting')")) {
    finishOpenRuns(t, "failed");
    setTaskStatus(t.id, "failed", "Прервано перезапуском сервера. Отправьте задачу ещё раз.");
  }
  run("UPDATE questions SET answer = '(сервер перезапущен)', answered_at = datetime('now') WHERE answer IS NULL");
  pump();
}

async function runTask(task: TaskRow, group: GroupRow) {
  busyGroups.add(group.id);
  const controller = new AbortController();
  running.set(task.id, controller);
  setTaskStatus(task.id, "working");
  addMessage({ taskId: task.id, groupId: group.id, kind: "system", text: `▶ «${group.name}» взялись за задачу «${task.title}»` });
  try {
    const result = await groupLoop(getTask(task.id)!, group, controller);
    finishOpenRuns(task, "done");
    setTaskStatus(task.id, "done", result);
    addMessage({ taskId: task.id, groupId: group.id, kind: "lead", text: result });
  } catch (err) {
    finishOpenRuns(task, "failed");
    if (controller.signal.aborted || err instanceof CancelledError) {
      setTaskStatus(task.id, "cancelled", "Отменено боссом");
      addMessage({ taskId: task.id, groupId: group.id, kind: "system", text: `⏹ «${task.title}» остановлена.` });
    } else {
      const text = err instanceof Error ? err.message : String(err);
      console.error(`[task ${task.id}]`, err);
      setTaskStatus(task.id, "failed", text);
      addMessage({ taskId: task.id, groupId: group.id, kind: "system", text: `⚠️ «${group.name}»: задача «${task.title}» не выполнена — ${text}` });
    }
  } finally {
    running.delete(task.id);
    busyGroups.delete(group.id);
    pump();
  }
}

// ---------- Промпты ----------

function leadPrompt(group: GroupRow, subs: SubagentRow[]): string {
  const roster = subs.map((s) => `- ${s.id}: ${s.name}, ${s.role}. ${s.description}`).join("\n");
  return `Ты — координатор отдела «${group.name}» в виртуальном офисе. Владелец офиса (босс) ставит задачи с телефона.
Специализация отдела: ${group.lead_prompt}

Твоя команда — субагенты. Вызывай их инструментом Agent, указывая subagent_type:
${roster}

Как ты работаешь:
1. Разбей задачу на части под специалистов и поручи каждую тому, кто сделает её лучше всех. Тяжёлую работу сам не делай.
2. Независимые части запускай параллельно, зависимые — по очереди. Субагент не видит эту переписку, поэтому пиши ему задание самодостаточно и передавай результаты предыдущих шагов.
3. Если без уточнения легко сделать не то — спроси босса через ask_boss. По мелочам не дёргай.
4. Итог для босса — коротко, по пунктам: что сделано, главный результат, пути к файлам. Его читают с телефона.

Текущая папка — общий диск офиса, босс видит эти файлы. Пиши по-русски, если задача не на другом языке.`;
}

function subagentPrompt(s: SubagentRow, group: GroupRow): string {
  return `Ты — ${s.name}, ${s.role} в отделе «${group.name}» виртуального офиса.

${s.prompt}

Общие правила: работаешь только с файлами в текущей папке (общий диск офиса, относительные пути). Возвращай результат так, чтобы координатор мог сразу его использовать. Пиши по-русски, если задача не на другом языке.`;
}

function taskPrompt(task: TaskRow): string {
  const parts = [`Задача #${task.id} от босса: ${task.title}`, "", task.instructions];
  const recent = all<TaskRow>(
    "SELECT * FROM tasks WHERE group_id = ? AND id < ? AND status = 'done' ORDER BY id DESC LIMIT 3",
    task.group_id, task.id,
  ).reverse();
  if (recent.length) {
    parts.push("", "Недавние задачи отдела (для контекста, если текущая на них ссылается):");
    for (const r of recent) parts.push(`- #${r.id} «${r.title}» → ${truncate(r.result ?? "", 500)}`);
  }
  return parts.join("\n");
}

function truncate(s: string, n: number) {
  const flat = s.replace(/\s+/g, " ").trim();
  return flat.length > n ? flat.slice(0, n) + "…" : flat;
}

function toolsFor(s: SubagentRow): string[] {
  return ["Read", "Glob", "Grep", ...(s.files ? ["Write", "Edit"] : []), ...(s.web ? ["WebSearch", "WebFetch"] : []), ASK_TOOL];
}

// Окружение процесса Claude Code: оставляем ровно один способ оплаты, чтобы случайно не платить не тем.
function claudeEnv(): Record<string, string | undefined> {
  const { ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, CLAUDE_CODE_OAUTH_TOKEN, APP_PASSWORD, SESSION_SECRET, ...base } = process.env;
  const env: Record<string, string | undefined> = {
    ...base,
    // Ответ босса может прийти через часы — не даём инструменту ask_boss отвалиться по таймауту.
    MCP_TOOL_TIMEOUT: String(24 * 60 * 60 * 1000),
    // Субагенты работают «на переднем плане»: иначе Claude Code уводит их в фон и обрывает ожидание ответа босса.
    CLAUDE_CODE_DISABLE_BACKGROUND_TASKS: "1",
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
  };
  if (config.auth === "subscription") env.CLAUDE_CODE_OAUTH_TOKEN = CLAUDE_CODE_OAUTH_TOKEN;
  if (config.auth === "api") env.ANTHROPIC_API_KEY = ANTHROPIC_API_KEY;
  return env;
}

// Файловые инструменты пускаем только внутрь диска офиса.
const FILE_TOOLS: Record<string, string[]> = {
  Read: ["file_path"],
  Write: ["file_path"],
  Edit: ["file_path"],
  Glob: ["path"],
  Grep: ["path"],
};

const guardFiles: HookCallback = async (input) => {
  if (input.hook_event_name !== "PreToolUse") return {};
  const keys = FILE_TOOLS[input.tool_name];
  if (!keys) return {};
  const toolInput = (input.tool_input ?? {}) as Record<string, unknown>;
  for (const k of keys) {
    const v = toolInput[k];
    if (typeof v === "string" && v && !insideDrive(v)) {
      return {
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: "Можно работать только с файлами на диске офиса (текущая папка).",
        },
      };
    }
  }
  return {};
};

// ---------- Цикл отдела ----------

async function groupLoop(task: TaskRow, group: GroupRow, controller: AbortController): Promise<string> {
  const subs = listSubagents(group.id);
  if (!subs.length) throw new Error("в отделе нет ни одного субагента");
  // На подписке модель по умолчанию выбирает сам Claude Code; по API-ключу берём Opus 5.5.
  const model = group.model || defaultModel() || (config.auth === "api" ? "claude-opus-5-5" : undefined);

  const agents: Record<string, AgentDefinition> = Object.fromEntries(
    subs.map((s) => [
      s.id,
      {
        description: `${s.name}, ${s.role}. ${s.description}`,
        prompt: subagentPrompt(s, group),
        tools: toolsFor(s),
        model: s.model || "inherit",
      } satisfies AgentDefinition,
    ]),
  );

  // Кто последним потянулся к ask_boss — так понимаем, какой субагент поднял руку.
  let lastAsker: string | null = null;

  const office = createSdkMcpServer({
    name: "office",
    tools: [
      tool(
        "ask_boss",
        "Задать вопрос боссу и дождаться ответа (он ответит с телефона, это может занять время). Только когда без ответа задачу не сделать правильно.",
        { question: z.string().describe("Короткий конкретный вопрос") },
        async ({ question }) => {
          const q = createQuestion(task, lastAsker, question);
          addMessage({ taskId: task.id, groupId: group.id, subagentId: lastAsker, kind: "question", text: question });
          setTaskStatus(task.id, "waiting");
          try {
            const answer = await waitForAnswer(q.id, controller.signal);
            return { content: [{ type: "text", text: `Ответ босса: ${answer}` }] };
          } finally {
            if (!controller.signal.aborted) setTaskStatus(task.id, "working");
          }
        },
      ),
    ],
  });

  const allTools = ["Agent", "Task", "Read", "Glob", "Grep", "Write", "Edit", "WebSearch", "WebFetch", ASK_TOOL];
  const q = query({
    prompt: taskPrompt(task),
    options: {
      cwd: driveDir,
      model,
      agents,
      systemPrompt: leadPrompt(group, subs),
      tools: allTools.filter((t) => t !== ASK_TOOL),
      allowedTools: allTools,
      disallowedTools: ["Bash"],
      // Без интерактивных вопросов: правки файлов разрешены, но хук guardFiles пускает только внутрь диска офиса.
      permissionMode: "acceptEdits",
      settingSources: [],
      mcpServers: { office },
      hooks: { PreToolUse: [{ hooks: [guardFiles] }] },
      maxTurns: config.maxTurns,
      abortController: controller,
      persistSession: false,
      env: claudeEnv(),
      stderr: (line) => {
        if (!config.isProd) process.stderr.write(`[claude ${task.id}] ${line}`);
      },
    },
  });

  let final: string | null = null;
  try {
    for await (const msg of q) {
      if (controller.signal.aborted) throw new CancelledError();
      const asker = handleMessage(task, group, msg);
      if (asker !== undefined) lastAsker = asker;
      if (msg.type === "result") {
        setTaskUsage(task.id, msg.total_cost_usd ?? 0, msg.num_turns ?? 0);
        if (msg.subtype === "success" && !msg.is_error) final = msg.result?.trim() || "Готово.";
        else {
          const errors = "errors" in msg ? msg.errors.join("; ") : msg.result;
          const why = msg.subtype === "error_max_turns" ? `превышен лимит шагов (${config.maxTurns})` : errors || msg.subtype;
          throw new Error(why);
        }
      }
    }
  } catch (err) {
    if (controller.signal.aborted) throw new CancelledError();
    if (final) return final; // SDK может бросить ошибку уже после итогового результата
    throw err;
  }
  if (final === null) throw new Error("Claude Code завершился без результата");
  return final;
}

function waitForAnswer(questionId: number, signal: AbortSignal): Promise<string> {
  return new Promise((resolve, reject) => {
    const check = () => {
      const row = getQuestion(questionId);
      if (row?.answer != null) {
        cleanup();
        resolve(row.answer);
      }
    };
    const onAbort = () => {
      cleanup();
      reject(new CancelledError());
    };
    const cleanup = () => {
      bus.off("office", check);
      signal.removeEventListener("abort", onAbort);
    };
    bus.on("office", check);
    signal.addEventListener("abort", onAbort, { once: true });
    check();
  });
}

// ---------- Разбор потока сообщений Claude Code ----------

type ContentBlock = { type: string; id?: string; name?: string; input?: Record<string, unknown>; text?: string; tool_use_id?: string; content?: unknown };

function subagentIdFor(group: GroupRow, type: unknown): string | null {
  if (typeof type !== "string") return null;
  const s = getSubagent(type);
  return s && s.group_id === group.id ? s.id : null;
}

function describeTool(name: string, input: Record<string, unknown> = {}): string | null {
  const p = typeof input.file_path === "string" ? path.relative(driveDir, path.resolve(driveDir, input.file_path)) : "";
  switch (name) {
    case "WebSearch": return `🔎 ищет: ${String(input.query ?? "").slice(0, 80)}`;
    case "WebFetch": return `🌐 читает сайт ${String(input.url ?? "").replace(/^https?:\/\//, "").slice(0, 60)}`;
    case "Write": return `📝 пишет файл ${p}`;
    case "Edit": return `✏️ правит ${p}`;
    case "Read": return `📖 читает ${p}`;
    case "Glob":
    case "Grep": return "🗂 смотрит файлы на диске";
    case ASK_TOOL: return "✋ задаёт вопрос боссу";
    default: return null;
  }
}

const SHORT_TOOL: Record<string, string> = {
  WebSearch: "ищет в интернете",
  WebFetch: "читает сайт",
  Write: "пишет файл",
  Edit: "правит файл",
  Read: "читает файл",
  Glob: "смотрит файлы",
  Grep: "ищет по файлам",
  [ASK_TOOL]: "ждёт ответа босса",
};

// Возвращает id субагента, если в этом сообщении он вызвал ask_boss (null — сам координатор), иначе undefined.
function handleMessage(task: TaskRow, group: GroupRow, msg: SDKMessage): string | null | undefined {
  let asker: string | null | undefined;

  if (msg.type === "rate_limit_event") {
    const info = { ...msg.rate_limit_info, at: Date.now() };
    setSetting("rate_limit", JSON.stringify(info));
    emit({ type: "limits", limits: info });
    return;
  }

  if (msg.type === "system") {
    const m = msg as { subtype: string; tool_use_id?: string; subagent_type?: string; description?: string; summary?: string; last_tool_name?: string; status?: string };
    if (m.subtype === "task_started" && m.tool_use_id) {
      const sid = subagentIdFor(group, m.subagent_type);
      if (sid) beginRun(task, group, sid, m.tool_use_id, m.description ?? "");
    } else if (m.subtype === "task_progress" && m.tool_use_id) {
      const r = getRunByToolUse(task.id, m.tool_use_id);
      const activity = m.summary || (m.last_tool_name ? SHORT_TOOL[m.last_tool_name] : undefined);
      if (r && activity) updateRun(task, r.id, { activity: truncate(activity, 90) });
    } else if (m.subtype === "task_notification" && m.tool_use_id) {
      const r = getRunByToolUse(task.id, m.tool_use_id);
      if (r && r.status === "working") endRun(task, group, r.id, r.subagent_id, m.status === "completed" ? "done" : "failed", m.summary ?? "");
    }
    return;
  }

  if (msg.type === "assistant") {
    const content = (msg.message?.content ?? []) as ContentBlock[];
    const parent = msg.parent_tool_use_id;
    const parentRun = parent ? getRunByToolUse(task.id, parent) : undefined;
    for (const block of content) {
      if (block.type !== "tool_use" || !block.name) continue;
      if (!parent && AGENT_TOOLS.has(block.name) && block.id) {
        const sid = subagentIdFor(group, block.input?.subagent_type);
        if (sid) beginRun(task, group, sid, block.id, String(block.input?.description ?? ""));
        continue;
      }
      if (block.name === ASK_TOOL) asker = parentRun?.subagent_id ?? null;
      const label = describeTool(block.name, block.input);
      if (parentRun) {
        updateRun(task, parentRun.id, { activity: SHORT_TOOL[block.name] ?? block.name });
        if (label) addMessage({ taskId: task.id, groupId: group.id, subagentId: parentRun.subagent_id, kind: "tool", text: label });
      } else if (label && block.name !== ASK_TOOL) {
        addMessage({ taskId: task.id, groupId: group.id, kind: "tool", text: label });
      }
    }
    return asker;
  }

  if (msg.type === "user" && !msg.parent_tool_use_id) {
    // Результат синхронного вызова субагента приходит как tool_result на вызов Agent.
    const content = msg.message?.content;
    if (!Array.isArray(content)) return;
    for (const block of content as ContentBlock[]) {
      if (block.type !== "tool_result" || !block.tool_use_id) continue;
      const r = getRunByToolUse(task.id, block.tool_use_id);
      if (!r || r.status !== "working") continue;
      const text = toolResultText(block.content);
      const meta = msg.tool_use_result as { status?: string } | undefined;
      // Субагент ушёл работать в фоне — итог придёт позже отдельным уведомлением.
      if (meta?.status === "async_launched" || /async_launched|Async agent launched|working in the background/i.test(text)) continue;
      endRun(task, group, r.id, r.subagent_id, "done", text);
    }
  }
  return asker;
}

function toolResultText(content: unknown): string {
  if (typeof content === "string") return content;
  if (Array.isArray(content)) return content.map((c) => (c && typeof c === "object" && "text" in c ? String(c.text) : "")).join("\n");
  return "";
}

function beginRun(task: TaskRow, group: GroupRow, subagentId: string, toolUseId: string, description: string) {
  if (getRunByToolUse(task.id, toolUseId)) return;
  startRun(task, subagentId, toolUseId, description || "задание от координатора");
  const s = getSubagent(subagentId);
  addMessage({ taskId: task.id, groupId: group.id, subagentId, kind: "tool", text: `👉 берётся: ${description}` });
}

function endRun(task: TaskRow, group: GroupRow, runId: number, subagentId: string, status: "done" | "failed", summary: string) {
  updateRun(task, runId, { status, summary: truncate(summary, 2000) });
  if (summary.trim()) {
    addMessage({ taskId: task.id, groupId: group.id, subagentId, kind: "subagent", text: truncate(summary, 1200) });
  }
}

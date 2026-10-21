import type Anthropic from "@anthropic-ai/sdk";
import { z } from "zod";
import type { AgentRow, TaskRow } from "../db.js";
import { isHaiku } from "./pricing.js";

// Схемы для проверки входа инструментов. С eager_input_streaming сервер не валидирует JSON сам,
// поэтому всё, что пришло от модели, проверяем здесь перед выполнением.
export const inputs = {
  delegate_task: z.object({
    agent_id: z.string(),
    title: z.string().min(1),
    instructions: z.string().min(1),
  }),
  ask_boss: z.object({ question: z.string().min(1) }),
  write_file: z.object({ path: z.string().min(1), content: z.string() }),
  read_file: z.object({ path: z.string().min(1) }),
  list_files: z.object({}),
};

export type ToolName = keyof typeof inputs;

export function isToolName(name: string): name is ToolName {
  return name in inputs;
}

export function buildTools(agent: AgentRow, task: TaskRow, team: AgentRow[], model: string): Anthropic.Beta.BetaToolUnion[] {
  const tools: Anthropic.Beta.BetaToolUnion[] = [];

  const colleagues = team.filter((a) => a.id !== agent.id);
  // Делегировать может только агент с правом делегирования и только в задаче верхнего уровня —
  // так исключаем бесконечные цепочки «ты мне — я тебе».
  if (agent.can_delegate && task.parent_id === null && colleagues.length > 0) {
    tools.push({
      name: "delegate_task",
      description:
        "Поручить задачу коллеге и дождаться результата. Возвращает итоговый ответ коллеги. " +
        "Несколько независимых поручений можно отправить параллельно, вызвав инструмент несколько раз в одном ответе. " +
        "Пиши инструкции так, чтобы коллега справился без доступа к этой переписке: цель, контекст, ожидаемый формат результата.",
      eager_input_streaming: true,
      input_schema: {
        type: "object",
        properties: {
          agent_id: {
            type: "string",
            enum: colleagues.map((a) => a.id),
            description: "id коллеги: " + colleagues.map((a) => `${a.id} — ${a.name}, ${a.role}`).join("; "),
          },
          title: { type: "string", description: "Короткое название задачи (до 80 символов)" },
          instructions: { type: "string", description: "Подробное описание задачи" },
        },
        required: ["agent_id", "title", "instructions"],
        additionalProperties: false,
      },
    });
  }

  tools.push(
    {
      name: "ask_boss",
      description:
        "Задать вопрос боссу и дождаться ответа (он ответит с телефона, это может занять время). " +
        "Используй, только когда без ответа невозможно сделать задачу правильно.",
      eager_input_streaming: true,
      input_schema: {
        type: "object",
        properties: { question: { type: "string", description: "Короткий конкретный вопрос" } },
        required: ["question"],
        additionalProperties: false,
      },
    },
    {
      name: "write_file",
      description:
        "Создать или перезаписать файл на общем диске офиса. Босс видит эти файлы в приложении. " +
        "Используй для объёмных результатов: отчётов, кода, текстов. Путь вида folder/name.md.",
      eager_input_streaming: true,
      input_schema: {
        type: "object",
        properties: {
          path: { type: "string" },
          content: { type: "string", description: "Полное содержимое файла" },
        },
        required: ["path", "content"],
        additionalProperties: false,
      },
    },
    {
      name: "read_file",
      description: "Прочитать файл с общего диска офиса.",
      eager_input_streaming: true,
      input_schema: {
        type: "object",
        properties: { path: { type: "string" } },
        required: ["path"],
        additionalProperties: false,
      },
    },
    {
      name: "list_files",
      description: "Список файлов на общем диске офиса.",
      eager_input_streaming: true,
      input_schema: { type: "object", properties: {}, additionalProperties: false },
    },
  );

  if (agent.web) {
    // Версии с динамической фильтрацией есть только у Opus/Sonnet; Haiku получает базовые.
    if (isHaiku(model)) {
      tools.push(
        { type: "web_search_20250305", name: "web_search", max_uses: 8 },
        { type: "web_fetch_20250910", name: "web_fetch", max_uses: 8 },
      );
    } else {
      tools.push(
        { type: "web_search_20260209", name: "web_search", max_uses: 8 },
        { type: "web_fetch_20260209", name: "web_fetch", max_uses: 8 },
      );
    }
  }

  return tools;
}

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parse } from "yaml";

// Субагенты описаны так же, как для Claude Code: .claude/agents/<name>.md с YAML-заголовком.
// Офис читает эти файлы при старте — один и тот же агент работает и в Claude Code, и в офисе.
const here = path.dirname(fileURLToPath(import.meta.url));
export const agentsDir = path.resolve(process.env.AGENTS_DIR ?? path.join(here, "..", "..", ".claude", "agents"));

export interface AgentFile {
  name: string;
  description: string;
  tools: string[] | null;
  model: string | null;
  prompt: string;
  file: string;
}

function toolList(raw: unknown): string[] | null {
  if (raw == null) return null;
  const list = Array.isArray(raw) ? raw : String(raw).split(",");
  const tools = list.map((t) => String(t).trim()).filter(Boolean);
  return tools.length ? tools : null;
}

export function readAgentFiles(): AgentFile[] {
  if (!fs.existsSync(agentsDir)) return [];
  const out: AgentFile[] = [];
  for (const entry of fs.readdirSync(agentsDir).sort()) {
    if (!entry.endsWith(".md")) continue;
    const file = path.join(agentsDir, entry);
    const text = fs.readFileSync(file, "utf8").replace(/^﻿/, "");
    const m = text.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/);
    if (!m) {
      console.warn(`⚠️  ${entry}: нет YAML-заголовка — пропускаю`);
      continue;
    }
    try {
      const meta = (parse(m[1]) ?? {}) as Record<string, unknown>;
      const name = String(meta.name ?? entry.replace(/\.md$/, "")).trim();
      if (!/^[a-z0-9][a-z0-9-]*$/.test(name)) throw new Error(`имя «${name}» должно быть из строчных латинских букв, цифр и дефисов`);
      if (!meta.description) throw new Error("нет description");
      out.push({
        name,
        description: String(meta.description).trim(),
        tools: toolList(meta.tools),
        model: meta.model ? String(meta.model).trim() : null,
        prompt: m[2].trim(),
        file: entry,
      });
    } catch (err) {
      console.warn(`⚠️  ${entry}: ${(err as Error).message} — пропускаю`);
    }
  }
  return out;
}

// Короткая подпись роли для интерфейса — первая фраза из description, без выдуманных должностей.
export function roleFromDescription(description: string): string {
  const first = description.split(/(?<=[.!?])\s|\(|—/)[0].replace(/[.!?]$/, "").trim();
  return first.length > 50 ? first.slice(0, 47) + "…" : first;
}

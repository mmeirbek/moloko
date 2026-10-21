import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { config } from "./config.js";

fs.mkdirSync(config.dataDir, { recursive: true });

// v2: офис из отделов с субагентами. Старая база (office.db) просто остаётся рядом и не используется.
export const db = new DatabaseSync(path.join(config.dataDir, "office-v2.db"));

db.exec(`
  PRAGMA journal_mode = WAL;
  PRAGMA foreign_keys = ON;

  CREATE TABLE IF NOT EXISTS groups (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    motto       TEXT NOT NULL DEFAULT '',
    color       TEXT NOT NULL DEFAULT '#3ab7ff',
    lead_prompt TEXT NOT NULL DEFAULT '',
    model       TEXT,
    position    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS subagents (
    id          TEXT PRIMARY KEY,
    group_id    TEXT NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    role        TEXT NOT NULL,
    description TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    web         INTEGER NOT NULL DEFAULT 0,
    files       INTEGER NOT NULL DEFAULT 1,
    model       TEXT,
    position    INTEGER NOT NULL DEFAULT 0
  );

  CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    instructions TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'queued',
    result      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    started_at  TEXT,
    finished_at TEXT,
    cost_usd    REAL NOT NULL DEFAULT 0,
    turns       INTEGER NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status);
  CREATE INDEX IF NOT EXISTS tasks_group ON tasks(group_id);

  -- Один «выход» субагента на работу внутри задачи отдела.
  CREATE TABLE IF NOT EXISTS runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    subagent_id TEXT NOT NULL,
    tool_use_id TEXT NOT NULL,
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'working',
    activity    TEXT,
    summary     TEXT,
    started_at  TEXT NOT NULL DEFAULT (datetime('now')),
    finished_at TEXT
  );
  CREATE INDEX IF NOT EXISTS runs_task ON runs(task_id);

  CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    group_id    TEXT,
    subagent_id TEXT,
    kind        TEXT NOT NULL,
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS messages_task ON messages(task_id);

  CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    group_id    TEXT NOT NULL,
    subagent_id TEXT,
    question    TEXT NOT NULL,
    answer      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT
  );

  CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
  );
`);

export type TaskStatus = "queued" | "working" | "waiting" | "done" | "failed" | "cancelled";
export type MessageKind = "boss" | "lead" | "subagent" | "tool" | "system" | "question" | "answer";

export interface GroupRow {
  id: string;
  name: string;
  motto: string;
  color: string;
  lead_prompt: string;
  model: string | null;
  position: number;
  created_at: string;
}

export interface SubagentRow {
  id: string;
  group_id: string;
  name: string;
  role: string;
  description: string;
  prompt: string;
  web: number;
  files: number;
  model: string | null;
  position: number;
}

export interface TaskRow {
  id: number;
  group_id: string;
  title: string;
  instructions: string;
  status: TaskStatus;
  result: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  cost_usd: number;
  turns: number;
}

export interface RunRow {
  id: number;
  task_id: number;
  subagent_id: string;
  tool_use_id: string;
  description: string;
  status: "working" | "done" | "failed";
  activity: string | null;
  summary: string | null;
  started_at: string;
  finished_at: string | null;
}

export interface MessageRow {
  id: number;
  task_id: number | null;
  group_id: string | null;
  subagent_id: string | null;
  kind: MessageKind;
  text: string;
  created_at: string;
}

export interface QuestionRow {
  id: number;
  task_id: number;
  group_id: string;
  subagent_id: string | null;
  question: string;
  answer: string | null;
  created_at: string;
  answered_at: string | null;
}

// node:sqlite возвращает объекты с null-прототипом; приводим к нашим типам в одном месте.
export function all<T>(sql: string, ...params: (string | number | null)[]): T[] {
  return db.prepare(sql).all(...params) as unknown as T[];
}

export function get<T>(sql: string, ...params: (string | number | null)[]): T | undefined {
  return db.prepare(sql).get(...params) as unknown as T | undefined;
}

export function run(sql: string, ...params: (string | number | null)[]) {
  return db.prepare(sql).run(...params);
}

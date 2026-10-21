import fs from "node:fs";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { config } from "./config.js";

fs.mkdirSync(config.dataDir, { recursive: true });

export const db = new DatabaseSync(path.join(config.dataDir, "office.db"));

db.exec(`
  PRAGMA journal_mode = WAL;
  PRAGMA foreign_keys = ON;

  CREATE TABLE IF NOT EXISTS agents (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    role          TEXT NOT NULL,
    emoji         TEXT NOT NULL DEFAULT '🤖',
    color         TEXT NOT NULL DEFAULT '#6c8cff',
    system_prompt TEXT NOT NULL DEFAULT '',
    model         TEXT,
    effort        TEXT NOT NULL DEFAULT 'medium',
    web           INTEGER NOT NULL DEFAULT 0,
    can_delegate  INTEGER NOT NULL DEFAULT 0,
    position      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
  );

  CREATE TABLE IF NOT EXISTS tasks (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id      TEXT NOT NULL,
    parent_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    title         TEXT NOT NULL,
    instructions  TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    result        TEXT,
    created_by    TEXT NOT NULL DEFAULT 'boss',
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    started_at    TEXT,
    finished_at   TEXT,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0
  );
  CREATE INDEX IF NOT EXISTS tasks_status ON tasks(status);
  CREATE INDEX IF NOT EXISTS tasks_parent ON tasks(parent_id);

  CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    INTEGER REFERENCES tasks(id) ON DELETE CASCADE,
    agent_id   TEXT,
    kind       TEXT NOT NULL,
    text       TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
  CREATE INDEX IF NOT EXISTS messages_task ON messages(task_id);

  CREATE TABLE IF NOT EXISTS questions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_id    TEXT NOT NULL,
    question    TEXT NOT NULL,
    answer      TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    answered_at TEXT
  );

  CREATE TABLE IF NOT EXISTS files (
    path       TEXT PRIMARY KEY,
    content    TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
  );
`);

export type TaskStatus = "queued" | "working" | "waiting" | "done" | "failed" | "cancelled";
export type MessageKind = "boss" | "agent" | "thinking" | "tool" | "system" | "question" | "answer";

export interface AgentRow {
  id: string;
  name: string;
  role: string;
  emoji: string;
  color: string;
  system_prompt: string;
  model: string | null;
  effort: "low" | "medium" | "high" | "xhigh" | "max";
  web: number;
  can_delegate: number;
  position: number;
  created_at: string;
}

export interface TaskRow {
  id: number;
  agent_id: string;
  parent_id: number | null;
  title: string;
  instructions: string;
  status: TaskStatus;
  result: string | null;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  input_tokens: number;
  output_tokens: number;
  cost_usd: number;
}

export interface MessageRow {
  id: number;
  task_id: number | null;
  agent_id: string | null;
  kind: MessageKind;
  text: string;
  created_at: string;
}

export interface QuestionRow {
  id: number;
  task_id: number;
  agent_id: string;
  question: string;
  answer: string | null;
  created_at: string;
  answered_at: string | null;
}

export interface FileRow {
  path: string;
  content: string;
  updated_by: string;
  updated_at: string;
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

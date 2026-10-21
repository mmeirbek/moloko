import crypto from "node:crypto";
import path from "node:path";

function int(name: string, fallback: number): number {
  const raw = process.env[name];
  const n = raw ? Number.parseInt(raw, 10) : NaN;
  return Number.isFinite(n) ? n : fallback;
}

const isProd = process.env.NODE_ENV === "production";

if (isProd && !process.env.APP_PASSWORD) {
  console.error("APP_PASSWORD не задан. В продакшене без пароля офис был бы открыт всему интернету.");
  process.exit(1);
}

export const config = {
  port: int("PORT", 3000),
  isProd,
  dataDir: path.resolve(process.env.DATA_DIR ?? "./data"),
  password: process.env.APP_PASSWORD ?? "dev",
  // Если SESSION_SECRET не задан, сессии сбрасываются при каждом рестарте — это не страшно, просто снова войти.
  sessionSecret: process.env.SESSION_SECRET ?? crypto.randomBytes(32).toString("hex"),
  defaultModel: process.env.MODEL ?? "claude-opus-5-5",
  maxTurns: int("MAX_TURNS", 40),
  // Сколько всего задач могут одновременно ходить в API (защита от случайного «пожара» в счёте).
  maxParallel: int("MAX_PARALLEL", 4),
  // Предохранитель: если суммарные траты за сутки превысили лимит, новые задачи не стартуют.
  dailyBudgetUsd: Number(process.env.DAILY_BUDGET_USD ?? "10"),
};

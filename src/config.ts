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

// Чем платим за работу агентов:
// - "subscription": токен подписки Claude (Pro/Max) из `claude setup-token` в CLAUDE_CODE_OAUTH_TOKEN;
// - "api": ключ Claude API в ANTHROPIC_API_KEY (в т.ч. кредиты, включённые в Max/Team).
// Если заданы оба, решает CLAUDE_AUTH (по умолчанию — подписка).
function authMode(): "subscription" | "api" | "none" {
  const hasToken = !!process.env.CLAUDE_CODE_OAUTH_TOKEN;
  const hasKey = !!process.env.ANTHROPIC_API_KEY;
  if (process.env.CLAUDE_AUTH === "api" && hasKey) return "api";
  if (hasToken) return "subscription";
  if (hasKey) return "api";
  return "none";
}

export const config = {
  port: int("PORT", 3000),
  isProd,
  dataDir: path.resolve(process.env.DATA_DIR ?? "./data"),
  password: process.env.APP_PASSWORD ?? "dev",
  // Если SESSION_SECRET не задан, сессии сбрасываются при каждом рестарте — это не страшно, просто снова войти.
  sessionSecret: process.env.SESSION_SECRET ?? crypto.randomBytes(32).toString("hex"),
  auth: authMode(),
  maxTurns: int("MAX_TURNS", 60),
  // Сколько отделов могут работать одновременно. Каждый отдел — отдельный процесс Claude Code (~300 МБ памяти).
  maxParallel: int("MAX_PARALLEL", 3),
  // Предохранитель для режима API-ключа: после этой суммы за сутки новые задачи не стартуют.
  dailyBudgetUsd: Number(process.env.DAILY_BUDGET_USD ?? "10"),
};

import type Anthropic from "@anthropic-ai/sdk";

// Цены за 1M токенов (USD). Нужны для приблизительного счётчика расходов и для выбора модели в интерфейсе.
export const MODELS = [
  { id: "claude-haiku-5-5", label: "Haiku 5.5 — эконом", input: 0.1, output: 0.5, cacheRead: 0.01 },
  { id: "claude-sonnet-5-5", label: "Sonnet 5.5 — баланс", input: 2, output: 10, cacheRead: 0.2 },
  { id: "claude-opus-5-5", label: "Opus 5.5 — максимум качества", input: 4, output: 20, cacheRead: 0.2 },
  { id: "claude-fable-5-1", label: "Fable 5.1 — самый мощный и дорогой", input: 10, output: 50, cacheRead: 0.25 },
] as const;

const PRICES: Record<string, { input: number; output: number; cacheRead: number }> = Object.fromEntries(
  MODELS.map((m) => [m.id, m]),
);

// Haiku: без серверных запасных моделей и только базовые версии веб-поиска.
export function isHaiku(model: string): boolean {
  return model.startsWith("claude-haiku");
}

const WEB_SEARCH_PER_REQUEST = 10 / 1000;

export function estimateCostUsd(model: string, usage: Anthropic.Beta.BetaUsage): number {
  const p = PRICES[model] ?? PRICES["claude-opus-5-5"];
  const cacheWrite = usage.cache_creation_input_tokens ?? 0;
  const cacheRead = usage.cache_read_input_tokens ?? 0;
  const searches = usage.server_tool_use?.web_search_requests ?? 0;
  return (
    (usage.input_tokens * p.input +
      cacheWrite * p.input * 1.25 +
      cacheRead * p.cacheRead +
      usage.output_tokens * p.output) /
      1_000_000 +
    searches * WEB_SEARCH_PER_REQUEST
  );
}

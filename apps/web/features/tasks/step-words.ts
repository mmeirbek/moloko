/**
 * Agent steps in plain words (owner: «Прочитал 3 файла → Исправил форму → Тесты: 2 упали»):
 * what a command is for instead of the command itself, and what it came to. The command and
 * its whole output stay one click away. Pure: tested.
 */

export type CommandKind =
  | "tests"
  | "browserTests"
  | "build"
  | "install"
  | "lint"
  | "typecheck"
  | "git"
  | "look"
  | "script"
  | "other";

const RULES: [CommandKind, RegExp][] = [
  ["browserTests", /\bplaywright\b|\bcypress\b|\b(npm|pnpm|yarn|bun)\s+run\s+(test:)?e2e\b|e2e\.sh\b/],
  ["tests", /\b(pytest|vitest|jest|mocha|unittest)\b|\b(npm|pnpm|yarn|bun)\s+(run\s+)?test\b|\bgo\s+test\b|\bcargo\s+test\b|\bmake\s+test\b/],
  ["typecheck", /\b(tsc|mypy|pyright)\b|\btypecheck\b/],
  ["lint", /\b(eslint|ruff|flake8|prettier|black|biome)\b|\blint\b/],
  ["build", /\b(build|compile|webpack|vite\s+build|next\s+build|make)\b/],
  ["install", /\b(npm|pnpm|yarn|bun)\s+(i|install|ci|add)\b|\bpip3?\s+install\b|\buv\s+(sync|add|pip)\b|\bpoetry\s+install\b|\bapt(-get)?\s+install\b/],
  ["git", /^\s*git\b/],
  ["look", /^\s*(ls|cat|head|tail|find|grep|rg|tree|pwd|wc|du|stat|file|less)\b/],
  ["script", /^\s*(python3?|node|bash|sh|deno|ruby|php)\b/],
];

/** What a sandbox command is for. `cd x && npm test` counts as the part after `cd`. */
export function commandKind(command: string): CommandKind {
  const text = command
    .split("\n")[0]!
    .split(/&&|;|\|\|/)
    .map((p) => p.trim())
    .filter((p) => p && !/^cd\b/.test(p) && !/^export\b/.test(p))
    .join(" && ");
  for (const [kind, rule] of RULES) if (rule.test(text)) return kind;
  return "other";
}

/** The program a command runs (shown for «other»), or "". */
export function commandProgram(command: string): string {
  const part = command
    .split("\n")[0]!
    .split(/&&|;/)
    .map((p) => p.trim())
    .find((p) => p && !/^cd\b/.test(p));
  const word = (part ?? "").split(/\s+/)[0]?.split("/").pop() ?? "";
  return /^[A-Za-z0-9_.+-]{1,24}$/.test(word) ? word : "";
}

export interface CommandOutcome {
  /** Exit code (null: unknown). */
  code: number | null;
  /** Test counts when the output has them. */
  passed?: number;
  failed?: number;
}

/** What a command came to: its exit code, and how many tests passed and failed. */
export function commandOutcome(result: string | null | undefined): CommandOutcome {
  const text = result ?? "";
  const code = /^exit code (-?\d+)/.exec(text);
  const out: CommandOutcome = { code: code ? Number(code[1]) : null };
  // vitest «Tests  2 failed | 10 passed», jest «Tests: 2 failed, 8 passed», pytest «2 failed, 10 passed».
  const summary =
    /Tests?:?\s+((?:\d+\s+\w+(?:\s*[|,]\s*)?)+)/.exec(text)?.[1] ?? /=+\s*((?:\d+\s+\w+(?:,\s*)?)+)\s+in\s+[\d.]+s/.exec(text)?.[1];
  if (summary) {
    const count = (word: RegExp) => {
      const m = new RegExp(`(\\d+)\\s+${word.source}`).exec(summary);
      return m ? Number(m[1]) : undefined;
    };
    out.passed = count(/passed/);
    out.failed = count(/failed/);
  }
  return out;
}

/** Steps that read or look (several in a row read as one line: «Прочитал 3 файла»). */
export const GROUPABLE = new Set(["fs_read", "fs_list", "github_read_file", "github_list_dir", "web_fetch", "work_read", "knowledge_search", "web_search"]);

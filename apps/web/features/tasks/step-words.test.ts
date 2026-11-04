import { describe, expect, it } from "vitest";

import { commandKind, commandOutcome, commandProgram } from "./step-words";

describe("commands in plain words", () => {
  it("says what a command is for", () => {
    expect(commandKind("cd /w/app && npm test -- --run")).toBe("tests");
    expect(commandKind("uv run pytest -q tests/test_api.py")).toBe("tests");
    expect(commandKind("npx playwright test e2e/tests/chat.spec.ts")).toBe("browserTests");
    expect(commandKind("npm run build")).toBe("build");
    expect(commandKind("npm ci")).toBe("install");
    expect(commandKind("pip install -r requirements.txt")).toBe("install");
    expect(commandKind("npm run lint")).toBe("lint");
    expect(commandKind("npx tsc --noEmit")).toBe("typecheck");
    expect(commandKind("git status")).toBe("git");
    expect(commandKind("ls -la e2e")).toBe("look");
    expect(commandKind('python3 -c "\nprint(1)\n"')).toBe("script");
    expect(commandKind("ffmpeg -i a.mp4 b.gif")).toBe("other");
    expect(commandProgram("cd x && ffmpeg -i a.mp4 b.gif")).toBe("ffmpeg");
  });

  it("reads how many tests passed and failed", () => {
    expect(commandOutcome("exit code 0\n--- stdout ---\n Test Files  3 passed (3)\n      Tests  12 passed (12)")).toEqual({
      code: 0,
      passed: 12, // tests, not test files
      failed: undefined,
    });
    expect(commandOutcome("exit code 1\n--- stdout ---\n      Tests  2 failed | 10 passed (12)")).toEqual({ code: 1, passed: 10, failed: 2 });
    expect(commandOutcome("exit code 1\n=========== 2 failed, 10 passed in 3.21s ===========")).toEqual({
      code: 1,
      passed: 10,
      failed: 2,
    });
    expect(commandOutcome("exit code 0")).toEqual({ code: 0 });
    expect(commandOutcome(null)).toEqual({ code: null });
  });
});

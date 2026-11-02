import { describe, expect, it } from "vitest";

import { BEHAVIOR, hudModeFor } from "./behavior";
import {
  ACTIVITY_CHARS,
  agentHud,
  BAR_INNER,
  barFill,
  cleanActivity,
  hudText,
  officeHud,
  taskPercent,
  type HudSource,
  type HudTask,
} from "./hud";
import { busyLit, FRAME, HUD_BAR, HUD_BAR_W, HUD_BUSY_FRAMES, HUD_TONES } from "./sprites";

const words = { step: (n: number) => `шаг ${n}`, approval: "ждёт одобрения" };

const task = (id: string, extra: Partial<HudTask> = {}): HudTask => ({
  id,
  status: "running",
  progress: 0,
  title: `Задача ${id}`,
  run_id: `run-${id}`,
  parent_task_id: null,
  agent_id: "a",
  ...extra,
});

const source = (over: Partial<HudSource> = {}): HudSource => ({
  tasks: {},
  runs: {},
  lastMessage: {},
  approvals: {},
  ...over,
});

const agent = (status: string, current_task_id: string | null = "t") => ({ id: "a", status, current_task_id });

describe("activity label (untrusted model text → a few words of plain text)", () => {
  it("keeps the first sentence, a few words, with an ellipsis when cut", () => {
    expect(cleanActivity("Сначала найду все обработчики, затем напишу тесты. Потом отчёт.")).toBe("Сначала найду все…");
    expect(cleanActivity("Читаю файл")).toBe("Читаю файл");
    expect(cleanActivity("Готово!")).toBe("Готово!");
  });

  it("drops HTML, Markdown, links, code, emoji, control and direction-override characters", () => {
    expect(cleanActivity("<script>alert(1)</script><b>Пишу</b> отчёт.")).toBe("Пишу отчёт");
    expect(cleanActivity("**Сравниваю** `цены` 🥛")).toBe("Сравниваю цены");
    expect(cleanActivity("Смотри [справку](https://evil.example/x) сейчас")).toBe("Смотри справку сейчас");
    expect(cleanActivity("Смотри [документацию](https://evil.example/x) сейчас")).toBe("Смотри документацию…");
    expect(cleanActivity("Открываю https://evil.example/a?b=c и читаю")).toBe("Открываю и читаю");
    expect(cleanActivity("‮текст‬ наоборот\u0007")).toBe("текст наоборот");
    expect(cleanActivity("```js\nrm -rf /\n```\nПроверяю код")).toBe("Проверяю код");
    expect(cleanActivity("# План\n- первый шаг")).toBe("План");
    // whatever is left is plain text drawn on a canvas: no markup characters or entities survive
    for (const out of [
      cleanActivity("&lt;img src=x onerror=alert(1)&gt; привет"),
      cleanActivity("<img src=x onerror=alert(1)>"),
      cleanActivity("a < b > c"),
    ]) {
      expect(out ?? "").not.toMatch(/[<>]|&[a-z#]/i);
    }
  });

  it("skips empty lines and list markers, never returns markup-only text", () => {
    expect(cleanActivity("\n\n  1. Ищу новости о рынке")).toBe("Ищу новости о рынке");
    expect(cleanActivity("")).toBeNull();
    expect(cleanActivity("***  ---  ```")).toBeNull();
    expect(cleanActivity(undefined)).toBeNull();
    expect(cleanActivity(42)).toBeNull();
  });

  it("is never longer than the limit (plus the ellipsis)", () => {
    const long = cleanActivity("Суперкалифрагилистикэкспиалидоциозный антидисэстаблишментарианизм");
    expect(long!.length).toBeLessThanOrEqual(ACTIVITY_CHARS);
    expect(long!.endsWith("…")).toBe(true);
    expect(cleanActivity("x".repeat(10_000))!.length).toBeLessThanOrEqual(ACTIVITY_CHARS);
  });
});

describe("task progress", () => {
  it("comes from subtasks (done / all, like the server) or from the task's own progress", () => {
    const children = [
      task("c1", { status: "completed" }),
      task("c2", { status: "failed" }),
      task("c3", { status: "running" }),
      task("c4", { status: "queued" }),
    ];
    expect(taskPercent(task("t"), children)).toBe(50);
    expect(taskPercent(task("t", { progress: 75 }), children)).toBe(75);
    expect(taskPercent(task("t"), [task("c", { status: "running" })])).toBe(0);
    expect(taskPercent(task("t", { progress: 42 }), [])).toBe(42);
  });

  it("is unknown at 0 % without subtasks, and never 100 % before the task is done", () => {
    expect(taskPercent(task("t"), [])).toBeNull();
    expect(taskPercent(task("t"), [task("c", { status: "completed" })])).toBe(99);
    expect(taskPercent(task("t", { status: "completed", progress: 100 }), [])).toBe(100);
  });

  it("fills the bar in whole pixels, never full before 100 % nor empty after 0 %", () => {
    expect(barFill(0)).toBe(0);
    expect(barFill(1)).toBe(1);
    expect(barFill(50)).toBe(BAR_INNER / 2);
    expect(barFill(99)).toBe(BAR_INNER - 1);
    expect(barFill(100)).toBe(BAR_INNER);
    expect(barFill(Number.NaN)).toBe(0);
  });
});

describe("HUD over the head", () => {
  it("shows % when known, else the step, else only the busy bar", () => {
    const t = task("t", { progress: 42 });
    expect(agentHud(agent("working"), source({ tasks: { t } }), words)).toEqual({
      percent: 42,
      tag: "42%",
      activity: "Задача t",
      tone: "work",
    });
    const s = source({
      tasks: { t: task("t") },
      runs: { "run-t": { steps: 3 } },
      lastMessage: { "run-t": { step: 4, text: "Пишу тесты" } },
    });
    expect(agentHud(agent("working"), s, words)).toMatchObject({ percent: null, tag: "шаг 4", activity: "Пишу тесты" });
    // a plan / message between agents has no step and no text: the run's step and the title stay
    const quiet = source({
      tasks: { t: task("t") },
      runs: { "run-t": { steps: 2 } },
      lastMessage: { "run-t": { step: 0, text: "" } },
    });
    expect(agentHud(agent("planning"), quiet, words)).toMatchObject({ tag: "шаг 2", activity: "Задача t" });
    expect(agentHud(agent("planning"), source({ tasks: { t: task("t") } }), words)).toMatchObject({
      percent: null,
      tag: null,
    });
  });

  it("is hidden while resting or done (status → visual stays in behavior.ts)", () => {
    const s = source({ tasks: { t: task("t", { progress: 50 }) } });
    for (const status of ["idle", "completed", "failed", "something-new"]) {
      expect(agentHud(agent(status), s, words), status).toBeNull();
    }
    expect(agentHud(agent("paused"), s, words)).toMatchObject({ tone: "paused", tag: "50%" });
  });

  it("marks an agent waiting for the owner's approval (pending approval or task status)", () => {
    const s = source({ tasks: { t: task("t") }, approvals: { p: { agent_id: "a", status: "pending" } } });
    expect(agentHud(agent("waiting"), s, words)).toMatchObject({ tone: "approval", tag: "ждёт одобрения" });
    const byTask = source({ tasks: { t: task("t", { status: "waiting_approval" }) } });
    expect(agentHud(agent("waiting"), byTask, words)).toMatchObject({ tone: "approval" });
    const answered = source({ tasks: { t: task("t") }, approvals: { p: { agent_id: "a", status: "approved" } } });
    expect(agentHud(agent("waiting"), answered, words)).toMatchObject({ tone: "work", tag: null });
  });

  it("finds the agent's busy task when the agent does not name it yet", () => {
    const s = source({ tasks: { old: task("old", { status: "completed", progress: 100 }), t: task("t", { progress: 30 }) } });
    expect(agentHud(agent("working", null), s, words)).toMatchObject({ percent: 30 });
    expect(agentHud(agent("working", null), source(), words)).toEqual({
      percent: null,
      tag: null,
      activity: null,
      tone: "work",
    });
  });

  it("the Orchestrator's root task counts its subtasks", () => {
    const s = source({
      tasks: {
        t: task("t", { status: "waiting" }),
        s1: task("s1", { parent_task_id: "t", status: "completed", agent_id: "b" }),
        s2: task("s2", { parent_task_id: "t", status: "running", agent_id: "c" }),
      },
    });
    expect(agentHud(agent("waiting"), s, words)).toMatchObject({ percent: 50, tag: "50%" });
  });

  it("officeHud leaves out agents with nothing to show", () => {
    const s = source({ tasks: { t: task("t", { progress: 10 }) } });
    const huds = officeHud([agent("working"), { id: "b", status: "idle", current_task_id: null }], s, words);
    expect(Object.keys(huds)).toEqual(["a"]);
  });

  it("the caption: the short tag; the focused agent also says what it is doing", () => {
    const hud = { percent: 42, tag: "42%", activity: "Пишу тесты", tone: "work" as const };
    expect(hudText(hud, false)).toBe("42%");
    expect(hudText(hud, true)).toBe("42%\nПишу тесты");
    expect(hudText({ ...hud, tag: null }, false)).toBeNull();
    expect(hudText({ ...hud, tag: null }, true)).toBe("Пишу тесты");
    expect(hudText(null, true)).toBeNull();
  });
});

describe("status → progress bar (behavior.ts)", () => {
  it("every status says whether the bar shows", () => {
    for (const [status, b] of Object.entries(BEHAVIOR)) expect(["live", "frozen", "none"], status).toContain(b.hud);
    expect(hudModeFor("working")).toBe("live");
    expect(hudModeFor("paused")).toBe("frozen");
    expect(hudModeFor("idle")).toBe("none");
    expect(hudModeFor("unknown")).toBe("none");
  });
});

describe("progress bar art", () => {
  it("is as wide as a character, with the inner track the fill uses", () => {
    expect(HUD_BAR_W).toBe(FRAME);
    for (const row of HUD_BAR) expect(row).toHaveLength(HUD_BAR_W);
    expect(HUD_BAR_W - 2).toBe(BAR_INNER);
    expect(Object.keys(HUD_TONES).sort()).toEqual(["approval", "paused", "work"]);
  });

  it("busy stripes light half the track and move every frame", () => {
    const frame = (f: number) =>
      [0, 1].map((y) => Array.from({ length: BAR_INNER }, (_, x) => (busyLit(x, y, f) ? "x" : ".")).join("")).join("|");
    const frames = Array.from({ length: HUD_BUSY_FRAMES }, (_, f) => frame(f));
    expect(new Set(frames).size).toBe(HUD_BUSY_FRAMES);
    for (const f of frames) expect(Math.abs(f.split("x").length - 1 - BAR_INNER)).toBeLessThanOrEqual(2);
  });
});

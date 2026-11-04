/**
 * Original pixel art, drawn in code (no third-party assets — see assets/MANIFEST.md).
 * Characters are 16×16 frames described as character maps; palettes vary per agent.
 */
import type { Species } from "@/features/agents/agent-looks";

import { animalFrame, ANIMAL_ART } from "./animals";
import { hash } from "./assign";
import type { Indicator } from "./behavior";
import type { AgentHud } from "./bus";

export const FRAME = 16;

/** palette keys: . transparent  o outline  s skin  h hair  c shirt  p pants  f shoes  e eyes  w white  d paper */
const FRONT = [
  "................",
  ".....hhhhhh.....",
  "....hhhhhhhh....",
  "....hssssssh....",
  "....sesssses....",
  "....ssssssss....",
  ".....ssssss.....",
  "....cccccccc....",
  "...sccccccccs...",
  "...sccccccccs...",
  "....cccccccc....",
  "....pppppppp....",
  "....ppp..ppp....",
  "....ppp..ppp....",
  "....fff..fff....",
  "................",
];

const BACK = [
  "................",
  ".....hhhhhh.....",
  "....hhhhhhhh....",
  "....hhhhhhhh....",
  "....hhhhhhhh....",
  "....shhhhhhs....",
  ".....ssssss.....",
  "....cccccccc....",
  "...sccccccccs...",
  "...sccccccccs...",
  "....cccccccc....",
  "....pppppppp....",
  "....ppp..ppp....",
  "....ppp..ppp....",
  "....fff..fff....",
  "................",
];

type Grid = string[];

function replaceRows(base: Grid, rows: Record<number, string>): Grid {
  return base.map((line, i) => rows[i] ?? line);
}

function shiftDown(base: Grid, from: number, to: number): Grid {
  const out = [...base];
  for (let r = to; r > from; r--) out[r] = base[r - 1]!;
  out[from] = "................";
  return out;
}

export const FRAMES: Record<string, Grid> = {
  stand: FRONT,
  breathe: shiftDown(FRONT, 1, 10),
  walk1: replaceRows(FRONT, {
    12: "...ppp...ppp....",
    13: "...ppp....ppp...",
    14: "...fff....fff...",
  }),
  walk2: replaceRows(FRONT, {
    12: "....ppp...ppp...",
    13: "...ppp....ppp...",
    14: "..fff.....fff...",
  }),
  type1: replaceRows(BACK, {
    7: "...scccccccs....",
    8: "....cccccccc....",
    9: "....cccccccc....",
  }),
  type2: replaceRows(BACK, {
    7: "....sccccccs....",
    8: "....cccccccc....",
    9: "....cccccccc....",
  }),
  think1: replaceRows(FRONT, {
    6: "...sssssss......",
    7: "...scccccccc....",
    8: "....cccccccc....",
    9: "....ccccccccs...",
  }),
  think2: replaceRows(FRONT, {
    4: "....sessssse....",
    6: "...sssssss......",
    7: "...scccccccc....",
    8: "....cccccccc....",
    9: "....ccccccccs...",
  }),
  read1: replaceRows(FRONT, {
    8: "...sddddddddds..",
    9: "...sdwwwwwwwds..",
    10: "....dddddddd....",
  }),
  read2: replaceRows(FRONT, {
    4: "....ssssssss....",
    8: "...sddddddddds..",
    9: "...sdwwwwwwwds..",
    10: "....dddddddd....",
  }),
  wait1: FRONT,
  wait2: replaceRows(FRONT, { 13: "....ppp..ppp....", 14: "....fff...fff..." }),
  cheer1: replaceRows(FRONT, {
    3: "..s.hssssssh.s..",
    4: "..s.sesssses.s..",
    5: "..s.ssssssss.s..",
    6: "...s.ssssss.s...",
    8: "....cccccccc....",
    9: "....cccccccc....",
  }),
  cheer2: shiftDown(
    replaceRows(FRONT, {
      3: "..s.hssssssh.s..",
      4: "..s.sesssses.s..",
      5: "..s.ssssssss.s..",
      6: "...s.ssssss.s...",
      8: "....cccccccc....",
      9: "....cccccccc....",
    }),
    0,
    11,
  ),
  slump1: shiftDown(replaceRows(FRONT, { 4: "....soossoos...." }), 1, 7),
  slump2: shiftDown(replaceRows(FRONT, { 4: "....soossoos...." }), 1, 8),
};

/** Every pose has two frames; walking uses walk1/walk2. */
export const POSE_FRAMES = {
  rest: ["stand", "breathe"],
  think: ["think1", "think2"],
  type: ["type1", "type2"],
  wait: ["wait1", "wait2"],
  read: ["read1", "read2"],
  frozen: ["stand", "stand"],
  cheer: ["cheer1", "cheer2"],
  slump: ["slump1", "slump2"],
  walk: ["walk1", "walk2"],
} as const;

export const FRAME_ORDER = Object.keys(FRAMES);

const SKINS = ["#f2c9a0", "#e0a878", "#c68653", "#8d5a3b", "#f5d7b5"];
const HAIRS = ["#2b1d14", "#5a3a22", "#a0522d", "#d9b26f", "#1f2633", "#7a7a85"];
const SHIRTS = ["#4aa8e8", "#5bbf4a", "#e8734a", "#9b6bd6", "#e8c34a", "#4ad6c0", "#d64a7a", "#7a8de8"];

export interface Palette {
  o: string;
  s: string;
  h: string;
  c: string;
  p: string;
  f: string;
  e: string;
  w: string;
  d: string;
  /** an animal's head (animals.ts): fur, light fur, marks, nose, second accent */
  a?: string;
  b?: string;
  k?: string;
  n?: string;
  x?: string;
}

/** The agent's shirt (its own colour); with a species, its fur, marks and eyes (arms are fur). */
export function paletteFor(id: string, kind: string, species?: Species): Palette {
  const n = hash(id);
  const shirt = kind === "orchestrator" ? "#f0b43c" : SHIRTS[n % SHIRTS.length]!;
  const human: Palette = {
    o: "#1b1b2e",
    s: SKINS[(n >>> 3) % SKINS.length]!,
    h: HAIRS[(n >>> 7) % HAIRS.length]!,
    c: shirt,
    p: kind === "subagent" ? "#3b4a6b" : "#2e3a5c",
    f: "#22222f",
    e: "#1b1b2e",
    w: "#ffffff",
    d: "#f6efdc",
  };
  if (!species) return human;
  const art = ANIMAL_ART[species];
  const { a, b, k, n: nose, x, w } = art.colors;
  return { ...human, s: a, a, b, k, n: nose, x: x ?? a, w: w ?? "#ffffff", e: art.eyes ?? "#1b1b2e" };
}

/** Paint all frames of one palette side by side, each with a 1 px navy outline (readability). */
export function paintSheet(ctx: CanvasRenderingContext2D, palette: Palette, species?: Species): void {
  FRAME_ORDER.forEach((name, i) => {
    const grid = species ? animalFrame(name, FRAMES[name]!, species) : FRAMES[name]!;
    const filled = (x: number, y: number) =>
      x >= 0 && y >= 0 && x < FRAME && y < FRAME && grid[y]![x] !== "." && grid[y]![x] !== undefined;
    ctx.fillStyle = OUTLINE;
    for (let y = 0; y < FRAME; y++) {
      for (let x = 0; x < FRAME; x++) {
        if (filled(x, y)) continue;
        if (filled(x - 1, y) || filled(x + 1, y) || filled(x, y - 1) || filled(x, y + 1)) ctx.fillRect(i * FRAME + x, y, 1, 1);
      }
    }
    for (let y = 0; y < FRAME; y++) {
      const line = grid[y]!;
      for (let x = 0; x < FRAME; x++) {
        const key = line[x] as keyof Palette | ".";
        if (key === "." || key === undefined) continue;
        ctx.fillStyle = palette[key] ?? palette.o;
        ctx.fillRect(i * FRAME + x, y, 1, 1);
      }
    }
  });
}

const OUTLINE = "rgba(16,20,43,0.9)";

/**
 * 8×8 glyphs for the status badges above heads (spec 18.4 indicators); 'x' = the glyph colour.
 * Each badge has its own colour, so a status reads at a glance even when the glyph is tiny.
 */
export const ICONS: Record<Exclude<Indicator, "none">, string[]> = {
  thinking: ["........", "........", "........", "xx.xx.xx", "xx.xx.xx", "........", "........", "........"],
  hourglass: ["xxxxxxxx", ".x....x.", "..x..x..", "...xx...", "...xx...", "..x..x..", ".xxxxxx.", "xxxxxxxx"],
  document: [".xxxxx..", ".x...xx.", ".x...xxx", ".x.....x", ".x.xxx.x", ".x.....x", ".x.xxx.x", ".xxxxxxx"],
  pause: ["........", ".xx..xx.", ".xx..xx.", ".xx..xx.", ".xx..xx.", ".xx..xx.", ".xx..xx.", "........"],
  check: ["........", "......xx", ".....xx.", "xx..xx..", ".xxxx...", "..xx....", "........", "........"],
  alert: ["...xx...", "...xx...", "...xx...", "...xx...", "...xx...", "........", "...xx...", "...xx..."],
};

/** Badge colours per indicator: fill and glyph. */
export const BADGES: Record<Exclude<Indicator, "none">, { fill: string; glyph: string }> = {
  thinking: { fill: "#6ec3f5", glyph: "#10142b" },
  hourglass: { fill: "#f0b43c", glyph: "#10142b" },
  document: { fill: "#f5ecd6", glyph: "#2a3566" },
  pause: { fill: "#8a8fa8", glyph: "#ffffff" },
  check: { fill: "#5bbf4a", glyph: "#ffffff" },
  alert: { fill: "#e5534b", glyph: "#ffffff" },
};

/** A 12×14 badge: rounded square with a tail pointing down at the head. */
const BADGE = [
  ".oooooooooo.",
  "ohFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  "oFFFFFFFFFFo",
  ".oooooooooo.",
  "....oFFo....",
  ".....oo.....",
];
export const BADGE_W = BADGE[0]!.length;
export const BADGE_H = BADGE.length;

export function paintBadge(ctx: CanvasRenderingContext2D, indicator: Exclude<Indicator, "none">): void {
  const { fill, glyph } = BADGES[indicator];
  BADGE.forEach((line, y) => {
    for (let x = 0; x < line.length; x++) {
      const key = line[x]!;
      if (key === ".") continue;
      ctx.fillStyle = key === "o" ? "#10142b" : key === "h" ? "rgba(255,255,255,0.6)" : fill;
      ctx.fillRect(x, y, 1, 1);
    }
  });
  ctx.fillStyle = glyph;
  ICONS[indicator].forEach((line, y) => {
    for (let x = 0; x < 8; x++) if (line[x] === "x") ctx.fillRect(2 + x, 2 + y, 1, 1);
  });
}

// --- progress over the head (engine/hud.ts) ---------------------------------------------------

/** A 16×4 bar (as wide as a character): navy frame with cut corners and a two-tone track. */
export const HUD_BAR = [
  ".oooooooooooooo.",
  "otttttttttttttto",
  "obbbbbbbbbbbbbbo",
  ".oooooooooooooo.",
];
export const HUD_BAR_W = HUD_BAR[0]!.length;
export const HUD_BAR_H = HUD_BAR.length;
export const HUD_BAR_COLORS: Record<string, string> = { o: "#10142b", t: "#2a3566", b: "#1d2447" };
/** Frames of the "busy" stripes (progress unknown); they run along the bar. */
export const HUD_BUSY_FRAMES = 4;

/** Fill colours: green while working, amber while it waits for the owner, grey when paused. */
export const HUD_TONES: Record<AgentHud["tone"], { light: string; base: string }> = {
  work: { light: "#a6e08a", base: "#5bbf4a" },
  approval: { light: "#f9d77a", base: "#f0b43c" },
  paused: { light: "#c3c6d4", base: "#8a8fa8" },
};

/** One filled column of the bar (1×2), stretched to the filled width. */
export function paintHudFill(ctx: CanvasRenderingContext2D, tone: AgentHud["tone"]): void {
  ctx.fillStyle = HUD_TONES[tone].light;
  ctx.fillRect(0, 0, 1, 1);
  ctx.fillStyle = HUD_TONES[tone].base;
  ctx.fillRect(0, 1, 1, 1);
}

/** Pixels lit in a "busy" frame: diagonal stripes, period 4, one pixel further each frame. Pure. */
export function busyLit(x: number, y: number, frame: number): boolean {
  return (x - frame + y + 64) % 4 < 2;
}

/** All "busy" frames side by side (each `inner`×2; the track shows between the stripes). */
export function paintHudBusy(ctx: CanvasRenderingContext2D, tone: AgentHud["tone"], inner: number): void {
  for (let f = 0; f < HUD_BUSY_FRAMES; f++) {
    for (let y = 0; y < 2; y++) {
      ctx.fillStyle = y === 0 ? HUD_TONES[tone].light : HUD_TONES[tone].base;
      for (let x = 0; x < inner; x++) if (busyLit(x, y, f)) ctx.fillRect(f * inner + x, y, 1, 1);
    }
  }
}

/** The frame around a desk whose agent waits for the owner's approval (navy + amber, cut corners). */
export const DESK_MARK_W = 38;
export const DESK_MARK_H = 39;

export function paintDeskMark(ctx: CanvasRenderingContext2D): void {
  const w = DESK_MARK_W;
  const h = DESK_MARK_H;
  ctx.fillStyle = "rgba(240,180,60,0.18)";
  ctx.fillRect(3, 3, w - 6, h - 6);
  // rings from the outside in: navy, amber, amber, soft navy (outer corners cut)
  const rings = ["#10142b", "#f0b43c", "#f0b43c", "rgba(16,20,43,0.55)"];
  rings.forEach((color, i) => {
    ctx.fillStyle = color;
    const cut = Math.max(0, 2 - i);
    ctx.fillRect(i + cut, i, w - 2 * (i + cut), 1);
    ctx.fillRect(i + cut, h - 1 - i, w - 2 * (i + cut), 1);
    ctx.fillRect(i, i + cut, 1, h - 2 * (i + cut));
    ctx.fillRect(w - 1 - i, i + cut, 1, h - 2 * (i + cut));
  });
}

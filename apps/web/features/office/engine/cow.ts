/**
 * The cow (the Orchestrator) in the office, desk pets and speech bubbles. Original pixel
 * art (features/mascot/cow-art.json and the maps below; see assets/MANIFEST.md).
 */
import { COW, type Season } from "@/features/mascot/art";

import { hash } from "./assign";
import type { CowPose } from "./behavior";

export const COW_W = COW.side.width; // 24
export const COW_PAD = 4; // empty rows above the art for hats
export const COW_H = COW.side.height + COW_PAD; // 20
export const COW_FRAMES = Object.keys(COW.side.frames);

/** Two frames per pose; walking uses walk1/walk2 (carry1/carry2 while working). */
export const COW_POSES: Record<CowPose | "walk", [string, string]> = {
  stand: ["stand", "breathe"],
  graze: ["graze1", "graze2"],
  carry: ["carry1", "carry2"],
  moo: ["moo1", "moo2"],
  sad: ["sad1", "sad2"],
  sleep: ["sleep1", "sleep2"],
  cheer: ["cheer1", "cheer2"],
  frozen: ["stand", "stand"],
  walk: ["walk1", "walk2"],
};

// Seasonal hats for the side view, anchored at the left horn (x, y) of each frame.
const HATS: Record<Season, { rows: string[]; dx: number; dy: number }> = {
  newyear: { rows: [".....RW", "...RRR.", "..RRRR.", ".WWWWWW"], dx: -2, dy: -2 },
  halloween: { rows: ["...V....", "...VV...", "..VVVV..", "..VyyV..", "VVVVVVVV"], dx: -3, dy: -3 },
  spring: { rows: [".F.", "FyF", ".F."], dx: 0, dy: -2 },
};

/** The left horn of a frame: where hats sit. */
export function hornOf(rows: string[]): { x: number; y: number } {
  for (let y = 0; y < rows.length; y++) {
    const x = rows[y]!.indexOf("h");
    if (x >= 0) return { x, y };
  }
  return { x: 19, y: 1 };
}

/** Frame rows (24×20) with the hat drawn on, if any. Pure: tested. */
export function cowFrame(name: string, season: Season | null): string[] {
  const art = COW.side.frames[name]!;
  const rows = [...Array.from({ length: COW_PAD }, () => ".".repeat(COW_W)), ...art];
  if (!season) return rows;
  const hat = HATS[season];
  const horn = hornOf(art);
  const out = rows.map((r) => r.split(""));
  hat.rows.forEach((line, j) => {
    const y = horn.y + COW_PAD + hat.dy + j;
    [...line].forEach((key, i) => {
      const x = horn.x + hat.dx + i;
      if (key !== "." && y >= 0 && y < COW_H && x >= 0 && x < COW_W) out[y]![x] = key;
    });
  });
  return out.map((r) => r.join(""));
}

export function paintCowSheet(ctx: CanvasRenderingContext2D, season: Season | null): void {
  COW_FRAMES.forEach((name, i) => {
    cowFrame(name, season).forEach((line, y) => {
      for (let x = 0; x < COW_W; x++) {
        const key = line[x]!;
        if (key === ".") continue;
        ctx.fillStyle = COW.palette[key] ?? "#ff00ff";
        ctx.fillRect(i * COW_W + x, y, 1, 1);
      }
    });
  });
}

// --- speech bubbles (3×5 pixel letters) -------------------------------------------------------

const GLYPHS: Record<string, string[]> = {
  М: ["k.k", "kkk", "kkk", "k.k", "k.k"],
  M: ["k.k", "kkk", "kkk", "k.k", "k.k"],
  У: ["k.k", "k.k", ".kk", "..k", "kk."],
  O: [".k.", "k.k", "k.k", "k.k", ".k."],
  "!": ["k", "k", "k", ".", "k"],
  Z: ["kkk", "..k", ".k.", "k..", "kkk"],
  z: ["...", "kkk", ".k.", "k..", "kkk"],
};

/** A white speech bubble with pixel text and a tail at the bottom left. Pure: tested. */
export function bubbleRows(text: string): string[] {
  const glyphs = [...text].map((ch) => GLYPHS[ch] ?? GLYPHS["!"]!);
  const inner = glyphs.reduce((w, g) => w + g[0]!.length, 0) + glyphs.length - 1;
  const width = inner + 4;
  const edge = "." + "o".repeat(width - 2) + ".";
  const pad = "o" + "w".repeat(width - 2) + "o";
  const rows = [edge, pad];
  for (let y = 0; y < 5; y++) rows.push("ow" + glyphs.map((g) => g[y]!.replace(/\./g, "w")).join("w") + "wo");
  rows.push(pad, edge, "..oo" + ".".repeat(width - 4), "..o" + ".".repeat(width - 3));
  return rows;
}

export const BUBBLE_COLORS: Record<string, string> = { o: "#1b1b2e", w: "#ffffff", k: "#1b1b2e" };

// --- desk pets for persistent agents ---------------------------------------------------------

const PET_PALETTE: Record<string, string> = {
  o: "#1b1b2e",
  y: "#f0c93c",
  r: "#e8734a",
  g: "#5bbf4a",
  G: "#3f8f32",
  w: "#ffffff",
  p: "#f4a6b8",
  b: "#8a5a3b",
  c: "#c9c4bb",
  e: "#1b1b2e",
};

/** 7×6 pets that sit on an agent's desk (one per persistent agent, chosen by its id). */
export const PETS: Record<string, string[]> = {
  chick: ["..yy...", ".yeyr..", ".yyy...", "yyyyy..", ".yyy...", ".r.r..."],
  cat: ["c...c..", "cc.cc..", "cecec..", "ccpcc..", ".ccc..c", ".c.c.c."],
  frog: [".g.g...", "gegeg..", "ggggg..", "gGGGg..", "g...g..", "......."],
  bunny: [".w.w...", ".w.w...", "wwwww..", "wewew..", "wwpww..", ".w.w..."],
  piggy: ["p...p..", "ppppp..", "pepep..", "pprpp..", ".ppp...", ".p.p..."],
  duck: ["..ww...", ".wew...", ".wwwyy.", "wwwww..", ".www...", ".y.y..."],
};
export const PET_NAMES = Object.keys(PETS);

export function petFor(agentId: string): string {
  return PET_NAMES[hash(`pet:${agentId}`) % PET_NAMES.length]!;
}

export function paintRows(
  ctx: CanvasRenderingContext2D,
  rows: string[],
  colors: Record<string, string>,
  ox = 0,
  oy = 0,
): void {
  rows.forEach((line, y) => {
    for (let x = 0; x < line.length; x++) {
      const key = line[x]!;
      if (key === ".") continue;
      ctx.fillStyle = colors[key] ?? "#ff00ff";
      ctx.fillRect(ox + x, oy + y, 1, 1);
    }
  });
}

export const PET_COLORS = PET_PALETTE;

/** A 10×7 envelope with a red seal for messages between agents. */
export const ENVELOPE = [
  "oooooooooo",
  "owwwwwwwwo",
  "oowwwwwwoo",
  "owowwwwowo",
  "owwooroowo",
  "owwwwwwwwo",
  "oooooooooo",
];
export const ENVELOPE_COLORS: Record<string, string> = { o: "#1b1b2e", w: "#f6efdc", r: "#e5534b" };

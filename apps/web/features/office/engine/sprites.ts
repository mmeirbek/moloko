/**
 * Original pixel art, drawn in code (no third-party assets — see assets/MANIFEST.md).
 * Characters are 16×16 frames described as character maps; palettes vary per agent.
 */
import { hash } from "./assign";

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
}

export function paletteFor(id: string, kind: string): Palette {
  const n = hash(id);
  const shirt = kind === "orchestrator" ? "#f0b43c" : SHIRTS[n % SHIRTS.length]!;
  return {
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
}

/** Paint all frames of one palette side by side onto a 2D canvas context. */
export function paintSheet(ctx: CanvasRenderingContext2D, palette: Palette): void {
  FRAME_ORDER.forEach((name, i) => {
    const grid = FRAMES[name]!;
    for (let y = 0; y < FRAME; y++) {
      const line = grid[y]!;
      for (let x = 0; x < FRAME; x++) {
        const key = line[x] as keyof Palette | ".";
        if (key === "." || key === undefined) continue;
        ctx.fillStyle = palette[key];
        ctx.fillRect(i * FRAME + x, y, 1, 1);
      }
    }
  });
}

/** 8×8 status icons above heads (spec 18.4 indicators). */
export const ICONS: Record<string, string[]> = {
  thinking: ["........", ".wwwwww.", "wwwwwwww", "wkwkwkww", "wwwwwwww", ".wwwwww.", "..ww....", ".w......"],
  hourglass: ["kkkkkkkk", ".kyyyyk.", "..kyyk..", "...kk...", "...kk...", "..kyyk..", ".kyyyyk.", "kkkkkkkk"],
  document: [".kkkkk..", ".kwwwkk.", ".kwkkwk.", ".kwwwwk.", ".kwkkwk.", ".kwwwwk.", ".kkkkkk.", "........"],
  pause: ["........", ".kk..kk.", ".kk..kk.", ".kk..kk.", ".kk..kk.", ".kk..kk.", ".kk..kk.", "........"],
  check: ["........", "......gg", ".....gg.", "gg..gg..", ".gggg...", "..gg....", "........", "........"],
  alert: ["...rr...", "...rr...", "...rr...", "...rr...", "...rr...", "........", "...rr...", "...rr..."],
  envelope: ["........", "wwwwwwww", "wkwwwwkw", "wwkwwkww", "wwwkkwww", "wwwwwwww", "........", "........"],
};
export const ICON_COLORS: Record<string, string> = {
  w: "#ffffff",
  k: "#1b1b2e",
  y: "#f0b43c",
  g: "#5bbf4a",
  r: "#e5534b",
};

export function paintIcon(ctx: CanvasRenderingContext2D, rows: string[], ox: number): void {
  for (let y = 0; y < 8; y++) {
    for (let x = 0; x < 8; x++) {
      const key = rows[y]![x]!;
      if (key === ".") continue;
      ctx.fillStyle = ICON_COLORS[key] ?? "#ff00ff";
      ctx.fillRect(ox + x, y, 1, 1);
    }
  }
}

/**
 * The office interior: original pixel art drawn in code (see assets/MANIFEST.md), in the
 * logo's palette — night navy, cream, meadow greens, sky blue. No Phaser here: everything
 * paints onto a 2D canvas context, once. The scene shows the result as a single image
 * (cheap on phones) plus a few small "props" that must be depth-sorted with the characters
 * (chair backs, sofa and bench fronts, plants, monitors).
 */
import type { Sky } from "./daynight";
import { COLS, DESKS, LAYOUT, ROWS, TILE, tilesOf, WORLD_H, WORLD_W, ZONES } from "./map";

type Ctx = CanvasRenderingContext2D;

export const PAL = {
  outside: "#0c1024",
  navy: "#10142b",
  navy2: "#1d2447",
  navy3: "#2a3566",
  navy4: "#3a4680",
  navy5: "#56639c",
  cream: "#f5ecd6",
  cream2: "#ebdfc2",
  cream3: "#d8c8a2",
  shadow: "rgba(12,16,36,0.24)",
  shadowSoft: "rgba(12,16,36,0.12)",
  // honey wood floor
  wood: "#c8955a",
  woodLight: "#d0a068",
  woodAlt: "#c08c52",
  woodAlt2: "#cc9a60",
  woodSeam: "#ae7f48",
  woodGrain: "#b7864e",
  // furniture
  walnut: "#8a5a3b",
  walnutDark: "#6b4a2f",
  walnutTop: "#b27a4e",
  walnutHi: "#c48c5c",
  birch: "#ead6ab",
  birchHi: "#f6e9c9",
  birchEdge: "#cbb07f",
  birchDark: "#b4966a",
  // meadow
  grass: "#5bbf4a",
  grass2: "#53b443",
  grassDark: "#3f9a35",
  grassLight: "#7ed266",
  // sky and accents
  sky: "#6ec3f5",
  skyLight: "#a9dcfb",
  skyPale: "#dcecf9",
  amber: "#f0b43c",
  coral: "#e8734a",
  red: "#e5534b",
  pink: "#f4a6b8",
  purple: "#9b6bd6",
  mint: "#a6e08a",
  // sofa
  sofa: "#4a8fd6",
  sofaDark: "#3a72b0",
  sofaHi: "#7fb8ec",
  sofaCushion: "#5c9ee0",
};

/** Deterministic noise in [0, 1) for scattered details. */
export function noise(x: number, y: number, seed = 0): number {
  let h = (Math.imul(x, 374761393) + Math.imul(y, 668265263) + Math.imul(seed, 1442695041)) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  return ((h ^ (h >>> 16)) >>> 0) / 4294967296;
}

function rect(ctx: Ctx, color: string, x: number, y: number, w: number, h: number): void {
  ctx.fillStyle = color;
  ctx.fillRect(x, y, w, h);
}

/** A filled pixel disc (no anti-aliasing). */
function disc(ctx: Ctx, color: string, cx: number, cy: number, r: number): void {
  ctx.fillStyle = color;
  for (let dy = -r; dy <= r; dy++) {
    const half = Math.floor(Math.sqrt(r * r - dy * dy + r * 0.8));
    ctx.fillRect(cx - half, cy + dy, half * 2 + 1, 1);
  }
}

/** Paint a character map with a palette ('.' = transparent). */
export function paintMap(ctx: Ctx, rows: string[], colors: Record<string, string>, ox = 0, oy = 0): void {
  rows.forEach((line, y) => {
    for (let x = 0; x < line.length; x++) {
      const key = line[x]!;
      if (key === "." || key === " ") continue;
      ctx.fillStyle = colors[key] ?? "#ff00ff";
      ctx.fillRect(ox + x, oy + y, 1, 1);
    }
  });
}

const at = (col: number, row: number) => LAYOUT[row]?.[col] ?? "#";

// --- the meeting room: cols 28..38, rows 2..8, behind glass partitions ------------------------
const ROOM = { x: 440, y: 32, w: WORLD_W - TILE - 440, h: 9 * TILE - 32 };

// =============================================================================================
// The base layer (one 640×360 image)
// =============================================================================================

export function paintOffice(ctx: Ctx): void {
  rect(ctx, PAL.outside, 0, 0, WORLD_W, WORLD_H);
  paintWoodFloor(ctx, TILE, 2 * TILE, WORLD_W - 2 * TILE, (ROWS - 3) * TILE);
  paintWoodFloor(ctx, 19 * TILE, 21 * TILE, 2 * TILE, TILE); // the doorway
  paintCarpet(ctx);
  paintPasture(ctx);
  paintLoungeRug(ctx);
  paintRunner(ctx);
  paintNorthWall(ctx);
  paintSideWalls(ctx);
  paintOutside(ctx);
  paintPartitions(ctx);
  for (const desk of DESKS) paintDesk(ctx, desk.monitor.col, desk.monitor.row, DESKS.indexOf(desk));
  paintMeetingTable(ctx);
  paintSofa(ctx);
  paintBench(ctx);
}

function paintWoodFloor(ctx: Ctx, x0: number, y0: number, w: number, h: number): void {
  const PLANK = 4;
  const LEN = 32;
  for (let y = y0; y < y0 + h; y += PLANK) {
    const line = Math.floor(y / PLANK);
    const offset = (line * 11) % LEN;
    for (let x = x0 - ((x0 + offset) % LEN); x < x0 + w; x += LEN) {
      const id = Math.floor((x + offset) / LEN);
      const n = noise(id, line, 1);
      const tone = n < 0.33 ? PAL.wood : n < 0.66 ? PAL.woodAlt : PAL.woodAlt2;
      const sx = Math.max(x, x0);
      const ex = Math.min(x + LEN, x0 + w);
      if (ex <= sx) continue;
      rect(ctx, tone, sx, y, ex - sx, PLANK - 1);
      rect(ctx, PAL.woodLight, sx, y, ex - sx, 1);
      rect(ctx, PAL.woodSeam, sx, y + PLANK - 1, ex - sx, 1);
      if (x >= x0) rect(ctx, PAL.woodSeam, x, y, 1, PLANK - 1); // plank end
      // a little grain
      const gx = x + 4 + Math.floor(noise(id, line, 2) * (LEN - 10));
      if (gx >= x0 && gx + 4 <= x0 + w) rect(ctx, PAL.woodGrain, gx, y + 1 + (id % 2), 3 + (id % 3), 1);
    }
  }
}

function paintCarpet(ctx: Ctx): void {
  const { x, y, w, h } = ROOM;
  rect(ctx, "#4b5c9a", x, y, w, h);
  for (let py = y; py < y + h; py += 4) {
    for (let px = x + ((py / 4) % 2) * 2; px < x + w; px += 4) rect(ctx, "#45558f", px, py, 1, 1);
  }
  for (let py = y + 6; py < y + h; py += 12) {
    for (let px = x + 6 + ((py - y) % 24 === 6 ? 0 : 6); px < x + w - 2; px += 12) {
      rect(ctx, "#5b6dab", px, py - 1, 1, 3);
      rect(ctx, "#5b6dab", px - 1, py, 3, 1);
    }
  }
  // the threshold of the south door
  rect(ctx, PAL.navy4, 32 * TILE, 9 * TILE, 3 * TILE, 1);
}

function paintPasture(ctx: Ctx): void {
  const tiles = [...tilesOf("G"), ...tilesOf("H")];
  const isGrass = (c: number, r: number) => at(c, r) === "G" || at(c, r) === "H";
  for (const { col, row: r } of tiles) {
    const x = col * TILE;
    const y = r * TILE;
    rect(ctx, (col + r) % 2 ? PAL.grass : PAL.grass2, x, y, TILE, TILE);
    for (let i = 0; i < 7; i++) {
      const tx = x + Math.floor(noise(col, r, 10 + i) * 15);
      const ty = y + Math.floor(noise(col, r, 20 + i) * 14);
      rect(ctx, i % 3 === 0 ? PAL.grassLight : PAL.grassDark, tx, ty, 1, 2);
      if (i % 2 === 0) rect(ctx, PAL.grassDark, tx + 1, ty + 1, 1, 1);
    }
    const flower = noise(col, r, 30);
    if (flower < 0.55) {
      const fx = x + 3 + Math.floor(noise(col, r, 31) * 10);
      const fy = y + 3 + Math.floor(noise(col, r, 32) * 10);
      const petal = flower < 0.2 ? "#ffffff" : flower < 0.38 ? "#f7d84a" : PAL.pink;
      rect(ctx, petal, fx - 1, fy, 3, 1);
      rect(ctx, petal, fx, fy - 1, 1, 3);
      rect(ctx, flower < 0.2 ? "#f7d84a" : "#ffffff", fx, fy, 1, 1);
    }
    // soft edge where the meadow meets the floor
    if (!isGrass(col, r - 1)) rect(ctx, PAL.grassLight, x, y, TILE, 1);
    if (!isGrass(col, r + 1)) {
      rect(ctx, PAL.grassDark, x, y + TILE - 1, TILE, 1);
      rect(ctx, PAL.shadowSoft, x, y + TILE, TILE, 1);
    }
    if (!isGrass(col - 1, r)) rect(ctx, PAL.grassDark, x, y, 1, TILE);
    if (!isGrass(col + 1, r)) rect(ctx, PAL.grassDark, x + TILE - 1, y, 1, TILE);
  }
  // a water trough for the cow
  const tx = 30 * TILE + 3;
  const ty = 11 * TILE + 3;
  rect(ctx, PAL.shadow, tx + 1, ty + 7, 20, 2);
  rect(ctx, PAL.walnutDark, tx, ty, 20, 7);
  rect(ctx, PAL.walnut, tx + 1, ty + 1, 18, 5);
  rect(ctx, PAL.sky, tx + 2, ty + 2, 16, 3);
  rect(ctx, PAL.skyLight, tx + 3, ty + 2, 6, 1);
}

function paintLoungeRug(ctx: Ctx): void {
  const x = 26;
  const y = 15 * TILE - 2;
  const w = 124;
  const h = 3 * TILE + 2;
  rect(ctx, PAL.shadowSoft, x + 1, y + 1, w, h);
  rect(ctx, PAL.navy3, x, y, w, h);
  rect(ctx, PAL.cream, x + 2, y + 2, w - 4, h - 4);
  rect(ctx, "#6fae5c", x + 4, y + 4, w - 8, 1);
  rect(ctx, "#6fae5c", x + 4, y + h - 5, w - 8, 1);
  rect(ctx, "#6fae5c", x + 4, y + 4, 1, h - 8);
  rect(ctx, "#6fae5c", x + w - 5, y + 4, 1, h - 8);
  // diamonds
  for (let cx = x + 12; cx < x + w - 8; cx += 14) {
    for (let cy = y + 12; cy < y + h - 8; cy += 13) {
      const color = (cx + cy) % 3 === 0 ? PAL.sky : (cx + cy) % 3 === 1 ? PAL.amber : PAL.pink;
      rect(ctx, color, cx, cy - 2, 1, 1);
      rect(ctx, color, cx - 1, cy - 1, 3, 1);
      rect(ctx, color, cx - 2, cy, 5, 1);
      rect(ctx, color, cx - 1, cy + 1, 3, 1);
      rect(ctx, color, cx, cy + 2, 1, 1);
    }
  }
  // tassels
  for (let tx = x + 2; tx < x + w - 2; tx += 3) {
    rect(ctx, PAL.cream3, tx, y - 1, 1, 1);
  }
}

/** A runner from the entrance into the office, as wide as the door. */
function paintRunner(ctx: Ctx): void {
  const x = 19 * TILE + 2;
  const y = 14 * TILE + 2;
  const w = 2 * TILE - 4;
  const h = 21 * TILE - y;
  rect(ctx, PAL.shadowSoft, x + 1, y + 1, w, h);
  rect(ctx, "#6f9f5e", x, y, w, h);
  rect(ctx, "#86b873", x + 2, y + 2, w - 4, h - 2);
  rect(ctx, PAL.cream, x + 3, y + 3, w - 6, 1);
  rect(ctx, PAL.cream, x + 3, y + 3, 1, h - 3);
  rect(ctx, PAL.cream, x + w - 4, y + 3, 1, h - 3);
  for (let py = y + 9; py < y + h - 3; py += 9) {
    const cx = x + Math.floor(w / 2);
    rect(ctx, PAL.cream, cx - 1, py, 2, 1);
    rect(ctx, PAL.cream, cx - 2, py + 1, 4, 1);
    rect(ctx, PAL.cream, cx - 1, py + 2, 2, 1);
  }
  for (let tx = x + 1; tx < x + w - 1; tx += 3) rect(ctx, PAL.cream3, tx, y - 1, 1, 1);
}

function paintNorthWall(ctx: Ctx): void {
  const x0 = TILE;
  const x1 = WORLD_W - TILE;
  // wallpaper: cream in the office, pale sky in the meeting room
  for (let x = x0; x < x1; x++) {
    const inRoom = x >= ROOM.x;
    rect(ctx, inRoom ? PAL.skyPale : PAL.cream, x, 4, 1, 18);
    if (x % 6 === 0) rect(ctx, inRoom ? "#cfe2f2" : PAL.cream2, x, 4, 1, 18);
  }
  rect(ctx, PAL.navy, 0, 0, WORLD_W, 3); // the top of the wall
  rect(ctx, PAL.navy4, x0, 3, x1 - x0, 1);
  // wainscot (meadow green) with panels, rail on top, baseboard below
  rect(ctx, "#86b873", x0, 22, x1 - x0, 7);
  for (let x = x0 + 2; x < x1; x += 12) {
    rect(ctx, "#76a663", x, 24, 9, 1);
    rect(ctx, "#76a663", x, 24, 1, 4);
    rect(ctx, "#9ccb88", x + 1, 27, 9, 1);
    rect(ctx, "#9ccb88", x + 9, 24, 1, 4);
  }
  rect(ctx, PAL.cream, x0, 21, x1 - x0, 1);
  rect(ctx, PAL.cream3, x0, 22, x1 - x0, 1);
  rect(ctx, PAL.walnutDark, x0, 29, x1 - x0, 3);
  rect(ctx, PAL.walnut, x0, 29, x1 - x0, 1);
  // the wall casts a soft shadow on the floor
  rect(ctx, PAL.shadow, x0, 32, x1 - x0, 1);
  rect(ctx, PAL.shadowSoft, x0, 33, x1 - x0, 2);

  for (const run of runs("K", 1)) paintShelf(ctx, run.from * TILE, run.to * TILE + TILE, run.from);
  for (const run of runs("B", 1)) paintBoard(ctx, run.from * TILE, run.to * TILE + TILE);
  for (const run of runs("C", 1)) paintCoffee(ctx, run.from * TILE, run.to * TILE + TILE);
  paintScreen(ctx, 33 * TILE - 4, 6);
}

/** Horizontal runs of a letter in one row. */
function runs(letter: string, r: number): { from: number; to: number }[] {
  const out: { from: number; to: number }[] = [];
  for (let c = 0; c < COLS; c++) {
    if (at(c, r) !== letter) continue;
    const from = c;
    while (at(c + 1, r) === letter) c++;
    out.push({ from, to: c });
  }
  return out;
}

const BOOKS = [PAL.coral, PAL.sky, PAL.amber, "#5bbf4a", PAL.purple, PAL.cream, PAL.navy4, PAL.red, PAL.pink];

function paintShelf(ctx: Ctx, x0: number, x1: number, seed: number): void {
  const w = x1 - x0;
  rect(ctx, PAL.walnutDark, x0 + 1, 3, w - 2, 29);
  rect(ctx, PAL.walnutHi, x0 + 1, 3, w - 2, 1);
  rect(ctx, "#3e2a1d", x0 + 3, 5, w - 6, 25);
  for (const shelfY of [12, 20, 28]) {
    const top = shelfY - 7;
    let x = x0 + 3;
    let i = 0;
    while (x < x1 - 4) {
      const n = noise(x, shelfY, seed);
      i++;
      if (n < 0.08 && x < x1 - 10) {
        // a little potted plant between the books
        rect(ctx, PAL.coral, x + 1, shelfY - 3, 4, 3);
        rect(ctx, "#5bbf4a", x, shelfY - 6, 6, 3);
        rect(ctx, PAL.grassDark, x + 2, shelfY - 7, 2, 1);
        x += 7;
        continue;
      }
      const bw = n < 0.5 ? 2 : 3;
      const bh = 5 + Math.floor(noise(x, shelfY, seed + 7) * 3);
      const color = BOOKS[Math.floor(noise(x, i, seed + 3) * BOOKS.length)]!;
      if (n > 0.93) {
        // a leaning book
        rect(ctx, color, x, shelfY - 4, 3, 4);
        rect(ctx, color, x + 1, shelfY - 6, 3, 2);
        x += 4;
        continue;
      }
      rect(ctx, color, x, Math.max(top, shelfY - bh), bw, Math.min(bh, 7));
      rect(ctx, "rgba(255,255,255,0.25)", x, Math.max(top, shelfY - bh) + 1, 1, 1);
      x += bw + (n > 0.85 ? 1 : 0);
    }
    rect(ctx, PAL.walnutTop, x0 + 2, shelfY, w - 4, 1);
    rect(ctx, PAL.walnut, x0 + 2, shelfY + 1, w - 4, 1);
  }
  // sides
  rect(ctx, PAL.walnut, x0 + 1, 4, 2, 28);
  rect(ctx, PAL.walnut, x1 - 3, 4, 2, 28);
}

function paintBoard(ctx: Ctx, x0: number, x1: number): void {
  const w = x1 - x0;
  rect(ctx, PAL.navy3, x0 + 2, 5, w - 4, 20);
  rect(ctx, "#fbf6e8", x0 + 3, 6, w - 6, 18);
  const cols = 3;
  const cw = Math.floor((w - 6) / cols);
  const heads = [PAL.sky, PAL.amber, "#5bbf4a"];
  const notes = ["#f7d84a", PAL.pink, PAL.mint, PAL.skyLight];
  for (let i = 0; i < cols; i++) {
    const cx = x0 + 3 + i * cw;
    rect(ctx, heads[i]!, cx + 2, 7, cw - 4, 2);
    if (i > 0) rect(ctx, PAL.cream3, cx, 7, 1, 16);
    const count = [4, 3, 3][i]!;
    for (let k = 0; k < count; k++) {
      const nx = cx + 3 + (k % 2) * Math.floor((cw - 4) / 2);
      const ny = 11 + Math.floor(k / 2) * 6;
      const color = notes[(i * 2 + k) % notes.length]!;
      rect(ctx, color, nx, ny, 9, 5);
      rect(ctx, "rgba(0,0,0,0.12)", nx, ny + 4, 9, 1);
      rect(ctx, "rgba(16,20,43,0.55)", nx + 1, ny + 1, 5 + ((k + i) % 3), 1);
      rect(ctx, "rgba(16,20,43,0.35)", nx + 1, ny + 3, 4, 1);
      if (i === 2) {
        // done: a green tick
        rect(ctx, "#2f8f2a", nx + 6, ny + 2, 1, 1);
        rect(ctx, "#2f8f2a", nx + 7, ny + 1, 1, 1);
      }
    }
  }
  // marker tray
  rect(ctx, PAL.navy3, x0 + 8, 25, w - 16, 2);
  rect(ctx, PAL.red, x0 + 12, 24, 4, 1);
  rect(ctx, PAL.sky, x0 + 18, 24, 4, 1);
}

function paintCoffee(ctx: Ctx, x0: number, x1: number): void {
  const w = x1 - x0;
  // a shelf with mugs
  rect(ctx, PAL.walnutTop, x0 + 4, 10, 30, 1);
  rect(ctx, PAL.walnutDark, x0 + 4, 11, 30, 1);
  const mugs = [PAL.cream, PAL.pink, PAL.sky, PAL.amber, PAL.cream];
  mugs.forEach((color, i) => {
    rect(ctx, color, x0 + 6 + i * 6, 7, 3, 3);
    rect(ctx, color, x0 + 9 + i * 6, 8, 1, 1);
  });
  // counter: birch top, navy cabinets with cream handles
  rect(ctx, PAL.navy3, x0 + 2, 21, w - 4, 11);
  for (let x = x0 + 2; x < x1 - 4; x += 15) {
    rect(ctx, PAL.navy2, x + 14, 22, 1, 10);
    rect(ctx, PAL.cream, x + 11, 25, 1, 3);
  }
  rect(ctx, PAL.birchEdge, x0 + 1, 20, w - 2, 2);
  rect(ctx, PAL.birchHi, x0 + 1, 19, w - 2, 1);
  // the coffee machine
  const mx = x0 + 5;
  rect(ctx, PAL.shadow, mx + 1, 18, 13, 1);
  rect(ctx, "#c9ccd8", mx, 9, 12, 10);
  rect(ctx, "#e6e8f0", mx, 9, 12, 2);
  rect(ctx, PAL.navy3, mx + 2, 12, 8, 3);
  rect(ctx, "#5bbf4a", mx + 3, 13, 1, 1);
  rect(ctx, PAL.red, mx + 5, 13, 1, 1);
  rect(ctx, PAL.navy, mx + 5, 15, 2, 1);
  rect(ctx, PAL.cream, mx + 4, 17, 4, 2);
  // steam (static)
  rect(ctx, "rgba(255,255,255,0.7)", mx + 5, 15, 1, 1);
  // kettle, fruit bowl, a tiny plant
  rect(ctx, PAL.coral, x0 + 22, 14, 5, 5);
  rect(ctx, PAL.coral, x0 + 27, 15, 1, 2);
  rect(ctx, PAL.navy2, x0 + 23, 13, 3, 1);
  rect(ctx, PAL.cream, x0 + 31, 16, 10, 3);
  rect(ctx, PAL.red, x0 + 32, 14, 3, 2);
  rect(ctx, "#5bbf4a", x0 + 35, 14, 3, 2);
  rect(ctx, PAL.amber, x0 + 38, 15, 2, 1);
  rect(ctx, PAL.cream, x1 - 13, 15, 5, 4);
  rect(ctx, "#5bbf4a", x1 - 14, 11, 3, 4);
  rect(ctx, "#5bbf4a", x1 - 11, 10, 3, 5);
  rect(ctx, PAL.grassDark, x1 - 12, 12, 1, 3);
}

/** The meeting room's wall screen with a little chart. */
function paintScreen(ctx: Ctx, x: number, y: number): void {
  rect(ctx, PAL.shadowSoft, x + 1, y + 16, 46, 1);
  rect(ctx, PAL.navy, x, y, 46, 16);
  rect(ctx, PAL.navy3, x + 1, y + 1, 44, 14);
  const bars = [5, 8, 6, 10, 9, 12];
  bars.forEach((h, i) => {
    rect(ctx, i === bars.length - 1 ? "#5bbf4a" : PAL.sky, x + 5 + i * 6, y + 13 - h, 4, h);
  });
  rect(ctx, PAL.amber, x + 4, y + 4, 2, 1);
  rect(ctx, PAL.cream, x + 7, y + 4, 8, 1);
  rect(ctx, PAL.navy5, x + 3, y + 13, 40, 1);
}

function paintSideWalls(ctx: Ctx): void {
  // west and east walls seen from above, south wall with the entrance
  rect(ctx, PAL.navy, 0, 0, TILE, ROWS * TILE);
  rect(ctx, PAL.navy, WORLD_W - TILE, 0, TILE, ROWS * TILE);
  rect(ctx, PAL.navy3, TILE - 2, 3, 2, ROWS * TILE - 19);
  rect(ctx, PAL.navy3, WORLD_W - TILE, 3, 2, ROWS * TILE - 19);
  rect(ctx, PAL.shadowSoft, TILE, 32, 2, ROWS * TILE - 48);
  const south = (ROWS - 1) * TILE;
  for (let c = 0; c < COLS; c++) {
    if (at(c, ROWS - 1) !== "#") continue;
    rect(ctx, PAL.navy, c * TILE, south, TILE, TILE);
    if (c > 0 && c < COLS - 1) rect(ctx, PAL.navy3, c * TILE, south, TILE, 2);
  }
  // the entrance: door frame and a mat
  const dx = 19 * TILE;
  rect(ctx, PAL.cream3, dx - 2, south, 2, TILE);
  rect(ctx, PAL.cream3, dx + 2 * TILE, south, 2, TILE);
  rect(ctx, "#b5523b", dx + 3, south + 2, 2 * TILE - 6, 11);
  rect(ctx, "#cf6a4f", dx + 4, south + 3, 2 * TILE - 8, 9);
  for (let x = dx + 6; x < dx + 2 * TILE - 6; x += 3) rect(ctx, "#b5523b", x, south + 5, 1, 5);

  // the meadow gate in the east wall, next to the pasture: an opening onto the grass
  const gy = 11 * TILE;
  const gx = WORLD_W - TILE;
  rect(ctx, PAL.grass, gx, gy, TILE, 3 * TILE);
  for (let i = 0; i < 9; i++) {
    rect(ctx, PAL.grassDark, gx + 3 + Math.floor(noise(i, 5, 40) * 10), gy + 3 + i * 5, 1, 2);
  }
  rect(ctx, "#f7d84a", gx + 9, gy + 13, 1, 1);
  rect(ctx, "#ffffff", gx + 5, gy + 33, 1, 1);
  // wall ends with cream gate posts
  rect(ctx, PAL.navy3, gx, gy - 3, TILE, 3);
  rect(ctx, PAL.navy5, gx, gy - 1, TILE, 1);
  rect(ctx, PAL.navy3, gx, gy + 3 * TILE, TILE, 3);
  rect(ctx, PAL.cream, gx + 1, gy - 4, 3, 4);
  rect(ctx, PAL.cream, gx + 1, gy + 3 * TILE, 3, 4);
  rect(ctx, PAL.cream3, gx + 1, gy - 1, 3, 1);
}

function paintOutside(ctx: Ctx): void {
  // the strip below the south wall: the meadow outside, a path from the door
  const y = ROWS * TILE;
  rect(ctx, PAL.grass2, 0, y, WORLD_W, WORLD_H - y);
  for (let x = 2; x < WORLD_W; x += 7) rect(ctx, PAL.grassDark, x + Math.floor(noise(x, 1, 50) * 4), y + 2 + (x % 3), 1, 2);
  rect(ctx, PAL.cream3, 19 * TILE + 2, y, 2 * TILE - 4, WORLD_H - y);
  rect(ctx, PAL.cream2, 19 * TILE + 4, y + 1, 10, 3);
  rect(ctx, PAL.cream2, 19 * TILE + 17, y + 4, 10, 3);
}

function paintPartitions(ctx: Ctx): void {
  // vertical glass walls (col 27) seen from above: a slim frame
  for (let r = 2; r < 9; r++) {
    if (at(27, r) !== "#") continue;
    const y = r * TILE;
    rect(ctx, PAL.navy3, 437, y, 6, TILE);
    rect(ctx, PAL.navy5, 437, y, 1, TILE);
    rect(ctx, "rgba(169,220,251,0.6)", 439, y, 2, TILE);
    rect(ctx, PAL.shadowSoft, 443, y, 2, TILE);
    if (at(27, r + 1) !== "#") {
      // the end of the wall faces us
      rect(ctx, PAL.navy2, 437, y + TILE - 4, 6, 4);
      rect(ctx, PAL.shadow, 437, y + TILE, 7, 2);
    }
    if (at(27, r - 1) !== "#") rect(ctx, PAL.navy5, 437, y, 6, 1);
  }
  // the south glass wall of the meeting room (row 9), facing us
  const y = 9 * TILE;
  for (let c = 27; c < COLS - 1; c++) {
    if (at(c, 9) !== "#") continue;
    const x = c === 27 ? 437 : c * TILE;
    const w = c === 27 ? TILE - 5 : TILE;
    rect(ctx, PAL.navy3, x, y, w, 4);
    rect(ctx, PAL.navy5, x, y, w, 1);
    rect(ctx, "rgba(169,220,251,0.55)", x, y + 4, w, 10);
    rect(ctx, "rgba(255,255,255,0.45)", x + (c % 3) + 3, y + 6, 1, 3);
    rect(ctx, "rgba(255,255,255,0.45)", x + (c % 3) + 4, y + 5, 1, 2);
    rect(ctx, PAL.navy3, x, y + 14, w, 2);
    if (c % 2 === 0) rect(ctx, PAL.navy3, x, y + 4, 1, 10);
    rect(ctx, PAL.shadow, x, y + 16, w, 2);
  }
  // door posts of the meeting room
  rect(ctx, PAL.navy2, 32 * TILE - 1, y, 2, TILE);
  rect(ctx, PAL.navy2, 35 * TILE - 1, y, 2, TILE);
}

/** Desk `index` decides the small things on it. Monitor and chair back are props. */
function paintDesk(ctx: Ctx, col: number, r: number, index: number): void {
  const x = col * TILE;
  const y = r * TILE;
  // shadow, legs, top, front lip, drawers
  rect(ctx, PAL.shadow, x + 1, y + 14, 32, 2);
  rect(ctx, PAL.navy3, x + 1, y + 10, 2, 5);
  rect(ctx, PAL.navy3, x + 29, y + 10, 2, 5);
  rect(ctx, PAL.birchDark, x + 18, y + 10, 10, 5);
  rect(ctx, PAL.birchEdge, x + 18, y + 10, 10, 1);
  rect(ctx, PAL.walnutDark, x + 21, y + 12, 4, 1);
  rect(ctx, PAL.birch, x, y + 2, 32, 7);
  rect(ctx, PAL.birchHi, x, y + 2, 32, 1);
  rect(ctx, PAL.birchEdge, x, y + 9, 32, 1);
  rect(ctx, PAL.birchDark, x, y + 10, 32, 1);
  // keyboard and mouse in front of the monitor
  rect(ctx, "#c3c8da", x + 3, y + 7, 10, 2);
  rect(ctx, "#e4e7f0", x + 4, y + 7, 8, 1);
  rect(ctx, "#c3c8da", x + 14, y + 7, 2, 2);
  // the right half: papers and a mug (the pet sits in between)
  rect(ctx, "#ffffff", x + 17, y + 4, 4, 3);
  rect(ctx, PAL.cream3, x + 17, y + 6, 4, 1);
  const mug = [PAL.coral, PAL.sky, PAL.amber, PAL.cream, PAL.pink][index % 5]!;
  rect(ctx, mug, x + 28, y + 4, 3, 3);
  rect(ctx, mug, x + 27, y + 5, 1, 1);
  // the empty office chair at the seat below (its back is a prop above the sitter)
  const sx = x;
  const sy = y + TILE;
  rect(ctx, PAL.shadowSoft, sx + 3, sy + 13, 11, 2);
  rect(ctx, PAL.navy, sx + 4, sy + 13, 8, 1);
  rect(ctx, PAL.navy, sx + 3, sy + 14, 2, 1);
  rect(ctx, PAL.navy, sx + 11, sy + 14, 2, 1);
  rect(ctx, PAL.navy2, sx + 7, sy + 11, 2, 2);
  rect(ctx, PAL.navy4, sx + 3, sy + 8, 10, 3);
  rect(ctx, PAL.navy5, sx + 3, sy + 8, 10, 1);
}

function paintMeetingTable(ctx: Ctx): void {
  const tiles = tilesOf("T");
  const x = Math.min(...tiles.map((t) => t.col)) * TILE;
  const y = Math.min(...tiles.map((t) => t.row)) * TILE;
  const w = (Math.max(...tiles.map((t) => t.col)) + 1) * TILE - x;
  const h = (Math.max(...tiles.map((t) => t.row)) + 1) * TILE - y;
  // chairs on the north side (behind the people sitting there)
  for (const spot of ZONES.meeting.filter((s) => s.facing === "down")) {
    const cx = spot.col * TILE;
    const cy = spot.row * TILE;
    rect(ctx, PAL.shadowSoft, cx + 3, cy + 13, 11, 2);
    rect(ctx, PAL.navy, cx + 4, cy + 1, 8, 1);
    rect(ctx, PAL.navy4, cx + 3, cy + 2, 10, 6);
    rect(ctx, PAL.navy5, cx + 4, cy + 2, 8, 1);
    rect(ctx, PAL.navy2, cx + 3, cy + 8, 10, 1);
    rect(ctx, PAL.navy4, cx + 3, cy + 9, 10, 3);
    rect(ctx, PAL.navy5, cx + 3, cy + 9, 10, 1);
    rect(ctx, PAL.navy, cx + 4, cy + 12, 2, 2);
    rect(ctx, PAL.navy, cx + 10, cy + 12, 2, 2);
  }
  // seat cushions of the south chairs (their backs are props)
  for (const spot of ZONES.meeting.filter((s) => s.facing === "up")) {
    const cx = spot.col * TILE;
    const cy = spot.row * TILE;
    rect(ctx, PAL.shadowSoft, cx + 3, cy + 13, 11, 2);
    rect(ctx, PAL.navy4, cx + 3, cy + 8, 10, 3);
    rect(ctx, PAL.navy2, cx + 7, cy + 11, 2, 2);
  }
  rect(ctx, PAL.shadow, x + 3, y + h - 1, w - 2, 3);
  rect(ctx, PAL.walnutDark, x + 2, y + h - 6, 3, 6);
  rect(ctx, PAL.walnutDark, x + w - 5, y + h - 6, 3, 6);
  rect(ctx, PAL.walnutDark, x + 1, y + 2, w - 2, h - 7);
  rect(ctx, PAL.walnutTop, x + 2, y + 3, w - 4, h - 10);
  rect(ctx, PAL.walnutHi, x + 2, y + 3, w - 4, 1);
  rect(ctx, PAL.walnut, x + 1, y + h - 6, w - 2, 2);
  // things on the table: laptops, papers, a vase
  const items: [number, number][] = [
    [8, 6],
    [30, 6],
    [52, 6],
    [18, 26],
    [44, 26],
    [64, 26],
  ];
  items.forEach(([ix, iy], i) => {
    if (i % 2 === 0) {
      rect(ctx, PAL.navy3, x + ix, y + iy, 9, 6);
      rect(ctx, i === 2 ? PAL.sky : PAL.navy4, x + ix + 1, y + iy + 1, 7, 4);
      rect(ctx, "#c3c8da", x + ix, y + iy + 6, 9, 2);
    } else {
      rect(ctx, "#ffffff", x + ix, y + iy + 1, 7, 5);
      rect(ctx, PAL.cream3, x + ix + 1, y + iy + 2, 4, 1);
      rect(ctx, PAL.cream3, x + ix + 1, y + iy + 4, 3, 1);
    }
  });
  const vx = x + Math.floor(w / 2) - 2;
  const vy = y + Math.floor(h / 2) - 6;
  rect(ctx, PAL.cream, vx, vy + 4, 5, 5);
  rect(ctx, PAL.sky, vx, vy + 6, 5, 1);
  disc(ctx, "#5bbf4a", vx + 2, vy + 2, 2);
  rect(ctx, PAL.pink, vx + 1, vy + 1, 1, 1);
  rect(ctx, "#f7d84a", vx + 3, vy, 1, 1);
}

function paintSofa(ctx: Ctx): void {
  const tiles = tilesOf("S");
  if (tiles.length === 0) return;
  const x = tiles[0]!.col * TILE;
  const y = tiles[0]!.row * TILE;
  const w = tiles.length * TILE;
  rect(ctx, PAL.shadow, x - 4, y + 17, w + 10, 3);
  // backrest
  rect(ctx, PAL.sofaDark, x - 2, y - 6, w + 4, 9);
  rect(ctx, PAL.sofa, x - 2, y - 5, w + 4, 6);
  rect(ctx, PAL.sofaHi, x - 2, y - 6, w + 4, 1);
  for (let i = 1; i < tiles.length; i++) rect(ctx, PAL.sofaDark, x + i * TILE, y - 4, 1, 5);
  // seat cushions (their fronts are the prop)
  for (let i = 0; i < tiles.length; i++) {
    rect(ctx, PAL.sofaCushion, x + i * TILE, y + 3, TILE, 5);
    rect(ctx, PAL.sofaHi, x + i * TILE + 1, y + 3, TILE - 2, 1);
    rect(ctx, PAL.sofaDark, x + i * TILE, y + 3, 1, 5);
  }
  // armrests
  for (const ax of [x - 6, x + w]) {
    rect(ctx, PAL.sofaDark, ax, y - 3, 6, 18);
    rect(ctx, PAL.sofa, ax + 1, y - 3, 4, 16);
    rect(ctx, PAL.sofaHi, ax + 1, y - 3, 4, 1);
  }
  // cushions thrown on it
  rect(ctx, PAL.amber, x + 3, y - 3, 7, 6);
  rect(ctx, "#f7cf6a", x + 4, y - 2, 5, 1);
  rect(ctx, PAL.cream, x + w - 11, y - 3, 7, 6);
  rect(ctx, PAL.pink, x + w - 9, y - 1, 3, 2);
}

function paintBench(ctx: Ctx): void {
  const tiles = tilesOf("b");
  if (tiles.length === 0) return;
  const x = tiles[0]!.col * TILE;
  const y = tiles[0]!.row * TILE;
  const w = tiles.length * TILE;
  rect(ctx, PAL.shadow, x - 1, y + 15, w + 3, 3);
  // backrest slats on posts
  for (let px = x + 2; px < x + w; px += 24) rect(ctx, PAL.walnutDark, px, y - 5, 2, 9);
  rect(ctx, PAL.walnut, x, y - 5, w, 3);
  rect(ctx, PAL.walnutHi, x, y - 5, w, 1);
  rect(ctx, PAL.walnut, x, y - 1, w, 2);
  rect(ctx, PAL.walnutHi, x, y - 1, w, 1);
  // seat (its front is the prop)
  rect(ctx, PAL.walnutTop, x, y + 2, w, 4);
  rect(ctx, PAL.walnutHi, x, y + 2, w, 1);
  for (let px = x + 8; px < x + w; px += 16) rect(ctx, PAL.walnut, px, y + 3, 1, 3);
}

// =============================================================================================
// Windows and the clock: they follow the time of day, so they live on their own layer
// =============================================================================================

export const WINDOWS: { x: number; w: number; cow?: boolean }[] = [
  { x: 2 * TILE + 2, w: 76, cow: true },
  { x: 23 * TILE + 4, w: 56 },
  { x: 36 * TILE + 2, w: 44, cow: false },
];
export const CLOCK = { x: 15 * TILE + 4, y: 18 };

const hex = (n: number) => `#${n.toString(16).padStart(6, "0")}`;

export function paintWindows(ctx: Ctx, sky: Sky, hour: number): void {
  ctx.clearRect(0, 0, WORLD_W, WORLD_H);
  WINDOWS.forEach((win, i) => paintWindow(ctx, win.x, 5, win.w, 15, sky, i, win.cow ?? false));
  paintClock(ctx, hour);
  if (sky.phase === "day" || sky.phase === "dawn") {
    // sunlight falling through the windows onto the floor
    ctx.fillStyle = sky.phase === "day" ? "rgba(255,246,214,0.13)" : "rgba(255,190,140,0.12)";
    for (const win of WINDOWS) {
      for (let k = 0; k < 18; k++) {
        const x = win.x + 2 + k;
        ctx.fillRect(x, 35 + k, Math.min(win.w - 4, WORLD_W - TILE - x), 1);
      }
    }
  }
}

function paintWindow(ctx: Ctx, x: number, y: number, w: number, h: number, sky: Sky, seed: number, cow: boolean): void {
  rect(ctx, PAL.navy3, x - 1, y - 1, w + 2, h + 2);
  rect(ctx, PAL.cream, x, y, w, h);
  const gx = x + 2;
  const gy = y + 2;
  const gw = w - 4;
  const gh = h - 4;
  rect(ctx, hex(sky.sky[0]), gx, gy, gw, Math.ceil(gh / 2));
  rect(ctx, hex(sky.sky[1]), gx, gy + Math.ceil(gh / 2), gw, Math.floor(gh / 2));
  if (sky.stars) {
    for (let i = 0; i < Math.floor(gw / 7); i++) {
      rect(ctx, "#ffffff", gx + Math.floor(noise(i, seed, 60) * gw), gy + Math.floor(noise(i, seed, 61) * (gh - 4)), 1, 1);
    }
  } else {
    // clouds
    for (let i = 0; i < Math.max(1, Math.floor(gw / 30)); i++) {
      const cx = gx + 3 + Math.floor(noise(i, seed, 62) * (gw - 12));
      const cy = gy + 1 + Math.floor(noise(i, seed, 63) * 3);
      rect(ctx, "rgba(255,255,255,0.85)", cx, cy + 1, 8, 2);
      rect(ctx, "rgba(255,255,255,0.85)", cx + 2, cy, 4, 1);
    }
  }
  if (seed === 1 && (sky.sun || sky.moon)) {
    const sx = gx + gw - 9;
    if (sky.sun) {
      rect(ctx, "#ffd34a", sx, gy + 1, 3, 3);
      rect(ctx, "#fff2a8", sx + 1, gy + 1, 1, 1);
    } else {
      rect(ctx, PAL.cream, sx, gy + 1, 3, 3);
      rect(ctx, hex(sky.sky[0]), sx + 1, gy + 1, 2, 2);
    }
  }
  // rolling hills of the logo's meadow
  const hill = hex(sky.hill);
  rect(ctx, hill, gx, gy + gh - 2, gw, 2);
  for (let i = 0; i < gw; i += 9) {
    const bump = 1 + Math.floor(noise(i, seed, 64) * 2);
    rect(ctx, hill, gx + i, gy + gh - 2 - bump, 7, bump);
  }
  if (cow) {
    const cx = gx + 8;
    const cy = gy + gh - 5;
    rect(ctx, "#ffffff", cx, cy, 4, 2);
    rect(ctx, "#1b1b2e", cx + 1, cy, 1, 1);
    rect(ctx, "#ffffff", cx + 4, cy - 1, 1, 2);
    rect(ctx, "#f2a898", cx + 5, cy, 1, 1);
    rect(ctx, "#1b1b2e", cx, cy + 2, 1, 1);
    rect(ctx, "#1b1b2e", cx + 3, cy + 2, 1, 1);
  }
  // glazing bars and a highlight
  for (let mx = x + Math.floor(w / 2); mx < x + w; mx += w) rect(ctx, PAL.cream, mx, y, 1, h);
  if (w > 60) {
    rect(ctx, PAL.cream, x + Math.floor(w / 4), y, 1, h);
    rect(ctx, PAL.cream, x + Math.floor((3 * w) / 4), y, 1, h);
  }
  rect(ctx, "rgba(255,255,255,0.35)", gx + 1, gy + 1, 1, 3);
  // sill
  rect(ctx, PAL.cream, x - 2, y + h, w + 4, 2);
  rect(ctx, PAL.cream3, x - 2, y + h + 2, w + 4, 1);
}

/** The wall clock shows the owner's hour (the office is told the hour; it reads no clock). */
function paintClock(ctx: Ctx, hour: number): void {
  const { x, y } = CLOCK;
  disc(ctx, PAL.navy3, x, y - 7, 5);
  disc(ctx, PAL.cream, x, y - 7, 4);
  const cy = y - 7;
  rect(ctx, PAL.navy, x, cy - 3, 1, 1);
  rect(ctx, PAL.navy, x + 3, cy, 1, 1);
  rect(ctx, PAL.navy, x, cy + 3, 1, 1);
  rect(ctx, PAL.navy, x - 3, cy, 1, 1);
  // minute hand at 12, hour hand by the hour
  rect(ctx, PAL.navy3, x, cy - 3, 1, 3);
  const angle = (((hour % 12) + 12) % 12) * (Math.PI / 6);
  for (let k = 1; k <= 2; k++) {
    rect(ctx, PAL.red, x + Math.round(Math.sin(angle) * k), cy - Math.round(Math.cos(angle) * k), 1, 1);
  }
  rect(ctx, PAL.navy, x, cy, 1, 1);
}

// =============================================================================================
// Props: small images sorted by depth together with the characters
// =============================================================================================

export interface PropArt {
  w: number;
  h: number;
  paint: (ctx: Ctx) => void;
}

const CHAIR_BACK = [
  ".hhhhhhhhhh.",
  "hBBBBBBBBBBh",
  "hBBBBBBBBBBh",
  "hBBBBBBBBBBh",
  ".BBBBBBBBBB.",
  "....nnnn....",
];

const MONITOR = [
  ".oooooooooooooo.",
  "oSSSSSSSSSSSSSSo",
  "oSSSSSSSSSSSSSSo",
  "oSSSSSSSSSSSSSSo",
  "oSSSSSSSSSSSSSSo",
  "oSSSSSSSSSSSSSSo",
  "oSSSSSSSSSSSSSSo",
  ".oooooooooooooo.",
  "......oooo......",
  ".....nnnnnn.....",
];
export const MONITOR_W = 16;
export const MONITOR_H = MONITOR.length;

/** Code on a working screen; (ox, oy) = the monitor's top-left. */
function paintCode(ctx: Ctx, ox: number, oy: number): void {
  const lines: [number, number, string][] = [
    [2, 6, PAL.navy],
    [4, 5, "#ffffff"],
    [4, 3, PAL.amber],
    [2, 8, "#ffffff"],
    [6, 4, PAL.navy],
  ];
  rect(ctx, PAL.skyLight, ox + 1, oy + 1, 14, 1);
  lines.forEach(([x, w, color], i) => rect(ctx, color, ox + x, oy + 2 + i, w, 1));
}

function paintMonitor(ctx: Ctx, on: boolean): void {
  paintMap(ctx, MONITOR, { o: PAL.navy, n: PAL.navy2, S: on ? PAL.sky : "#28305a" }, 0, 0);
  if (on) paintCode(ctx, 0, 0);
  else {
    rect(ctx, "#36406e", 3, 2, 1, 1);
    rect(ctx, "#36406e", 2, 3, 1, 1);
    rect(ctx, "#36406e", 11, 5, 3, 1);
  }
}

function paintPlant(ctx: Ctx, kind: number): void {
  // 16×24, the pot stands on the bottom of the tile
  if (kind === 0) {
    rect(ctx, PAL.shadow, 3, 22, 11, 2);
    rect(ctx, PAL.coral, 4, 15, 8, 8);
    rect(ctx, "#f08f68", 3, 14, 10, 2);
    rect(ctx, "#c85a35", 5, 21, 6, 1);
    disc(ctx, PAL.grassDark, 8, 8, 6);
    disc(ctx, "#5bbf4a", 6, 7, 4);
    disc(ctx, "#5bbf4a", 10, 9, 4);
    disc(ctx, PAL.grassLight, 7, 5, 2);
    rect(ctx, PAL.grassLight, 11, 7, 1, 1);
  } else if (kind === 1) {
    // a tall snake plant in a cream pot
    rect(ctx, PAL.shadow, 3, 22, 11, 2);
    rect(ctx, PAL.cream, 4, 15, 8, 8);
    rect(ctx, PAL.navy3, 4, 18, 8, 1);
    rect(ctx, PAL.cream3, 4, 22, 8, 1);
    const leaves: [number, number][] = [
      [5, 4],
      [7, 1],
      [9, 3],
      [11, 6],
      [4, 8],
    ];
    for (const [lx, top] of leaves) {
      rect(ctx, "#3f8f32", lx, top, 2, 15 - top);
      rect(ctx, PAL.grassLight, lx, top + 1, 1, 15 - top - 2);
    }
  } else {
    // a round cactus with a pink flower
    rect(ctx, PAL.shadow, 3, 22, 11, 2);
    rect(ctx, PAL.navy3, 4, 17, 8, 6);
    rect(ctx, PAL.navy4, 4, 17, 8, 1);
    disc(ctx, "#4aa85a", 8, 12, 4);
    rect(ctx, "#6fc77a", 6, 10, 1, 4);
    rect(ctx, "#6fc77a", 9, 9, 1, 5);
    rect(ctx, PAL.pink, 7, 7, 3, 2);
    rect(ctx, "#ffffff", 8, 7, 1, 1);
  }
}

export const PROP_ART: Record<string, PropArt> = {
  "chair-back": {
    w: 12,
    h: CHAIR_BACK.length,
    paint: (ctx) => paintMap(ctx, CHAIR_BACK, { h: PAL.navy5, B: PAL.navy4, n: PAL.navy2 }),
  },
  "monitor-on": { w: MONITOR_W, h: MONITOR_H, paint: (ctx) => paintMonitor(ctx, true) },
  "monitor-off": { w: MONITOR_W, h: MONITOR_H, paint: (ctx) => paintMonitor(ctx, false) },
  "monitor-glow": {
    w: 28,
    h: 20,
    paint: (ctx) => {
      // light from a working screen at night (drawn above the night shade): the screen and
      // a soft halo around it, kept off the person sitting in front of it
      rect(ctx, "rgba(110,195,245,0.14)", 3, 0, 22, 11);
      rect(ctx, "rgba(110,195,245,0.22)", 5, 1, 18, 8);
      rect(ctx, PAL.sky, 7, 2, 14, 6);
      paintCode(ctx, 6, 1);
    },
  },
  "sofa-front": {
    w: tilesOf("S").length * TILE + 12,
    h: 12,
    paint: (ctx) => {
      const w = tilesOf("S").length * TILE;
      for (let i = 0; i < tilesOf("S").length; i++) {
        rect(ctx, PAL.sofaCushion, 6 + i * TILE, 0, TILE, 3);
        rect(ctx, PAL.sofaDark, 6 + i * TILE, 0, 1, 3);
      }
      rect(ctx, PAL.sofaDark, 6, 3, w, 1);
      rect(ctx, PAL.sofa, 6, 4, w, 5);
      rect(ctx, PAL.sofaDark, 6, 9, w, 1);
      for (const ax of [0, w + 6]) {
        rect(ctx, PAL.sofaDark, ax, 0, 6, 10);
        rect(ctx, PAL.sofa, ax + 1, 0, 4, 8);
      }
      rect(ctx, PAL.navy, 2, 10, 2, 2);
      rect(ctx, PAL.navy, w + 8, 10, 2, 2);
    },
  },
  "bench-front": {
    w: tilesOf("b").length * TILE,
    h: 11,
    paint: (ctx) => {
      const w = tilesOf("b").length * TILE;
      rect(ctx, PAL.walnutTop, 0, 0, w, 2);
      rect(ctx, PAL.walnut, 0, 2, w, 3);
      rect(ctx, PAL.walnutDark, 0, 5, w, 1);
      for (let px = 2; px < w; px += 24) {
        rect(ctx, PAL.walnutDark, px, 6, 2, 5);
      }
      rect(ctx, PAL.walnutDark, w - 4, 6, 2, 5);
    },
  },
  "plant-0": { w: 16, h: 24, paint: (ctx) => paintPlant(ctx, 0) },
  "plant-1": { w: 16, h: 24, paint: (ctx) => paintPlant(ctx, 1) },
  "plant-2": { w: 16, h: 24, paint: (ctx) => paintPlant(ctx, 2) },
  hay: {
    w: 16,
    h: 16,
    paint: (ctx) => {
      rect(ctx, PAL.shadow, 1, 14, 15, 2);
      rect(ctx, "#c99a3a", 1, 3, 14, 12);
      rect(ctx, "#f0c93c", 1, 3, 14, 3);
      rect(ctx, "#e0b442", 1, 6, 14, 1);
      for (let i = 0; i < 6; i++) rect(ctx, "#f7dc72", 2 + Math.floor(noise(i, 1, 70) * 12), 7 + (i % 3) * 2, 2, 1);
      rect(ctx, PAL.walnut, 5, 3, 1, 12);
      rect(ctx, PAL.walnut, 10, 3, 1, 12);
      rect(ctx, "#f7dc72", 3, 2, 1, 1);
      rect(ctx, "#f7dc72", 12, 2, 1, 1);
    },
  },
  cooler: {
    w: 12,
    h: 26,
    paint: (ctx) => {
      rect(ctx, PAL.shadow, 1, 24, 11, 2);
      rect(ctx, PAL.skyLight, 3, 0, 6, 8);
      rect(ctx, PAL.sky, 3, 5, 6, 3);
      rect(ctx, "#ffffff", 4, 1, 1, 3);
      rect(ctx, PAL.navy3, 4, 8, 4, 1);
      rect(ctx, PAL.cream, 1, 9, 10, 16);
      rect(ctx, PAL.cream3, 1, 23, 10, 2);
      rect(ctx, PAL.navy3, 3, 12, 6, 3);
      rect(ctx, PAL.red, 4, 13, 1, 1);
      rect(ctx, PAL.sky, 7, 13, 1, 1);
    },
  },
};

export interface PropPlacement {
  art: keyof typeof PROP_ART;
  x: number;
  y: number;
  /** drawn above characters whose feet are higher up on screen than this */
  depth: number;
}

/** Where the props stand (derived from the floor plan). Monitors are placed by the scene. */
export function propPlacements(): PropPlacement[] {
  const out: PropPlacement[] = [];
  for (const desk of DESKS) {
    const x = desk.seat.col * TILE;
    const y = desk.seat.row * TILE;
    out.push({ art: "chair-back", x: x + 2, y: y + 5, depth: y + 12 });
  }
  for (const spot of ZONES.meeting.filter((s) => s.facing === "up")) {
    out.push({ art: "chair-back", x: spot.col * TILE + 2, y: spot.row * TILE + 5, depth: spot.row * TILE + 12 });
  }
  const sofa = tilesOf("S")[0];
  if (sofa) out.push({ art: "sofa-front", x: sofa.col * TILE - 6, y: sofa.row * TILE + 7, depth: sofa.row * TILE + 12 });
  const bench = tilesOf("b")[0];
  if (bench) out.push({ art: "bench-front", x: bench.col * TILE, y: bench.row * TILE + 6, depth: bench.row * TILE + 12 });
  tilesOf("P").forEach((t, i) => {
    out.push({ art: `plant-${(t.col + t.row + i) % 3}`, x: t.col * TILE, y: t.row * TILE - 8, depth: t.row * TILE + TILE });
  });
  for (const t of tilesOf("H")) out.push({ art: "hay", x: t.col * TILE, y: t.row * TILE, depth: t.row * TILE + TILE });
  for (const t of tilesOf("W")) out.push({ art: "cooler", x: t.col * TILE + 2, y: t.row * TILE - 10, depth: t.row * TILE + TILE });
  return out;
}

/** Where a desk's monitor stands (top-left), centred over the seat. */
export function monitorSpot(desk: (typeof DESKS)[number]): { x: number; y: number; depth: number } {
  return { x: desk.monitor.col * TILE, y: desk.monitor.row * TILE - 2, depth: desk.monitor.row * TILE + TILE };
}

/** Where the persistent agent's pet sits on its desk (bottom-left of the pet). */
export function petSpot(desk: (typeof DESKS)[number]): { x: number; y: number } {
  return { x: desk.monitor.col * TILE + 20, y: desk.monitor.row * TILE + 9 };
}

/**
 * The office floor plan (640×352 px world, 16 px tiles → 40×22). Pure data, no Phaser.
 *
 * Legend: '#' wall, '.' floor, 'D' desk, 'B' task board (on the wall), 'S' sofa seat,
 * 'T' meeting table, 'K' bookshelf, 'b' waiting-bench seat, 'P' plant, 'R' rug (walkable),
 * 'G' the cow's pasture (grass, walkable), 'H' hay bale, 'C' coffee counter (on the wall),
 * 'W' water cooler.
 *
 * Sofa and bench tiles are seats: a character can walk *to* one and sit there, but nobody
 * walks *through* them (see `stepsTo`).
 */
export const TILE = 16;
export const COLS = 40;
export const ROWS = 22;
export const WORLD_W = COLS * TILE; // 640
export const WORLD_H = 360; // spec 18.6 base resolution 640×360

export const LAYOUT = [
  "########################################",
  "#######KKKK#CCCC#BBBBBB#####KKKK########",
  "#P....................................P#",
  "#..........................#...........#",
  "#..DD....DD....DD....DD....#..TTTTT....#",
  "#..........................#..TTTTT....#",
  "#.............................TTTTT....#",
  "#..........................#...........#",
  "#..DD....DD....DD....DD....#..........P#",
  "#..........................#####...#####",
  "#......................................#",
  "#..DD....DD....DD....DD.......GGGGGGGH.#",
  "#.............................GGGGGGGG.#",
  "#.............................GGGGGGGG.#",
  "#..........................P..GGGGGGGG.#",
  "#......................................#",
  "#.RRRRRRR..........................P...#",
  "#.RRRRRRR..............................#",
  "#.SSSSSSS......................bbbbbbb.#",
  "#P.....................................#",
  "#...........P............W.............#",
  "###################..###################",
];

const BLOCKING = new Set(["#", "D", "B", "S", "T", "K", "b", "P", "H", "C", "W"]);
const SEATS = new Set(["S", "b"]);

/** Free floor: characters walk here. */
export function walkable(col: number, row: number): boolean {
  if (row < 0 || row >= ROWS || col < 0 || col >= COLS) return false;
  return !BLOCKING.has(LAYOUT[row]![col]!);
}

/** A sofa or bench seat. */
export function isSeat(col: number, row: number): boolean {
  return SEATS.has(LAYOUT[row]?.[col] ?? "#");
}

/** Path rule for a walk to `goal`: free floor, plus the goal itself when it is a seat. */
export function stepsTo(goal: { col: number; row: number }): (col: number, row: number) => boolean {
  return (col, row) => walkable(col, row) || (col === goal.col && row === goal.row && isSeat(col, row));
}

export type Spot = { col: number; row: number; facing?: "up" | "down" };
export type Desk = { seat: Spot; monitor: { col: number; row: number } };

/** Desks: the seat is the tile below the desk's left half; agents face the monitor (up). */
export const DESKS: Desk[] = [];
for (const row of [4, 8, 11]) {
  for (const col of [3, 9, 15, 21]) {
    DESKS.push({
      seat: { col, row: row + 1, facing: "up" },
      monitor: { col, row },
    });
  }
}

const row = (r: number, cols: number[], facing: Spot["facing"] = "down"): Spot[] =>
  cols.map((col) => ({ col, row: r, facing }));

export const ZONES = {
  /** idle → resting: first on the sofa, then on the rug in front of it */
  lounge: [
    ...row(18, [2, 3, 4, 5, 6, 7, 8]),
    ...row(17, [2, 3, 4, 5, 6, 7, 8]),
    ...row(16, [2, 3, 4, 5, 6, 7, 8]),
    ...row(15, [2, 3, 4, 5, 6, 7, 8, 9, 10]),
  ],
  /** planning → in front of the task board */
  board: row(2, [17, 18, 19, 20, 21, 22], "up"),
  /** waiting → on the waiting bench, then standing in front of it */
  waiting: [
    ...row(18, [31, 32, 33, 34, 35, 36, 37]),
    ...row(17, [31, 32, 33, 34, 35, 36, 37]),
    ...row(16, [31, 32, 33, 34, 36, 37]),
  ],
  /** reviewing → at the bookshelves */
  review: [...row(2, [7, 8, 9, 10], "up"), ...row(2, [28, 29, 30, 31], "up")],
  /** discussion room (orchestrator meetings): chairs on both sides of the table */
  meeting: [...row(3, [30, 31, 32, 33, 34]), ...row(7, [30, 31, 32, 33, 34], "up")],
  /** the cow's (Orchestrator's) corner by the meadow gate */
  pasture: [
    { col: 33, row: 12, facing: "down" as const },
    { col: 35, row: 13, facing: "down" as const },
    { col: 31, row: 13, facing: "down" as const },
  ],
  door: [
    { col: 19, row: 21 },
    { col: 20, row: 21 },
  ],
};
export type ZoneName = keyof typeof ZONES;

export function tileCenter(col: number, rowIndex: number): { x: number; y: number } {
  return { x: col * TILE + TILE / 2, y: rowIndex * TILE + TILE / 2 };
}

/** Every tile with this letter, in reading order. */
export function tilesOf(letter: string): { col: number; row: number }[] {
  const out: { col: number; row: number }[] = [];
  LAYOUT.forEach((line, r) => [...line].forEach((ch, c) => ch === letter && out.push({ col: c, row: r })));
  return out;
}

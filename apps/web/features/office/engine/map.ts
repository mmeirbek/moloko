/**
 * The office floor plan (640×352 px world, 16 px tiles → 40×22). Pure data, no Phaser.
 *
 * Legend: '#' wall, '.' floor, 'D' desk, 'B' task board (on the wall), 'S' sofa,
 * 'T' meeting table, 'K' bookshelf, 'b' waiting bench, 'P' plant, 'R' rug (walkable).
 */
export const TILE = 16;
export const COLS = 40;
export const ROWS = 22;
export const WORLD_W = COLS * TILE; // 640
export const WORLD_H = 360; // spec 18.6 base resolution 640×360

export const LAYOUT = [
  "########################################",
  "#######KKKK######BBBBBB#####KKKK########",
  "#......................................#",
  "#..........................#...........#",
  "#..DD....DD....DD....DD....#..TTTTT....#",
  "#..........................#..TTTTT....#",
  "#..............................TTTTT...#",
  "#..........................#...........#",
  "#..DD....DD....DD....DD....#...........#",
  "#..........................#####...#####",
  "#......................................#",
  "#..DD....DD....DD....DD................#",
  "#......................................#",
  "#......................................#",
  "#..........................P...........#",
  "#......................................#",
  "#.RRRRRRR..........................P...#",
  "#.RRRRRRR..............................#",
  "#.SSSSSSS......................bbbbbbb.#",
  "#P.....................................#",
  "#......................................#",
  "###################..###################",
];

const BLOCKING = new Set(["#", "D", "B", "S", "T", "K", "b", "P"]);

export function walkable(col: number, row: number): boolean {
  if (row < 0 || row >= ROWS || col < 0 || col >= COLS) return false;
  return !BLOCKING.has(LAYOUT[row]![col]!);
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
  /** idle → resting on the sofa side of the lounge */
  lounge: row(17, [2, 3, 4, 5, 6, 7, 8]),
  /** planning → in front of the task board */
  board: row(2, [17, 18, 19, 20, 21, 22], "up"),
  /** waiting → on the waiting bench */
  waiting: row(17, [31, 32, 33, 34, 35, 36, 37]),
  /** reviewing → at the bookshelves */
  review: [...row(2, [7, 8, 9, 10], "up"), ...row(2, [28, 29, 30, 31], "up")],
  /** discussion room (orchestrator meetings) */
  meeting: [...row(3, [31, 32, 33, 34, 35]), ...row(7, [32, 33, 34, 35, 36], "up")],
  door: [
    { col: 19, row: 21 },
    { col: 20, row: 21 },
  ],
};
export type ZoneName = keyof typeof ZONES;

export function tileCenter(col: number, rowIndex: number): { x: number; y: number } {
  return { x: col * TILE + TILE / 2, y: rowIndex * TILE + TILE / 2 };
}

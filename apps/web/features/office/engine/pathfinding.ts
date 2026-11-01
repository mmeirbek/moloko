/** A* on the office grid (4-neighbour, unit cost, Manhattan heuristic). Pure. */
export type Cell = { col: number; row: number };

export function findPath(
  start: Cell,
  goal: Cell,
  isWalkable: (col: number, row: number) => boolean,
  maxNodes = 4000,
): Cell[] | null {
  const key = (c: Cell) => c.row * 1000 + c.col;
  if (start.col === goal.col && start.row === goal.row) return [start];
  if (!isWalkable(goal.col, goal.row)) return null;
  const open = new Map<number, Cell>([[key(start), start]]);
  const came = new Map<number, Cell>();
  const g = new Map<number, number>([[key(start), 0]]);
  const f = new Map<number, number>([[key(start), h(start, goal)]]);
  let explored = 0;
  while (open.size > 0) {
    if (++explored > maxNodes) return null;
    let current: Cell | null = null;
    let best = Infinity;
    for (const [k, c] of open) {
      const score = f.get(k) ?? Infinity;
      if (score < best) {
        best = score;
        current = c;
      }
    }
    if (!current) break;
    if (current.col === goal.col && current.row === goal.row) return rebuild(came, current, key);
    open.delete(key(current));
    for (const [dc, dr] of [
      [1, 0],
      [-1, 0],
      [0, 1],
      [0, -1],
    ] as const) {
      const next = { col: current.col + dc, row: current.row + dr };
      if (!isWalkable(next.col, next.row) && !(next.col === start.col && next.row === start.row)) continue;
      const tentative = (g.get(key(current)) ?? Infinity) + 1;
      if (tentative < (g.get(key(next)) ?? Infinity)) {
        came.set(key(next), current);
        g.set(key(next), tentative);
        f.set(key(next), tentative + h(next, goal));
        open.set(key(next), next);
      }
    }
  }
  return null;
}

function h(a: Cell, b: Cell): number {
  return Math.abs(a.col - b.col) + Math.abs(a.row - b.row);
}

function rebuild(came: Map<number, Cell>, end: Cell, key: (c: Cell) => number): Cell[] {
  const path = [end];
  let current = end;
  while (came.has(key(current))) {
    current = came.get(key(current))!;
    path.unshift(current);
  }
  return path;
}

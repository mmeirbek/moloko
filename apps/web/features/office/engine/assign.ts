/**
 * Stable seat assignment: an agent keeps its desk / spot while it exists, new agents
 * take the first free one. Pure and deterministic (same input → same seats).
 */
export class SeatAssigner {
  private taken = new Map<string, Map<string, number>>(); // pool → agentId → index

  constructor(private readonly sizes: Record<string, number>) {}

  seat(pool: string, agentId: string): number {
    const size = this.sizes[pool] ?? 1;
    const map = this.taken.get(pool) ?? new Map<string, number>();
    this.taken.set(pool, map);
    const existing = map.get(agentId);
    if (existing !== undefined) return existing;
    const used = new Set(map.values());
    let index = 0;
    while (used.has(index) && index < size) index++;
    if (index >= size) index = hash(agentId) % size; // overflow: share a spot
    map.set(agentId, index);
    return index;
  }

  release(pool: string, agentId: string): void {
    this.taken.get(pool)?.delete(agentId);
  }

  releaseAll(agentId: string): void {
    for (const map of this.taken.values()) map.delete(agentId);
  }
}

export function hash(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

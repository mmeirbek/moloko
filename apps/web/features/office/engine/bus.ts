/**
 * React ⇄ Phaser event bus (the pattern of phaserjs/template-nextjs, MIT — see
 * THIRD_PARTY_NOTICES.md). Typed and dependency-free so it is safe to import on the
 * server. Direction: store → React → bus → scene (render); scene → bus → React (clicks).
 */
export interface OfficeAgent {
  id: string;
  name: string;
  status: string;
  kind: "orchestrator" | "subagent" | "autonomous";
}

export interface OfficeEvents {
  /** React → scene: the agents to show (already filtered by mode) */
  agents: OfficeAgent[];
  /** React → scene: camera actions */
  camera: "in" | "out" | "fit";
  /** React → scene: highlight an agent */
  select: string | null;
  /** React → scene: an agent sent a message to another (animated envelope) */
  message: { from: string; to: string };
  /** scene → React: the user clicked a character (or empty floor → null) */
  selected: string | null;
  /** scene → React: the scene is ready to receive agents */
  ready: undefined;
}

type Listener<T> = (payload: T) => void;

export class OfficeBus {
  private listeners = new Map<keyof OfficeEvents, Set<Listener<never>>>();

  on<K extends keyof OfficeEvents>(event: K, listener: Listener<OfficeEvents[K]>): () => void {
    const set = this.listeners.get(event) ?? new Set();
    set.add(listener as Listener<never>);
    this.listeners.set(event, set);
    return () => set.delete(listener as Listener<never>);
  }

  emit<K extends keyof OfficeEvents>(event: K, payload: OfficeEvents[K]): void {
    for (const listener of this.listeners.get(event) ?? []) (listener as Listener<OfficeEvents[K]>)(payload);
  }

  clear(): void {
    this.listeners.clear();
  }
}

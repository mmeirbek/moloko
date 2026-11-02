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

/**
 * What is shown over a busy agent's head (derived from the store by engine/hud.ts; the
 * scene only draws it). All text is plain and already shortened.
 */
export interface AgentHud {
  /** 0–100 when the task's progress is known; null = unknown (the bar shows "busy") */
  percent: number | null;
  /** the short caption next to the bar: "42%", "шаг 3", "ждёт одобрения"; null = none */
  tag: string | null;
  /** what it is doing right now, a few words (shown for the hovered / selected agent) */
  activity: string | null;
  /** bar colour: working, waiting for the owner's approval (amber), paused (grey, still) */
  tone: "work" | "approval" | "paused";
}

/** What the office is told about the world around it (never decided by the scene). */
export interface OfficeEnv {
  /** the owner's local hour (0–23): day and night */
  hour: number;
  locale: string;
  /** seasonal outfit for the cow, if the owner keeps outfits on */
  season: "newyear" | "halloween" | "spring" | null;
  /** an approval is waiting: the cow moos */
  attention: boolean;
}

export interface OfficeEvents {
  /** React → scene: the agents to show (already filtered by mode) */
  agents: OfficeAgent[];
  /** React → scene: camera actions (buttons, keyboard) */
  camera: CameraAction;
  /** React → scene: progress over the heads, by agent id (agents without an entry show none) */
  hud: Record<string, AgentHud>;
  /** React → scene: highlight an agent */
  select: string | null;
  /** React → scene: an agent sent a message to another (animated envelope) */
  message: { from: string; to: string };
  /** React → scene: time of day, language, season, pending approvals */
  env: OfficeEnv;
  /** scene → React: the cow was clicked five times (easter egg; React decides about sound) */
  moo: undefined;
  /** scene → React: the user clicked a character (or empty floor → null) */
  selected: string | null;
  /** scene → React: the scene is ready to receive agents */
  ready: undefined;
  /** scene → React: the current zoom (for the on-map controls and to remember it) */
  zoom: ZoomState;
}

export type CameraAction = "in" | "out" | "fit" | "left" | "right" | "up" | "down";

export interface ZoomState {
  /** size of the office in % of its base 640×360 (CSS pixels) */
  percent: number;
  canZoomIn: boolean;
  canZoomOut: boolean;
  /** the whole office is in view */
  fitted: boolean;
  /** CSS scale the owner chose, to remember per device; null = automatic (fit) */
  chosen: number | null;
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

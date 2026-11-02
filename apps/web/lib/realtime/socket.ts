import type { ClientFrame, EventEnvelope, ServerFrame } from "@moloko/shared-types";

import { api, readBrowserCookie } from "@/lib/api/client";
import { CSRF_COOKIE } from "@/lib/api/config";

import { useRealtimeStore } from "./store";

const HEARTBEAT_MS = 25_000;
const PONG_TIMEOUT_MS = 10_000;
/** A handshake can hang forever if it started while the server was going down. */
const FIRST_FRAME_TIMEOUT_MS = 10_000;
const MAX_BACKOFF_MS = 30_000;

export type EventListener = (event: EventEnvelope) => void;

export function backoffDelay(attempt: number, random = Math.random): number {
  const base = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt);
  return Math.round(base / 2 + (random() * base) / 2);
}

/**
 * One connection to /ws/v1/events. Resumes with the last applied seq; the server
 * answers with the missed events, or a fresh snapshot if we are too far behind.
 * Reconnects with exponential backoff; detects dead links with ping/pong.
 */
export class RealtimeClient {
  private ws: WebSocket | null = null;
  private attempt = 0;
  private stopped = false;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private firstFrameTimer: ReturnType<typeof setTimeout> | null = null;
  private listeners = new Set<EventListener>();
  /** A connect() is between "start" and "socket created" (it awaits the CSRF token). */
  private connecting = false;
  private onUnauthenticated: () => void;

  constructor(opts: { onUnauthenticated: () => void }) {
    this.onUnauthenticated = opts.onUnauthenticated;
  }

  subscribe(listener: EventListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  start(): void {
    this.stopped = false;
    void this.connect();
  }

  stop(): void {
    this.stopped = true;
    this.cleanup();
    this.ws?.close(1000);
    this.ws = null;
  }

  /** Reconnect now (e.g. the tab became visible or the network came back). */
  nudge(): void {
    if (this.stopped || this.connecting) return;
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.attempt = 0;
    void this.connect();
  }

  private send(frame: ClientFrame) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(frame));
  }

  private async csrfToken(): Promise<string> {
    const existing = readBrowserCookie(CSRF_COOKIE);
    if (existing) return existing;
    const { csrf_token } = await api.request<{ csrf_token: string }>("/auth/csrf");
    return csrf_token;
  }

  private async connect(): Promise<void> {
    if (this.stopped || this.connecting) return;
    this.connecting = true;
    useRealtimeStore.getState().setStatus("connecting");
    let csrf: string;
    try {
      csrf = await this.csrfToken();
    } catch {
      this.connecting = false;
      this.scheduleReconnect();
      return;
    }
    this.connecting = false;
    // Stopped (page left) while the token was loading: open nothing, or the socket is orphaned.
    if (this.stopped) return;
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${scheme}://${window.location.host}/ws/v1/events`);
    this.ws = ws;
    // Watchdog: no snapshot/event soon after connecting → abort and retry.
    this.firstFrameTimer = setTimeout(() => {
      if (this.ws === ws) ws.close();
    }, FIRST_FRAME_TIMEOUT_MS);

    ws.onopen = () => {
      this.send({ type: "hello", last_seq: useRealtimeStore.getState().lastSeq, csrf });
      this.startHeartbeat();
    };
    ws.onmessage = (message) => this.handle(message.data);
    ws.onclose = (event) => {
      if (this.ws !== ws) return;
      this.cleanup();
      this.ws = null;
      useRealtimeStore.getState().setStatus("offline");
      if (event.code === 4401) {
        this.stopped = true;
        this.onUnauthenticated();
        return;
      }
      this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  private handle(raw: unknown) {
    let frame: ServerFrame;
    try {
      frame = JSON.parse(String(raw)) as ServerFrame;
    } catch {
      return;
    }
    const store = useRealtimeStore.getState();
    if (frame.type === "pong") {
      if (this.pongTimer) clearTimeout(this.pongTimer);
      this.pongTimer = null;
      return;
    }
    this.attempt = 0;
    if (this.firstFrameTimer) clearTimeout(this.firstFrameTimer);
    this.firstFrameTimer = null;
    store.setStatus("online");
    if (frame.type === "snapshot") {
      store.applySnapshot(frame);
      for (const listener of this.listeners) listener({ type: "snapshot" } as unknown as EventEnvelope);
      return;
    }
    if (frame.type === "event" && store.applyEvent(frame.event)) {
      for (const listener of this.listeners) listener(frame.event);
    }
  }

  private startHeartbeat() {
    this.heartbeat = setInterval(() => {
      this.send({ type: "ping" });
      this.pongTimer ??= setTimeout(() => this.ws?.close(4000), PONG_TIMEOUT_MS);
    }, HEARTBEAT_MS);
  }

  private cleanup() {
    if (this.heartbeat) clearInterval(this.heartbeat);
    if (this.pongTimer) clearTimeout(this.pongTimer);
    if (this.firstFrameTimer) clearTimeout(this.firstFrameTimer);
    this.heartbeat = null;
    this.pongTimer = null;
    this.firstFrameTimer = null;
  }

  private scheduleReconnect() {
    if (this.stopped) return;
    const delay = backoffDelay(this.attempt++);
    this.retryTimer = setTimeout(() => void this.connect(), delay);
  }
}

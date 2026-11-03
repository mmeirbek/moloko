"use client";

import type { AgentOut } from "@moloko/shared-types";
import { useLocale, useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";

import { Maximize, Minus, Plus, UserPlus } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/features/agents/status-badge";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { playMoo } from "@/features/mascot/moo";
import { useSeason } from "@/features/mascot/pixel-cow";
import { mascotSnapshot } from "@/features/mascot/prefs";
import { useRealtimeClient } from "@/lib/realtime/provider";
import { pendingApprovals, useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { canDrop, readDrop, useAddToOffice } from "./add-to-office";
import { AgentInspector } from "./agent-inspector";
import { AgentPalette } from "./agent-palette";
import { OfficeBus, type CameraAction, type OfficeAgent, type ZoomState } from "./engine/bus";
import { officeHud, type HudWords } from "./engine/hud";

/** Who is in the office: the owner's agents and the Orchestrator (old temporary subagents
 *  from before 2026-11-02 never come back). */
export function officeAgents(agents: AgentOut[]): AgentOut[] {
  return agents.filter((a) => !a.archived_at && a.agent_type !== "subagent");
}

/** The zoom chosen on this device (CSS px per art pixel); null = automatic. */
const ZOOM_KEY = "moloko.office.zoom";

function loadZoom(): number | null {
  try {
    const value = Number(window.localStorage.getItem(ZOOM_KEY));
    return Number.isFinite(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

function saveZoom(value: number | null): void {
  try {
    if (value === null) window.localStorage.removeItem(ZOOM_KEY);
    else window.localStorage.setItem(ZOOM_KEY, String(Math.round(value * 1000) / 1000));
  } catch {
    // private mode or blocked storage: the zoom is simply not remembered
  }
}

/** Keys on the focused map: + / − / 0 zoom, arrows move the view. */
export function cameraActionForKey(key: string): CameraAction | null {
  switch (key) {
    case "+":
    case "=":
      return "in";
    case "-":
    case "_":
      return "out";
    case "0":
      return "fit";
    case "ArrowLeft":
      return "left";
    case "ArrowRight":
      return "right";
    case "ArrowUp":
      return "up";
    case "ArrowDown":
      return "down";
    default:
      return null;
  }
}

function toOfficeAgent(a: AgentOut): OfficeAgent {
  return {
    id: a.id,
    name: a.name,
    status: a.status,
    kind: a.agent_type as OfficeAgent["kind"],
  };
}

/**
 * The pixel office: the owner's agents and the Orchestrator cow. `compact` (the island): only
 * the map and its zoom. Saved agents can be dragged onto the map (AgentPalette).
 */
export function OfficeView({
  compact = false,
  onSelect,
}: {
  compact?: boolean;
  /** A character was clicked (the island gives that agent the next task). */
  onSelect?: (agentId: string | null) => void;
}) {
  const t = useTranslations("office");
  const toMessage = useErrorMessage();
  const container = useRef<HTMLDivElement>(null);
  const [bus] = useState(() => new OfficeBus());
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [dropping, setDropping] = useState(false);
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);
  // A second click on a busy agent opens its task (owner: «нажал на агента — открылась его
  // задача»; the first click shows the agent's card with its task on top).
  const router = useRouter();
  const openTaskRef = useRef<(agentId: string) => void>(() => undefined);
  useEffect(() => {
    openTaskRef.current = (agentId) => {
      const taskId = useRealtimeStore.getState().agents[agentId]?.current_task_id;
      if (taskId && !compact) router.push(`/tasks/${taskId}`);
    };
  }, [compact, router]);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [zoom, setZoom] = useState<ZoomState | null>(null);
  const agentsById = useRealtimeStore((s) => s.agents);
  const realtime = useRealtimeClient();
  const locale = useLocale();
  const season = useSeason();
  const attention = useRealtimeStore((s) => pendingApprovals(s.approvals).length > 0);
  // `?hour=22` shows the office at that hour (screenshots, tests); otherwise the real clock.
  const forcedHour = useSearchParams().get("hour");
  const [hour, setHour] = useState(() => new Date().getHours());
  useEffect(() => {
    const timer = window.setInterval(() => setHour(new Date().getHours()), 60_000);
    return () => window.clearInterval(timer);
  }, []);
  const shownHour = forcedHour !== null && /^\d{1,2}$/.test(forcedHour) ? Number(forcedHour) % 24 : hour;

  const shown = useMemo(() => officeAgents(Object.values(agentsById)), [agentsById]);
  // Progress over the heads: task %, step, what it does now, waiting for approval (engine/hud.ts).
  const tasks = useRealtimeStore((s) => s.tasks);
  const runs = useRealtimeStore((s) => s.runs);
  const lastMessage = useRealtimeStore((s) => s.lastMessage);
  const approvals = useRealtimeStore((s) => s.approvals);
  const hudWords = useMemo<HudWords>(
    () => ({ step: (step) => t("hud.step", { step }), approval: t("hud.approval") }),
    [t],
  );
  const hud = useMemo(
    () => officeHud(shown, { tasks, runs, lastMessage, approvals }, hudWords),
    [shown, tasks, runs, lastMessage, approvals, hudWords],
  );
  // Show who came in.
  const addToOffice = useAddToOffice((id) => {
    if (!compact) setSelected(id);
  });

  // Mount Phaser on the client only (it needs window/canvas).
  useEffect(() => {
    let game: { destroy: (removeCanvas: boolean) => void } | null = null;
    let cancelled = false;
    const offReady = bus.on("ready", () => setReady(true));
    const offSelected = bus.on("selected", (id) => {
      setSelected(id);
      onSelectRef.current?.(id);
    });
    const offOpen = bus.on("open", (id) => openTaskRef.current(id));
    const offMoo = bus.on("moo", () => {
      if (mascotSnapshot().sound) playMoo();
    });
    const offZoom = bus.on("zoom", (state) => {
      setZoom(state);
      saveZoom(state.chosen);
    });
    void import("./engine/createGame")
      .then(({ createOfficeGame }) => {
        if (!cancelled && container.current) game = createOfficeGame(container.current, bus, { zoom: loadZoom() });
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      offReady();
      offSelected();
      offOpen();
      offMoo();
      offZoom();
      game?.destroy(true);
    };
  }, [bus]);

  // Store → scene (one direction only).
  useEffect(() => {
    if (ready) bus.emit("agents", shown.map(toOfficeAgent));
  }, [bus, ready, shown]);

  useEffect(() => {
    if (ready) bus.emit("hud", hud);
  }, [bus, ready, hud]);

  useEffect(() => {
    if (ready) bus.emit("select", selected);
  }, [bus, ready, selected]);

  useEffect(() => {
    if (ready) bus.emit("env", { hour: shownHour, locale, season, attention });
  }, [bus, ready, shownHour, locale, season, attention]);

  // Agent↔agent messages fly across the office.
  useEffect(() => {
    if (!realtime) return;
    return realtime.subscribe((event) => {
      const p = event.payload as Record<string, unknown> | undefined;
      if (event.type === "agent.message" && p?.kind === "agent_to_agent") {
        bus.emit("message", {
          from: String(p.sender_agent_id),
          to: String(p.receiver_agent_id),
        });
      }
    });
  }, [bus, realtime]);

  const selectedAgent = selected ? agentsById[selected] : undefined;

  const onMapKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return; // leave browser zoom and shortcuts alone
    const action = cameraActionForKey(e.key);
    if (!action || !ready) return;
    e.preventDefault();
    bus.emit("camera", action);
  };

  return (
    <div className={cn("flex flex-col gap-3", compact && "h-full min-h-0")}>
      {!compact && (
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="outline" onClick={() => setAdding((v) => !v)} aria-expanded={adding} data-testid="add-agent">
          <UserPlus /> <span className="hidden sm:inline">{t("addAgent")}</span>
        </Button>
      </div>
      )}

      {!compact && adding && (
        <AgentPalette
          onClose={() => setAdding(false)}
          onAdded={(id) => {
            setAdding(false);
            setSelected(id);
          }}
        />
      )}

      <div className={cn("relative", compact && "min-h-0 flex-1")}>
        {/* Focusable so + / − / 0 and the arrows work; the same state is listed below as text. */}
        <div
          ref={container}
          data-testid="pixel-office"
          role="group"
          aria-roledescription={t("mapRole")}
          aria-label={t("canvasLabel", { count: shown.length })}
          aria-describedby="office-keys"
          aria-keyshortcuts="Plus - 0 ArrowLeft ArrowRight ArrowUp ArrowDown"
          tabIndex={0}
          onKeyDown={onMapKey}
          onDragOver={(e) => {
            if (!canDrop(e)) return;
            e.preventDefault(); // allow the drop
            e.dataTransfer.dropEffect = "copy";
            setDropping(true);
          }}
          onDragLeave={() => setDropping(false)}
          onDrop={(e) => {
            setDropping(false);
            const item = readDrop(e);
            if (!item) return;
            e.preventDefault();
            addToOffice.mutate(item);
          }}
          className={cn(
            "w-full touch-none overflow-hidden bg-[#0c1024] pixel-frame outline-none select-none focus-visible:[--frame-color:var(--color-ring)]",
            compact ? "h-full min-h-48" : "aspect-[4/3] max-h-[70vh] sm:aspect-video",
            dropping && "[--frame-color:var(--color-sky)]",
          )}
          data-dropping={dropping || undefined}
        />
        {dropping && (
          <p className="pointer-events-none absolute inset-x-0 top-3 text-center text-sm text-[#f6efdc]">{t("dropHere")}</p>
        )}
        {addToOffice.error && (
          <p role="alert" className="absolute inset-x-3 top-3 bg-[#10142b] px-3 py-2 text-xs text-[#f6efdc] pixel-frame [--frame-color:var(--color-destructive)]">
            {toMessage(addToOffice.error).message}
          </p>
        )}
        <p id="office-keys" className="sr-only">
          {t("keysHint")}
        </p>
        {ready && zoom && (
          <div
            role="group"
            aria-label={t("zoom")}
            className="absolute top-2 right-2 flex items-center gap-0.5 border-2 border-[#f5ecd6]/15 bg-[#10142b]/85 p-1 text-[#f5ecd6] shadow-lg md:top-auto md:right-auto md:bottom-2 md:left-2"
          >
            <MapButton label={t("zoomOut")} shortcut="-" disabled={!zoom.canZoomOut} onClick={() => bus.emit("camera", "out")}>
              <Minus />
            </MapButton>
            <output
              aria-live="polite"
              aria-label={t("zoomLevel", { percent: zoom.percent })}
              className="min-w-11 text-center font-mono text-xs tabular-nums"
              data-testid="office-zoom-level"
            >
              {zoom.percent}%
            </output>
            <MapButton label={t("zoomIn")} shortcut="Plus" disabled={!zoom.canZoomIn} onClick={() => bus.emit("camera", "in")}>
              <Plus />
            </MapButton>
            <span aria-hidden className="mx-0.5 h-5 w-px bg-[#f5ecd6]/20" />
            <MapButton
              label={t("fit")}
              shortcut="0"
              pressed={zoom.fitted && zoom.chosen === null}
              onClick={() => bus.emit("camera", "fit")}
            >
              <Maximize />
            </MapButton>
          </div>
        )}
        {failed && (
          <p className="absolute inset-0 flex items-center justify-center p-4 text-sm text-muted-foreground">
            {t("failed")}
          </p>
        )}
        {ready && shown.length === 0 && !compact && (
          <p className="pointer-events-none absolute inset-x-0 bottom-3 px-3 text-center text-sm text-[#f6efdc]/80 md:top-3 md:bottom-auto">
            {t("emptyAgents")}
          </p>
        )}
        {selectedAgent && !compact && (
          <AgentInspector
            agent={selectedAgent}
            onClose={() => setSelected(null)}
            className="absolute inset-x-2 bottom-2 md:inset-x-auto md:top-2 md:right-2 md:bottom-auto md:w-80"
          />
        )}
      </div>

      {/* The same information as text: for screen readers and for a quick overview. */}
      <ul className={cn("flex flex-wrap gap-2", compact && "sr-only")} aria-label={t("list")}>
        {shown.map((a) => (
          <li key={a.id}>
            <button
              type="button"
              onClick={() => setSelected(a.id)}
              className={cn(
                "flex items-center gap-2 border-2 px-3 py-1 text-sm",
                selected === a.id ? "border-primary" : "hover:bg-accent/60",
              )}
            >
              <span className="max-w-40 truncate">{a.name}</span>
              <StatusBadge status={a.status} />
              {hud[a.id]?.tag && (
                <span
                  className={cn(
                    "text-xs whitespace-nowrap tabular-nums",
                    hud[a.id]!.tone === "approval"
                      ? "bg-amber-400/20 px-1 text-amber-700 dark:text-amber-300"
                      : "text-muted-foreground",
                  )}
                >
                  {hud[a.id]!.tag}
                </span>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** A button on the dark map: always light-on-navy, whatever the theme; 40 px on phones. */
function MapButton({
  label,
  shortcut,
  disabled,
  pressed,
  onClick,
  children,
}: {
  label: string;
  shortcut: string;
  disabled?: boolean;
  pressed?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-keyshortcuts={shortcut}
      aria-pressed={pressed}
      title={`${label} (${shortcut === "Plus" ? "+" : shortcut === "-" ? "−" : shortcut})`}
      disabled={disabled}
      onClick={onClick}
      className={cn(
        "inline-flex size-10 items-center justify-center outline-none transition-colors md:size-8",
        "hover:bg-[#f5ecd6]/15 focus-visible:ring-2 focus-visible:ring-[#f5ecd6] disabled:pointer-events-none disabled:opacity-35",
        pressed && "bg-[#f5ecd6]/15",
      )}
    >
      {children}
    </button>
  );
}

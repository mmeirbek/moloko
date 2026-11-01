"use client";

import type { AgentOut } from "@moloko/shared-types";
import { Maximize, Minus, Plus, UserPlus } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { AgentTemplates } from "@/features/agents/agent-templates";
import { StatusBadge } from "@/features/agents/status-badge";
import { playMoo } from "@/features/mascot/moo";
import { useSeason } from "@/features/mascot/pixel-cow";
import { mascotSnapshot } from "@/features/mascot/prefs";
import { useRealtimeClient } from "@/lib/realtime/provider";
import { pendingApprovals, useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { AgentInspector } from "./agent-inspector";
import { OfficeBus, type OfficeAgent } from "./engine/bus";

export type OfficeMode = "subagents" | "agents";

/** Which agents a mode shows (spec 2.1: one map, mode switch). */
export function agentsForMode(agents: AgentOut[], mode: OfficeMode): AgentOut[] {
  const visible = agents.filter((a) => !a.archived_at);
  if (mode === "agents") return visible.filter((a) => a.agent_type !== "subagent");
  return visible.filter((a) => a.agent_type === "subagent" || a.agent_type === "orchestrator");
}

function toOfficeAgent(a: AgentOut): OfficeAgent {
  return {
    id: a.id,
    name: a.name,
    status: a.status,
    kind: a.agent_type as OfficeAgent["kind"],
  };
}

export function OfficeView({ initialMode }: { initialMode: OfficeMode }) {
  const t = useTranslations("office");
  const container = useRef<HTMLDivElement>(null);
  const [bus] = useState(() => new OfficeBus());
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [mode, setMode] = useState<OfficeMode>(initialMode);
  const [selected, setSelected] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
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

  const shown = useMemo(() => agentsForMode(Object.values(agentsById), mode), [agentsById, mode]);

  // Mount Phaser on the client only (it needs window/canvas).
  useEffect(() => {
    let game: { destroy: (removeCanvas: boolean) => void } | null = null;
    let cancelled = false;
    const offReady = bus.on("ready", () => setReady(true));
    const offSelected = bus.on("selected", (id) => setSelected(id));
    const offMoo = bus.on("moo", () => {
      if (mascotSnapshot().sound) playMoo();
    });
    void import("./engine/createGame")
      .then(({ createOfficeGame }) => {
        if (!cancelled && container.current) game = createOfficeGame(container.current, bus);
      })
      .catch(() => setFailed(true));
    return () => {
      cancelled = true;
      offReady();
      offSelected();
      offMoo();
      game?.destroy(true);
    };
  }, [bus]);

  // Store → scene (one direction only).
  useEffect(() => {
    if (ready) bus.emit("agents", shown.map(toOfficeAgent));
  }, [bus, ready, shown]);

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

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* A two-way switch (not tabs: there is no separate panel per choice). */}
        <div role="group" aria-label={t("mode")} className="inline-flex rounded-md border p-0.5 text-sm">
          {(["subagents", "agents"] as const).map((m) => (
            <button
              key={m}
              type="button"
              aria-pressed={mode === m}
              onClick={() => {
                setMode(m);
                setSelected(null);
              }}
              className={cn(
                "min-h-9 rounded-sm px-3",
                mode === m ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t(`modes.${m}`)}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1">
          {mode === "agents" && (
            <Button variant="outline" onClick={() => setAdding((v) => !v)} aria-expanded={adding} data-testid="add-agent">
              <UserPlus /> <span className="hidden sm:inline">{t("addAgent")}</span>
            </Button>
          )}
          <Button size="icon" variant="outline" aria-label={t("zoomOut")} onClick={() => bus.emit("camera", "out")}>
            <Minus />
          </Button>
          <Button size="icon" variant="outline" aria-label={t("fit")} onClick={() => bus.emit("camera", "fit")}>
            <Maximize />
          </Button>
          <Button size="icon" variant="outline" aria-label={t("zoomIn")} onClick={() => bus.emit("camera", "in")}>
            <Plus />
          </Button>
        </div>
      </div>

      {adding && mode === "agents" && (
        <AgentTemplates
          onClose={() => setAdding(false)}
          onCreated={(id) => {
            setAdding(false);
            setSelected(id);
          }}
        />
      )}

      <div className="relative">
        <div
          ref={container}
          data-testid="pixel-office"
          role="img"
          aria-label={t("canvasLabel", { count: shown.length })}
          className="aspect-[4/3] max-h-[70vh] w-full touch-none overflow-hidden rounded-lg border bg-[#0c1024] select-none sm:aspect-video"
        />
        {failed && (
          <p className="absolute inset-0 flex items-center justify-center p-4 text-sm text-muted-foreground">
            {t("failed")}
          </p>
        )}
        {ready && shown.length === 0 && (
          <p className="pointer-events-none absolute inset-x-0 top-3 text-center text-sm text-[#f6efdc]/80">
            {t(mode === "agents" ? "emptyAgents" : "emptySubagents")}
          </p>
        )}
        {selectedAgent && (
          <AgentInspector
            agent={selectedAgent}
            onClose={() => setSelected(null)}
            className="absolute inset-x-2 bottom-2 md:inset-x-auto md:top-2 md:right-2 md:bottom-auto md:w-80"
          />
        )}
      </div>

      {/* The same information as text: for screen readers and for a quick overview. */}
      <ul className="flex flex-wrap gap-2" aria-label={t("list")}>
        {shown.map((a) => (
          <li key={a.id}>
            <button
              type="button"
              onClick={() => setSelected(a.id)}
              className={cn(
                "flex items-center gap-2 rounded-full border px-3 py-1 text-sm",
                selected === a.id ? "border-primary" : "hover:bg-accent/60",
              )}
            >
              <span className="max-w-40 truncate">{a.name}</span>
              <StatusBadge status={a.status} />
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

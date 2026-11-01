"use client";

import { useTranslations } from "next-intl";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { cn } from "@/lib/utils";

import { COW, composeFace, runs, seasonFor, type CowMood, type Season } from "./art";
import { playMoo } from "./moo";
import { DEFAULT_MASCOT, mascotSnapshot, subscribeMascot } from "./prefs";

const reducedMotion = () =>
  typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** The current seasonal outfit, if the owner keeps them on (client only: no hydration mismatch). */
export function useSeason(): Season | null {
  const prefs = useSyncExternalStore(subscribeMascot, mascotSnapshot, () => DEFAULT_MASCOT);
  const [season, setSeason] = useState<Season | null>(null);
  useEffect(() => {
    const update = () => setSeason(seasonFor(new Date()));
    update();
    const timer = window.setInterval(update, 60 * 60_000);
    return () => window.clearInterval(timer);
  }, []);
  return prefs.seasonal ? season : null;
}

export function CowSvg({
  rows,
  width,
  height,
  className,
  title,
  palette = COW.palette,
}: {
  rows: string[];
  width: number;
  height: number;
  className?: string;
  title?: string;
  palette?: Record<string, string>;
}) {
  const cols = rows[0]?.length ?? 0;
  return (
    <svg
      viewBox={`0 0 ${cols} ${rows.length}`}
      width={width}
      height={height}
      shapeRendering="crispEdges"
      className={cn("pixelated", className)}
      role={title ? "img" : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      {runs(rows).map(({ x, y, w, key }) => (
        <rect key={`${x}-${y}`} x={x} y={y} width={w} height={1} fill={palette[key] ?? "#ff00ff"} />
      ))}
    </svg>
  );
}

/**
 * The moloko cow (front view). Idle cows blink now and then. `interactive` hides the
 * easter egg: five quick clicks → "Moo!" (with sound only if the owner turned it on).
 */
export function PixelCow({
  mood = "idle",
  size = 64,
  className,
  title,
  interactive = false,
  outfit = true,
}: {
  mood?: CowMood;
  size?: number;
  className?: string;
  title?: string;
  interactive?: boolean;
  /** Show the seasonal outfit (if the owner keeps outfits on). */
  outfit?: boolean;
}) {
  const t = useTranslations("mascot");
  const season = useSeason();
  const [blink, setBlink] = useState(false);
  const [mooing, setMooing] = useState(false);
  const clicks = useRef<number[]>([]);

  useEffect(() => {
    if (mood !== "idle" || reducedMotion()) return;
    let timer = 0;
    const schedule = () => {
      timer = window.setTimeout(
        () => {
          setBlink(true);
          timer = window.setTimeout(() => {
            setBlink(false);
            schedule();
          }, 160);
        },
        2500 + Math.random() * 3500,
      );
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [mood]);

  useEffect(() => {
    if (!mooing) return;
    const timer = window.setTimeout(() => setMooing(false), 1600);
    return () => window.clearTimeout(timer);
  }, [mooing]);

  const shown: CowMood = mooing ? "moo" : mood === "idle" && blink ? "blink" : mood;
  const rows = composeFace(shown, outfit ? season : null);

  function onClick() {
    if (!interactive) return;
    const now = Date.now();
    clicks.current = [...clicks.current.filter((at) => now - at < 2500), now];
    if (clicks.current.length >= 5) {
      clicks.current = [];
      setMooing(true);
      if (mascotSnapshot().sound) playMoo();
    }
  }

  return (
    <span
      className={cn("relative inline-flex shrink-0", className)}
      onClick={interactive ? onClick : undefined}
      data-cow-mood={shown}
      data-season={outfit && season ? season : undefined}
    >
      <CowSvg rows={rows} width={size} height={size} title={title} />
      {mooing && (
        <span
          role="status"
          className="font-pixel absolute -top-3 left-3/4 rounded-md border-2 border-[#1b1b2e] bg-white px-1.5 text-sm leading-tight whitespace-nowrap text-[#1b1b2e] shadow"
        >
          {t("moo")}
        </span>
      )}
    </span>
  );
}

/** The office cow walking in place — used for loading screens. */
export function WalkingCow({ size = 72, className }: { size?: number; className?: string }) {
  const [frame, setFrame] = useState(0);
  useEffect(() => {
    if (reducedMotion()) return;
    const timer = window.setInterval(() => setFrame((f) => (f + 1) % 2), 260);
    return () => window.clearInterval(timer);
  }, []);
  const rows = COW.side.frames[frame ? "walk2" : "walk1"]!;
  return (
    <CowSvg
      rows={rows}
      width={size}
      height={Math.round((size * COW.side.height) / COW.side.width)}
      className={className}
    />
  );
}

"use client";

import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

import { CowSvg } from "./pixel-cow";

const BOTTLE = [
  "....cccc....",
  "...cccccc...",
  "....oooo....",
  "....o..o....",
  "....o..o....",
  "...o....o...",
  "..o......o..",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  ".o........o.",
  "..oooooooo..",
];

/** Bottle rows with milk up to `percent`: interior cells below the level become milk. Pure: tested. */
export function bottleRows(percent: number): string[] {
  const inside = BOTTLE.map((row): [number, number] | null => {
    const first = row.indexOf("o");
    const last = row.lastIndexOf("o");
    return first >= 0 && last > first && row.slice(first + 1, last).includes(".") ? [first, last] : null;
  });
  const interior = inside.filter(Boolean).length;
  const level = Math.round((Math.max(0, Math.min(100, percent)) / 100) * interior);
  let fromBottom = 0;
  const out = [...BOTTLE];
  for (let y = BOTTLE.length - 1; y >= 0; y--) {
    const span = inside[y];
    if (!span) continue;
    const fill = fromBottom < level ? "m" : "q";
    fromBottom++;
    out[y] = BOTTLE[y]!.slice(0, span[0] + 1) + fill.repeat(span[1] - span[0] - 1) + BOTTLE[y]!.slice(span[1]);
  }
  // a spot of cow print on the label once there is milk behind it
  if (level >= 4) out[12] = out[12]!.slice(0, 3) + "kk" + out[12]!.slice(5);
  return out;
}

/**
 * Task progress as a pixel milk bottle that fills up. When the task is done the bottle
 * clinks with a second one (the animation respects reduced motion).
 */
export function MilkBottle({
  percent,
  done = false,
  size = 28,
  className,
}: {
  percent: number;
  done?: boolean;
  size?: number;
  className?: string;
}) {
  const t = useTranslations("mascot");
  const value = done ? 100 : Math.max(0, Math.min(100, Math.round(percent)));
  const rows = bottleRows(value);
  const height = Math.round((size * BOTTLE.length) / BOTTLE[0]!.length);
  return (
    <span
      role="progressbar"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={value}
      aria-label={done ? t("bottleDone") : t("bottle", { percent: value })}
      className={cn("relative inline-flex items-end", className)}
      data-testid="milk-bottle"
    >
      <span className={cn("inline-flex origin-bottom", done && "motion-safe:animate-[clink-left_0.9s_ease-in-out_2]")}>
        <CowSvg rows={rows} width={size} height={height} />
      </span>
      {done && (
        <>
          <span className="pointer-events-none absolute -top-1 left-[85%] text-xs text-amber-400 motion-safe:animate-[sparkle_0.9s_ease-in-out_2]">
            ✦
          </span>
          <span className="-ml-1 inline-flex origin-bottom -scale-x-100 motion-safe:animate-[clink-right_0.9s_ease-in-out_2]">
            <CowSvg rows={rows} width={size} height={height} />
          </span>
        </>
      )}
    </span>
  );
}

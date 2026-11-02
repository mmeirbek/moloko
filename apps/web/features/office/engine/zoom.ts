/**
 * Zoom levels of the office camera. Pure: tested.
 *
 * The canvas is rendered at the screen's real (device) resolution, and a zoom level is a
 * whole number of device pixels per art pixel — so every art pixel is always the same
 * size on screen, at any devicePixelRatio (spec 18.6 pixel-perfect, integer scaling).
 * On a retina screen (ratio 2) that allows 150 % (3 device px), on a plain one 100 %, 200 %…
 * The UI shows a level as a percentage of the base 640×360 in CSS pixels.
 */

/** Sizes the ladder aims for, in CSS pixels per art pixel. */
const LADDER = [0.5, 0.75, 1, 1.5, 2, 3, 4, 6] as const;
/** The office never starts smaller than this (CSS px per art px), unless it fits. */
const MIN_AUTO_SCALE = 0.5;

export function clampDpr(dpr: number): number {
  return Number.isFinite(dpr) && dpr > 0 ? Math.min(3, Math.max(1, dpr)) : 1;
}

/** Largest whole zoom that shows the whole world in the view (both in device px); ≥ 1. */
export function fitZoom(viewW: number, viewH: number, worldW: number, worldH: number): number {
  return Math.max(1, Math.floor(Math.min(viewW / worldW, viewH / worldH)));
}

/** All levels for this screen: the ladder in device px, plus the fit level. Sorted, unique. */
export function zoomLevels(dpr: number, fit: number): number[] {
  const levels = new Set<number>([fit]);
  for (const scale of LADDER) levels.add(Math.max(1, Math.round(scale * dpr)));
  return [...levels].sort((a, b) => a - b);
}

/** The level closest to a CSS scale (compared on a log scale: 1.5 is as far from 1 as from 2.25). */
export function nearestLevel(levels: number[], scale: number, dpr: number): number {
  const want = Math.log(Math.max(0.01, scale * dpr));
  let best = levels[0]!;
  for (const level of levels) if (Math.abs(Math.log(level) - want) < Math.abs(Math.log(best) - want)) best = level;
  return best;
}

/** The start level when the owner has not chosen one: fit, but not microscopic on phones. */
export function autoLevel(levels: number[], fit: number, dpr: number): number {
  const floor = Math.ceil(MIN_AUTO_SCALE * dpr - 1e-9);
  return levels.find((level) => level >= Math.max(fit, floor)) ?? levels.at(-1)!;
}

/** One step in or out from the current zoom (which may sit between levels). */
export function stepLevel(levels: number[], current: number, direction: 1 | -1): number {
  if (direction > 0) return levels.find((level) => level > current) ?? levels.at(-1)!;
  return [...levels].reverse().find((level) => level < current) ?? levels[0]!;
}

/** "150" for 3 device px per art px at ratio 2. */
export function zoomPercent(level: number, dpr: number): number {
  return Math.round((level / dpr) * 100);
}

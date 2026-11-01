/**
 * The moloko cow — original pixel art (cow-art.json, listed in assets/MANIFEST.md).
 * `face` = front view for the UI (20×20), `side` = the office character (24×16).
 */
import raw from "./cow-art.json";

export type CowMood = "idle" | "blink" | "happy" | "sleep" | "sad" | "moo";
export type Season = "newyear" | "halloween" | "spring";

interface Sheet {
  width: number;
  height: number;
  frames: Record<string, string[]>;
}

interface CowArt {
  palette: Record<string, string>;
  face: Sheet & { frames: Record<CowMood, string[]> };
  overlays: Record<Season, string[]>;
  side: Sheet;
  /** the owner's logo (cow in a meadow), 32×32 with its own palette */
  logo: { width: number; height: number; palette: Record<string, string>; rows: string[] };
}

export const COW = raw as unknown as CowArt;

/** A face frame with an optional seasonal outfit drawn over it ('.' keeps the cow). */
export function composeFace(mood: CowMood, season: Season | null = null): string[] {
  const base = COW.face.frames[mood];
  const overlay = season ? COW.overlays[season] : null;
  if (!overlay) return base;
  return base.map((row, y) =>
    Array.from(row, (ch, x) => {
      const o = overlay[y]?.[x] ?? ".";
      return o === "." ? ch : o;
    }).join(""),
  );
}

/** Horizontal runs of one colour — far fewer SVG nodes than one rect per pixel. */
export function runs(rows: string[]): { x: number; y: number; w: number; key: string }[] {
  const out: { x: number; y: number; w: number; key: string }[] = [];
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const key = row[x]!;
      let end = x + 1;
      while (end < row.length && row[end] === key) end++;
      if (key !== ".") out.push({ x, y, w: end - x, key });
      x = end;
    }
  });
  return out;
}

/**
 * Seasonal outfit for a date (local time): New Year hat 15 Dec – 14 Jan, witch hat
 * 24 Oct – 1 Nov, a spring flower March–May. Pure: tested.
 */
export function seasonFor(date: Date): Season | null {
  const m = date.getMonth() + 1;
  const d = date.getDate();
  if ((m === 12 && d >= 15) || (m === 1 && d <= 14)) return "newyear";
  if ((m === 10 && d >= 24) || (m === 11 && d === 1)) return "halloween";
  if (m >= 3 && m <= 5) return "spring";
  return null;
}

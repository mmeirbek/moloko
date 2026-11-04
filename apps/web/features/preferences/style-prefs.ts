/*
 * Styles (owner: «разные стили, а не только темы — неон, ч/б и т. п.»): a colour scheme on top
 * of light / dark, per device in localStorage, applied as <html data-style="…"> before the first
 * paint (STYLE_INIT in app/layout.tsx), so nothing flashes. Each style has a light and a dark
 * palette in globals.css; "classic" is the default (no attribute). Plain data: the server layout
 * imports the init script from here.
 */

export const STYLES = ["classic", "neon", "mono", "milk", "ocean"] as const;
export type StyleName = (typeof STYLES)[number];
export const STYLE_KEY = "moloko.style";

/** Swatches for the picker: background, card, accent, text (light / dark). */
export const SWATCHES: Record<StyleName, { light: string[]; dark: string[] }> = {
  classic: { light: ["#faf9f7", "#ffffff", "#1c1b19", "#1f62c4"], dark: ["#141414", "#1c1c1e", "#f2e6c9", "#74aefc"] },
  neon: { light: ["#fbfaff", "#ffffff", "#c026d3", "#0891b2"], dark: ["#0a0a12", "#12121d", "#ff2bd6", "#22d3ee"] },
  mono: { light: ["#ffffff", "#ffffff", "#000000", "#555555"], dark: ["#000000", "#0b0b0b", "#ffffff", "#aaaaaa"] },
  milk: { light: ["#fbf6ea", "#fffdf7", "#3b2f22", "#b5652b"], dark: ["#17130f", "#211b16", "#e8c48a", "#d9a066"] },
  ocean: { light: ["#f4f8fc", "#ffffff", "#0b5cad", "#0e8f8f"], dark: ["#0c141f", "#122031", "#6cb6ff", "#41d3c4"] },
};

export function isStyle(value: unknown): value is StyleName {
  return typeof value === "string" && (STYLES as readonly string[]).includes(value);
}

/** Runs inline before the first paint; mirrors applyStyle in use-style.ts (same key). */
export const STYLE_INIT = `try{var v=localStorage.getItem("${STYLE_KEY}");if(v&&v!=="classic"&&${JSON.stringify(STYLES)}.indexOf(v)>0)document.documentElement.dataset.style=v}catch(e){}`;

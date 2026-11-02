/*
 * Sidebar width and collapsed state: a per-device layout preference (like Claude's sidebar),
 * kept in localStorage. The page reads it before the first paint (SIDEBAR_INIT_SCRIPT in
 * app/layout.tsx), so a reload never flashes the default width. The width is the CSS variable
 * --sidebar-width on <html>; "collapsed" is <html data-sidebar="collapsed"> (CSS variant
 * `sidebar-collapsed:` in globals.css) — no React state, so server and client render the same.
 * This file is plain data (the server layout imports the init script from it); the browser
 * side is in use-sidebar.ts.
 */

export const SIDEBAR_MIN = 208; // px: the logo, the two buttons and a short chat title still fit
export const SIDEBAR_MAX = 440;
export const SIDEBAR_DEFAULT = 256;
/** Dragging the edge this far below the minimum folds the sidebar into the icon rail. */
export const SIDEBAR_COLLAPSE_AT = SIDEBAR_MIN - 72;

export const WIDTH_KEY = "moloko.sidebar.width";
export const COLLAPSED_KEY = "moloko.sidebar.collapsed";

export function clampWidth(px: number): number {
  return Math.round(Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, px)));
}

/** Runs inline before the first paint; mirrors applyWidth/setCollapsed in use-sidebar.ts (same keys and limits). */
export const SIDEBAR_INIT_SCRIPT = `try{var s=localStorage,d=document.documentElement,w=parseInt(s.getItem("${WIDTH_KEY}"),10);if(w>0)d.style.setProperty("--sidebar-width",Math.min(${SIDEBAR_MAX},Math.max(${SIDEBAR_MIN},w))+"px");if(s.getItem("${COLLAPSED_KEY}")==="1")d.dataset.sidebar="collapsed"}catch(e){}`;

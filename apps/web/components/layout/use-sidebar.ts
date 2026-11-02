"use client";

import { useSyncExternalStore } from "react";

import { clampWidth, COLLAPSED_KEY, SIDEBAR_DEFAULT, WIDTH_KEY } from "./sidebar-prefs";

const EVENT = "moloko:sidebar";

function store(key: string, value: string | null) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    // Private mode or blocked storage: the change still applies to this page.
  }
}

/** Shows `px` at once (CSS variable only); `save` also remembers it for this device. */
export function applyWidth(px: number, save = false): number {
  const width = clampWidth(px);
  document.documentElement.style.setProperty("--sidebar-width", `${width}px`);
  if (save) store(WIDTH_KEY, width === SIDEBAR_DEFAULT ? null : String(width));
  window.dispatchEvent(new Event(EVENT));
  return width;
}

export function currentWidth(): number {
  const value = parseInt(getComputedStyle(document.documentElement).getPropertyValue("--sidebar-width"), 10);
  return Number.isFinite(value) ? value : SIDEBAR_DEFAULT;
}

export function setCollapsed(collapsed: boolean) {
  if (collapsed) document.documentElement.dataset.sidebar = "collapsed";
  else delete document.documentElement.dataset.sidebar;
  store(COLLAPSED_KEY, collapsed ? "1" : null);
  window.dispatchEvent(new Event(EVENT));
}

function subscribe(onChange: () => void) {
  window.addEventListener(EVENT, onChange);
  return () => window.removeEventListener(EVENT, onChange);
}

/** For aria attributes and labels; the layout itself follows the CSS. */
export function useSidebarCollapsed(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => document.documentElement.dataset.sidebar === "collapsed",
    () => false,
  );
}

export function useSidebarWidth(): number {
  return useSyncExternalStore(subscribe, currentWidth, () => SIDEBAR_DEFAULT);
}

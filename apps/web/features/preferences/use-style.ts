"use client";

import { useSyncExternalStore } from "react";

import { isStyle, STYLE_KEY, type StyleName } from "./style-prefs";

const CHANGED = "moloko:style";

function read(): StyleName {
  try {
    const value = window.localStorage.getItem(STYLE_KEY);
    return isStyle(value) ? value : "classic";
  } catch {
    return "classic";
  }
}

/** Switch the style on this device (the attribute at once, the choice for the next visits). */
export function applyStyle(style: StyleName): void {
  const root = document.documentElement;
  if (style === "classic") delete root.dataset.style;
  else root.dataset.style = style;
  try {
    window.localStorage.setItem(STYLE_KEY, style);
  } catch {
    /* private mode: it applies now, just not next time */
  }
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(onChange: () => void): () => void {
  window.addEventListener(CHANGED, onChange);
  window.addEventListener("storage", onChange);
  return () => {
    window.removeEventListener(CHANGED, onChange);
    window.removeEventListener("storage", onChange);
  };
}

/** The current style; null on the server (it lives in this device's storage). */
export function useStyle(): StyleName | null {
  return useSyncExternalStore(subscribe, read, () => null);
}

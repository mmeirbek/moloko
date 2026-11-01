"use client";

import { useEffect } from "react";

/** Registers the service worker in production builds (dev keeps hot reload simple). */
export function RegisterServiceWorker() {
  useEffect(() => {
    if (process.env.NODE_ENV !== "production" || !("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => {
      /* not fatal: the app works without it */
    });
  }, []);
  return null;
}

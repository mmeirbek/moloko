"use client";

import { useEffect, useState } from "react";

/** `value`, but only after it stopped changing for `delayMs` (search boxes: one request per pause, not per key). */
export function useDebounced<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

/** "<title> · moloko" in the browser tab for pages whose name comes from data (a chat, a task, an agent). */
export function useDocumentTitle(title: string | null | undefined) {
  useEffect(() => {
    if (title) document.title = `${title} · moloko`;
  }, [title]);
}

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/** Accept only same-site relative paths, so `?next=` can never redirect off-site. */
export function safeNextPath(value: string | null | undefined, fallback = "/chat"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) {
    return fallback;
  }
  if (value === "/login" || value.startsWith("/login?") || value.startsWith("/login/")) {
    return fallback;
  }
  return value;
}

/**
 * A one-line title without Markdown: chat and task titles are cut from the first message,
 * which may contain **bold**, `code`, links or a "# heading". snake_case words stay intact.
 */
export function plainTitle(text: string): string {
  return text
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1") // [text](url), ![alt](src) → text
    .replace(/(\*\*|__|~~)(\S(?:.*?\S)?)\1/g, "$2") // **bold**, __bold__, ~~strike~~
    .replace(/`([^`]+)`/g, "$1") // `code`
    .replace(/(^|\s)\*(\S(?:.*?\S)?)\*(?=\s|$|[.,!?:;])/g, "$1$2") // *italic*
    .replace(/^\s{0,3}(?:#{1,6}|>|[-*+]|\d+[.)])\s+/, "") // heading, quote or list marker in front
    .replace(/\s+/g, " ")
    .trim();
}

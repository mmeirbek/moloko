export const locales = ["ru", "en"] as const;
export type Locale = (typeof locales)[number];

/** Used when neither the locale cookie nor Accept-Language picks a supported locale. */
export const defaultLocale: Locale = "ru";
export const LOCALE_COOKIE = "moloko_locale";
/** The browser's IANA time zone (set by TimeZoneSync), so dates show the owner's local time. */
export const TIMEZONE_COOKIE = "moloko_tz";

/** A time zone name the runtime knows (e.g. "Asia/Almaty"); anything else is ignored. */
export function isTimeZone(value: unknown): value is string {
  if (typeof value !== "string" || value.length === 0 || value.length > 64) return false;
  try {
    new Intl.DateTimeFormat("en", { timeZone: value });
    return true;
  } catch {
    return false;
  }
}

export function isLocale(value: unknown): value is Locale {
  return typeof value === "string" && (locales as readonly string[]).includes(value);
}

/** Pick the first supported language from an Accept-Language header. */
export function localeFromAcceptLanguage(header: string | null | undefined): Locale | null {
  if (!header) return null;
  const ranked = header
    .split(",")
    .map((part) => {
      const [tag = "", ...params] = part.trim().split(";");
      const q = params.find((p) => p.trim().startsWith("q="));
      return { base: tag.toLowerCase().split("-")[0], q: q ? Number(q.split("=")[1]) : 1 };
    })
    .filter((entry) => !Number.isNaN(entry.q) && entry.q > 0)
    .sort((a, b) => b.q - a.q);
  return ranked.map((entry) => entry.base).find(isLocale) ?? null;
}

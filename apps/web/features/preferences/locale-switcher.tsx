"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { LOCALE_COOKIE, locales, type Locale } from "@/i18n/config";
import { cn } from "@/lib/utils";

const LABELS: Record<Locale, string> = { ru: "RU", en: "EN" };
// Each language in its own name (not translated), for the roomy variant.
const NAMES: Record<Locale, string> = { ru: "Русский", en: "English" };

function persistLocale(locale: Locale) {
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;
}

export function LocaleSwitcher({ className, wide = false }: { className?: string; wide?: boolean }) {
  const t = useTranslations("preferences");
  const active = useLocale();
  const router = useRouter();
  const [pending, startTransition] = useTransition();

  function choose(locale: Locale) {
    if (locale === active) return;
    persistLocale(locale);
    startTransition(() => router.refresh());
  }

  return (
    <div
      role="group"
      aria-label={t("language")}
      className={cn(
        wide ? "grid grid-cols-2 gap-1 rounded-lg border p-1 text-sm" : "inline-flex rounded-md border p-0.5 text-xs",
        className,
      )}
    >
      {locales.map((locale) => (
        <button
          key={locale}
          type="button"
          disabled={pending}
          aria-pressed={locale === active}
          lang={locale}
          onClick={() => choose(locale)}
          className={cn(
            "font-medium transition-colors",
            wide ? "min-h-10 rounded-md px-2" : "min-h-7 min-w-8 rounded-sm px-2 py-1",
            locale === active
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {wide ? NAMES[locale] : LABELS[locale]}
        </button>
      ))}
    </div>
  );
}

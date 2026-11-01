"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useTransition } from "react";

import { LOCALE_COOKIE, locales, type Locale } from "@/i18n/config";
import { cn } from "@/lib/utils";

const LABELS: Record<Locale, string> = { ru: "RU", en: "EN" };

function persistLocale(locale: Locale) {
  document.cookie = `${LOCALE_COOKIE}=${locale}; path=/; max-age=31536000; samesite=lax`;
}

export function LocaleSwitcher({ className }: { className?: string }) {
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
      className={cn("inline-flex rounded-md border p-0.5 text-xs", className)}
    >
      {locales.map((locale) => (
        <button
          key={locale}
          type="button"
          disabled={pending}
          aria-pressed={locale === active}
          onClick={() => choose(locale)}
          className={cn(
            "rounded-sm px-2 py-1 font-medium transition-colors",
            locale === active
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {LABELS[locale]}
        </button>
      ))}
    </div>
  );
}

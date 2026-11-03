"use client";

import { useTranslations } from "next-intl";

import { Check } from "@/components/icons";
import { cn } from "@/lib/utils";

import { STYLES, SWATCHES } from "./style-prefs";
import { applyStyle, useStyle } from "./use-style";

/** The styles side by side, each with its colours in light and dark. */
export function StyleSwitcher({ className }: { className?: string }) {
  const t = useTranslations("preferences.styles");
  const current = useStyle();
  return (
    <div role="group" aria-label={t("label")} className={cn("grid grid-cols-2 gap-2 sm:grid-cols-3", className)} data-testid="style-switcher">
      {STYLES.map((style) => {
        const on = current === style;
        return (
          <button
            key={style}
            type="button"
            aria-pressed={on}
            onClick={() => applyStyle(style)}
            className={cn(
              "flex flex-col gap-2 rounded-xl border p-2.5 text-left transition-colors",
              on ? "border-primary ring-2 ring-primary/30" : "hover:bg-accent",
            )}
          >
            <span className="flex gap-1" aria-hidden>
              {[...SWATCHES[style].light, ...SWATCHES[style].dark].map((color, i) => (
                <svg key={i} width="14" height="14" viewBox="0 0 14 14" className="shrink-0">
                  <circle cx="7" cy="7" r="6.5" fill={color} stroke="currentColor" strokeOpacity="0.2" />
                </svg>
              ))}
            </span>
            <span className="flex items-center gap-1.5 text-sm font-medium">
              {on && <Check className="size-3.5" />}
              {t(`${style}.name`)}
            </span>
            <span className="text-xs text-muted-foreground">{t(`${style}.hint`)}</span>
          </button>
        );
      })}
    </div>
  );
}

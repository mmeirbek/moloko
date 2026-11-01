"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const ORDER = ["system", "light", "dark"] as const;
const subscribe = () => () => {};

export function ThemeToggle() {
  const t = useTranslations("preferences");
  const { theme, setTheme } = useTheme();
  // The theme is only known on the client; render a stable icon until hydrated.
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const current = mounted ? ((theme as (typeof ORDER)[number]) ?? "system") : "system";
  const next = ORDER[(ORDER.indexOf(current) + 1) % ORDER.length] ?? "system";
  const Icon = current === "dark" ? Moon : current === "light" ? Sun : Monitor;
  const label = {
    system: t("themeSystem"),
    light: t("themeLight"),
    dark: t("themeDark"),
  }[current];

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={() => setTheme(next)}
      aria-label={`${t("toggleTheme")} (${label})`}
      title={`${t("theme")}: ${label}`}
    >
      <Icon />
    </Button>
  );
}

/** All three themes side by side, with words — clearer than a cycling icon (phone "More" menu). */
export function ThemeSwitcher() {
  const t = useTranslations("preferences");
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(subscribe, () => true, () => false);
  const current = mounted ? (theme ?? "system") : null;
  const options = [
    { value: "light", label: t("themeLight"), Icon: Sun },
    { value: "dark", label: t("themeDark"), Icon: Moon },
    { value: "system", label: t("themeSystemShort"), Icon: Monitor },
  ] as const;
  return (
    <div role="group" aria-label={t("theme")} className="grid grid-cols-3 gap-1 rounded-lg border p-1">
      {options.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          aria-pressed={current === value}
          title={value === "system" ? t("themeSystem") : undefined}
          onClick={() => setTheme(value)}
          className={cn(
            "flex min-h-10 items-center justify-center gap-1.5 rounded-md px-2 text-sm transition-colors",
            current === value ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
          )}
        >
          <Icon className="size-4 shrink-0" aria-hidden />
          <span className="truncate">{label}</span>
        </button>
      ))}
    </div>
  );
}

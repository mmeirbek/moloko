"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";

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

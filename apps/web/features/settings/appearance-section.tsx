"use client";

import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LocaleSwitcher } from "@/features/preferences/locale-switcher";
import { ThemeSwitcher } from "@/features/preferences/theme-toggle";

/** Theme and language in words (the sidebar has compact versions of the same switches). */
export function AppearanceSection() {
  const t = useTranslations("preferences");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("appearanceTitle")}</CardTitle>
        <CardDescription>{t("appearanceHint")}</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">{t("theme")}</p>
          <ThemeSwitcher />
        </div>
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">{t("language")}</p>
          <LocaleSwitcher wide />
        </div>
      </CardContent>
    </Card>
  );
}

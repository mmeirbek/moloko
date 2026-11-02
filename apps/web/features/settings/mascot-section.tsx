"use client";

import { useTranslations } from "next-intl";
import { useSyncExternalStore } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { MilkBottle } from "@/features/mascot/milk-bottle";
import { PixelCow } from "@/features/mascot/pixel-cow";
import { playMoo } from "@/features/mascot/moo";
import { DEFAULT_MASCOT, mascotSnapshot, saveMascotPrefs, subscribeMascot } from "@/features/mascot/prefs";

export function MascotSection() {
  const t = useTranslations("mascot.settings");
  const prefs = useSyncExternalStore(subscribeMascot, mascotSnapshot, () => DEFAULT_MASCOT);
  return (
    <Card data-testid="mascot-settings">
      <CardHeader>
        <CardTitle>{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4 sm:flex-row sm:items-center">
        <div className="flex items-end gap-3">
          <PixelCow size={80} interactive />
          <PixelCow mood="sleep" size={48} outfit={false} />
          <MilkBottle percent={60} size={24} />
        </div>
        <div className="flex flex-col gap-3 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={prefs.seasonal}
              onChange={(e) => saveMascotPrefs({ ...prefs, seasonal: e.target.checked })}
              className="size-4"
            />
            {t("seasonal")}
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={prefs.sound}
              onChange={(e) => {
                saveMascotPrefs({ ...prefs, sound: e.target.checked });
                if (e.target.checked) playMoo();
              }}
              className="size-4"
            />
            {t("sound")}
          </label>
          <p className="text-xs text-muted-foreground">{t("hint")}</p>
        </div>
      </CardContent>
    </Card>
  );
}

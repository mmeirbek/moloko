"use client";

import { useTranslations } from "next-intl";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { MemoryPanel } from "@/features/memory/memory-panel";

/** Settings → Memory: what every agent knows about the owner, and shared project notes. */
export function MemorySection() {
  const t = useTranslations("memory");
  return (
    <Card id="memory">
      <CardHeader>
        <CardTitle>{t("sharedTitle")}</CardTitle>
        <CardDescription>{t("sharedDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <MemoryPanel scope={{ shared: true }} />
      </CardContent>
    </Card>
  );
}

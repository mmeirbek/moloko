import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { Button } from "@/components/ui/button";
import { BackupsSection } from "@/features/settings/backups-section";
import { MascotSection } from "@/features/settings/mascot-section";
import { MemorySection } from "@/features/settings/memory-section";
import { NotificationsSection } from "@/features/settings/notifications-section";
import { ProvidersSection } from "@/features/settings/providers-section";
import { KillSwitchCard } from "@/features/system/kill-switch";
import { AccountCard, SystemStatus } from "@/features/system/system-status";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.settings");
  return { title: t("title") };
}

export default async function SettingsPage() {
  const t = await getTranslations("pages.settings");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="grid max-w-4xl gap-4">
        <div className="grid gap-4 md:grid-cols-2">
          <SystemStatus />
          <AccountCard />
          <KillSwitchCard />
        </div>
        <ProvidersSection />
        <MemorySection />
        <NotificationsSection />
        <MascotSection />
        <BackupsSection />
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" asChild>
            <Link href="/settings/costs">{t("costsLink")}</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/settings/audit">{t("auditLink")}</Link>
          </Button>
          <Button variant="outline" asChild>
            <Link href="/integrations">{t("integrationsLink")}</Link>
          </Button>
        </div>
      </div>
    </>
  );
}

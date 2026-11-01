import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { MemorySection } from "@/features/settings/memory-section";
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
      </div>
    </>
  );
}

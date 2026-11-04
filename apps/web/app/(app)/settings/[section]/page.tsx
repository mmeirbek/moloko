import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { ArrowLeft } from "@/components/icons";
import { Page } from "@/components/layout/page";
import { FullAccessForAllCard } from "@/features/agents/agent-full-access";
import { AiServicesSection } from "@/features/settings/ai-services-section";
import { AppearanceSection } from "@/features/settings/appearance-section";
import { BackupsSection } from "@/features/settings/backups-section";
import { MascotSection } from "@/features/settings/mascot-section";
import { MemorySection } from "@/features/settings/memory-section";
import { NotificationsSection } from "@/features/settings/notifications-section";
import { PasskeysCard } from "@/features/settings/passkeys-card";
import { ProvidersSection } from "@/features/settings/providers-section";
import { isSection, SECTIONS, type SectionId } from "@/features/settings/sections";
import { SessionLifetimeCard } from "@/features/settings/session-lifetime";
import { KillSwitchCard } from "@/features/system/kill-switch";
import { AccountCard, SystemStatus } from "@/features/system/system-status";

type Params = { params: Promise<{ section: string }> };

export function generateStaticParams() {
  return SECTIONS.map((section) => ({ section }));
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { section } = await params;
  const t = await getTranslations("pages.settings");
  return { title: isSection(section) ? t(`sections.${section}.title`) : t("title") };
}

const CONTENT: Record<SectionId, () => ReactNode> = {
  ai: () => (
    <>
      <ProvidersSection />
      <AiServicesSection />
    </>
  ),
  notifications: () => <NotificationsSection />,
  agents: () => (
    <>
      <FullAccessForAllCard />
      <KillSwitchCard />
      <MemorySection />
    </>
  ),
  appearance: () => (
    <>
      <AppearanceSection />
      <MascotSection />
    </>
  ),
  system: () => (
    <>
      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <SystemStatus />
        <AccountCard />
      </div>
      <SessionLifetimeCard />
      <PasskeysCard />
      <BackupsSection />
    </>
  ),
};

/** One section of the settings on its own page, with the way back to the list. */
export default async function SettingsSectionPage({ params }: Params) {
  const { section } = await params;
  if (!isSection(section)) notFound();
  const t = await getTranslations("pages.settings");
  return (
    <Page className="max-w-3xl">
      <Link href="/settings" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
        <ArrowLeft className="size-4" /> {t("title")}
      </Link>
      <section aria-labelledby="section-title" className="flex flex-col gap-4" data-testid={`settings-${section}`}>
        <div className="flex flex-col gap-1">
          <h1 id="section-title" className="text-2xl font-semibold tracking-tight">
            {t(`sections.${section}.title`)}
          </h1>
          <p className="text-sm text-muted-foreground">{t(`sections.${section}.hint`)}</p>
        </div>
        {CONTENT[section]()}
      </section>
    </Page>
  );
}

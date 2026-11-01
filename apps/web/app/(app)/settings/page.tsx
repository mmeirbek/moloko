import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { AiServicesSection } from "@/features/settings/ai-services-section";
import { AppearanceSection } from "@/features/settings/appearance-section";
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

// In the order a new owner needs them: without an AI provider nothing works.
const SECTIONS = ["ai", "notifications", "agents", "appearance", "system"] as const;

function Section({ id, title, hint, children }: { id: string; title: string; hint: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="flex scroll-mt-28 flex-col gap-3 md:scroll-mt-16">
      <div className="flex flex-col gap-0.5">
        <h2 id={`${id}-title`} className="text-lg font-semibold">
          {title}
        </h2>
        <p className="text-sm text-muted-foreground">{hint}</p>
      </div>
      {children}
    </section>
  );
}

export default async function SettingsPage() {
  const t = await getTranslations("pages.settings");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      {/* Jump to a section: one row, scrolls sideways on phones, stays under the header. */}
      <nav
        aria-label={t("sectionsLabel")}
        className="sticky top-14 z-[5] -mx-4 mb-6 flex gap-1 overflow-x-auto border-b bg-background/95 px-4 py-2 backdrop-blur md:top-0 md:-mx-8 md:px-8"
      >
        {SECTIONS.map((id) => (
          <a
            key={id}
            href={`#${id}`}
            className="flex min-h-9 shrink-0 items-center rounded-full px-3.5 text-sm whitespace-nowrap text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            {t(`sections.${id}.title`)}
          </a>
        ))}
        <Link
          href="/settings/costs"
          className="flex min-h-9 shrink-0 items-center rounded-full px-3.5 text-sm whitespace-nowrap text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          {t("costsLink")}
        </Link>
        <Link
          href="/settings/audit"
          className="flex min-h-9 shrink-0 items-center rounded-full px-3.5 text-sm whitespace-nowrap text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          {t("auditLink")}
        </Link>
      </nav>
      <div className="grid max-w-4xl grid-cols-1 gap-10">
        <Section id="ai" title={t("sections.ai.title")} hint={t("sections.ai.hint")}>
          <ProvidersSection />
          <AiServicesSection />
        </Section>
        <Section id="notifications" title={t("sections.notifications.title")} hint={t("sections.notifications.hint")}>
          <NotificationsSection />
        </Section>
        <Section id="agents" title={t("sections.agents.title")} hint={t("sections.agents.hint")}>
          <KillSwitchCard />
          <MemorySection />
        </Section>
        <Section id="appearance" title={t("sections.appearance.title")} hint={t("sections.appearance.hint")}>
          <AppearanceSection />
          <MascotSection />
        </Section>
        <Section id="system" title={t("sections.system.title")} hint={t("sections.system.hint")}>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <SystemStatus />
            <AccountCard />
          </div>
          <BackupsSection />
        </Section>
      </div>
    </>
  );
}

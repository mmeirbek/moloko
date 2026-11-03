import type { Metadata } from "next";
import Link from "next/link";
import { getTranslations } from "next-intl/server";

import { ChevronRight, type IconComponent } from "@/components/icons";
import { Page } from "@/components/layout/page";
import { PageHeader } from "@/components/layout/page-header";
import { EXTRA_PAGES, SECTION_ICONS, SECTIONS } from "@/features/settings/sections";
import { SettingsHashRedirect } from "@/features/settings/settings-hash-redirect";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.settings");
  return { title: t("title") };
}

function Row({ href, icon: Icon, title, hint }: { href: string; icon: IconComponent; title: string; hint?: string }) {
  return (
    <li>
      <Link href={href} className="flex items-center gap-3 px-4 py-3.5 transition-colors hover:bg-accent" data-testid="settings-row">
        <span className="flex size-9 shrink-0 items-center justify-center rounded-lg bg-muted">
          <Icon className="size-5" />
        </span>
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="font-medium">{title}</span>
          {hint && <span className="text-sm text-muted-foreground">{hint}</span>}
        </span>
        <ChevronRight className="size-4 shrink-0 text-muted-foreground" />
      </Link>
    </li>
  );
}

/** The sections as a list (each opens its own page), like the iPhone's settings. */
export default async function SettingsPage() {
  const t = await getTranslations("pages.settings");
  return (
    <Page className="max-w-2xl">
      <SettingsHashRedirect />
      <PageHeader title={t("title")} description={t("description")} />
      <nav aria-label={t("sectionsLabel")} className="flex flex-col gap-6">
        <ul className="divide-y overflow-hidden rounded-xl bg-card pixel-frame">
          {SECTIONS.map((id) => (
            <Row key={id} href={`/settings/${id}`} icon={SECTION_ICONS[id]} title={t(`sections.${id}.title`)} hint={t(`sections.${id}.hint`)} />
          ))}
        </ul>
        <ul className="divide-y overflow-hidden rounded-xl bg-card pixel-frame">
          {EXTRA_PAGES.map((page) => (
            <Row key={page.href} href={page.href} icon={page.icon} title={t(page.key)} />
          ))}
        </ul>
      </nav>
    </Page>
  );
}

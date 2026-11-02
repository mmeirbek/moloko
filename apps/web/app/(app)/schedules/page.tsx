import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { Page } from "@/components/layout/page";
import { PageHeader } from "@/components/layout/page-header";
import { SchedulesView } from "@/features/schedules/schedules-view";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.schedules");
  return { title: t("title") };
}

export default async function SchedulesPage() {
  const t = await getTranslations("pages.schedules");
  return (
    <Page>
      <PageHeader title={t("title")} description={t("description")} />
      <SchedulesView />
    </Page>
  );
}

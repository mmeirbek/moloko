import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { CostsView } from "@/features/costs/costs-view";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("costs");
  return { title: t("title") };
}

export default async function CostsPage() {
  const t = await getTranslations("costs");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <CostsView />
    </>
  );
}

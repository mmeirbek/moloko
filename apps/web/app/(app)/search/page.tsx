import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { Page } from "@/components/layout/page";
import { PageHeader } from "@/components/layout/page-header";
import { SearchView } from "@/features/search/search-view";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("search");
  return { title: t("title") };
}

export default async function SearchPage() {
  const t = await getTranslations("search");
  return (
    <Page>
      <PageHeader title={t("title")} description={t("description")} />
      <SearchView />
    </Page>
  );
}

import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { ApprovalsView } from "@/features/approvals/approvals-view";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("approvals");
  return { title: t("title") };
}

export default async function ApprovalsPage() {
  const t = await getTranslations("approvals");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <ApprovalsView />
    </>
  );
}

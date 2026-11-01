import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { AuditLog } from "@/features/settings/audit-log";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("audit");
  return { title: t("title") };
}

export default async function AuditPage() {
  const t = await getTranslations("audit");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <AuditLog />
    </>
  );
}

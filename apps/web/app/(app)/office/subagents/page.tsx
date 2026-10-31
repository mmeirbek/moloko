import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";

import { PageHeader } from "@/components/layout/page-header";
import { SubagentOffice } from "@/features/runs/subagent-office";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.subagentOffice");
  return { title: t("title") };
}

export default async function SubagentOfficePage() {
  const t = await getTranslations("pages.subagentOffice");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <Suspense>
        <SubagentOffice />
      </Suspense>
    </>
  );
}

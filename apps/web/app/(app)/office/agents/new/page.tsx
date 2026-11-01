import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { AgentForm } from "@/features/agents/agent-form";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("agents");
  return { title: t("new") };
}

export default async function NewAgentPage() {
  const t = await getTranslations("agents");
  return (
    <>
      <PageHeader title={t("new")} description={t("form.newDescription")} />
      <AgentForm />
    </>
  );
}

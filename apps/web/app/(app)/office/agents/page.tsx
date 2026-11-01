import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { AgentsPanel } from "@/features/agents/agents-panel";
import { OfficeView } from "@/features/office/office-view";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.agentOffice");
  return { title: t("title") };
}

export default async function AgentOfficePage() {
  const t = await getTranslations("pages.agentOffice");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="mb-8">
        <OfficeView initialMode="agents" />
      </div>
      <AgentsPanel types={["autonomous", "orchestrator"]} />
    </>
  );
}

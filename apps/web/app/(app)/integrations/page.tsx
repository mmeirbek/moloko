import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PageHeader } from "@/components/layout/page-header";
import { GitHubSection } from "@/features/integrations/github-section";
import { McpSection } from "@/features/integrations/mcp-section";
import { SandboxSection } from "@/features/integrations/sandbox-section";
import { ToolsSection } from "@/features/integrations/tools-section";
import { WorkspacesSection } from "@/features/integrations/workspaces-section";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("pages.integrations");
  return { title: t("title") };
}

export default async function IntegrationsPage() {
  const t = await getTranslations("pages.integrations");
  return (
    <>
      <PageHeader title={t("title")} description={t("description")} />
      <div className="grid max-w-4xl gap-4">
        <ToolsSection />
        <SandboxSection />
        <GitHubSection />
        <McpSection />
        <WorkspacesSection />
      </div>
    </>
  );
}

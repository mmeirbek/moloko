import { Page } from "@/components/layout/page";
import { AgentDetail } from "@/features/agents/agent-detail";

export default async function AgentPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ tab?: string | string[] }>;
}) {
  const { id } = await params;
  const { tab } = await searchParams;
  return (
    <Page>
      <AgentDetail key={id} agentId={id} initialTab={typeof tab === "string" ? tab : undefined} />
    </Page>
  );
}

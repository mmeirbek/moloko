import { Page } from "@/components/layout/page";
import { AgentDetail } from "@/features/agents/agent-detail";

export default async function AgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return (
    <Page>
      <AgentDetail key={id} agentId={id} />
    </Page>
  );
}

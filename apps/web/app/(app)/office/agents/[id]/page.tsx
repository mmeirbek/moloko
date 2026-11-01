import { AgentDetail } from "@/features/agents/agent-detail";

export default async function AgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AgentDetail key={id} agentId={id} />;
}

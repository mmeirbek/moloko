import { RunRedirect } from "@/features/runs/run-redirect";

/** An Orchestrator run (links from chats and older notifications) opens its task's page. */
export default async function RunPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = await params;
  return <RunRedirect runId={runId} />;
}

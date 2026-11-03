"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useMemo } from "react";

import { createTask, taskKeys } from "@/lib/api/agents";
import { startRun } from "@/lib/api/runs";
import { useRealtimeStore } from "@/lib/realtime/store";

import { parseAgentMention, taskTitle, type Mention, type MentionAgent } from "./agent-mention";

/** The Orchestrator answers to its name in both languages, even before it first worked. */
const ORCHESTRATOR_NAMES = ["Оркестратор", "Orchestrator"];

/** The agents a message can be addressed to: the office's agents and the Orchestrator. */
export function useMentionAgents(): MentionAgent[] {
  const agents = useRealtimeStore((s) => s.agents);
  return useMemo(() => {
    const office = Object.values(agents)
      .filter((a) => !a.archived_at && a.agent_type === "autonomous")
      .map((a) => ({ id: a.id, name: a.name }));
    const taken = new Set(office.map((a) => a.name.toLocaleLowerCase()));
    const orchestrator = ORCHESTRATOR_NAMES.filter((name) => !taken.has(name.toLocaleLowerCase())).map((name) => ({
      id: `orchestrator:${name}`,
      name,
      orchestrator: true,
    }));
    return [...office.sort((a, b) => a.name.localeCompare(b.name)), ...orchestrator];
  }, [agents]);
}

/** «@Кодер почини…» → that agent's task, and its page opens (the task page is its chat). */
export function useAgentTask() {
  const agents = useMentionAgents();
  const router = useRouter();
  const queryClient = useQueryClient();
  return {
    match: (text: string) => parseAgentMention(text, agents),
    start: async (mention: Mention) => {
      const title = taskTitle(mention.text);
      const task = mention.agent.orchestrator
        ? (await startRun({ title, description: mention.text })).task
        : await createTask({ title, description: mention.text, agent_id: mention.agent.id });
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
      router.push(`/tasks/${task.id}`);
    },
  };
}

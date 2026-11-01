"use client";

import type { AgentOut } from "@moloko/shared-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/ui/confirm";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { agentAction, agentKeys, taskKeys } from "@/lib/api/agents";
import { useRealtimeStore } from "@/lib/realtime/store";

/** Agent statuses that mean "doing something right now". */
export const ACTIVE_STATUSES = new Set(["planning", "working", "waiting", "reviewing"]);

/** The agent has work in hand (running, paused or holding a task). */
export function isAgentBusy(agent: Pick<AgentOut, "status" | "current_task_id">): boolean {
  return ACTIVE_STATUSES.has(agent.status) || agent.status === "paused" || Boolean(agent.current_task_id);
}

/** The Orchestrator is still on a task: a new one would be refused ("agent busy") — say so instead. */
export function useOrchestratorBusy(): boolean {
  const orchestrator = useRealtimeStore((s) => Object.values(s.agents).find((a) => a.agent_type === "orchestrator"));
  return orchestrator ? isAgentBusy(orchestrator) : false;
}

/**
 * Pause / resume / stop for one agent — the same rules everywhere (agent list, agent page,
 * office inspector). Stop always asks first; buttons wait for the server; errors are shown.
 * `children` are extra buttons for the same row.
 */
export function AgentControls({
  agent,
  size = "sm",
  children,
}: {
  agent: Pick<AgentOut, "id" | "name" | "status" | "current_task_id">;
  size?: "sm" | "default";
  children?: ReactNode;
}) {
  const t = useTranslations("agents");
  const confirm = useConfirm();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const task = useRealtimeStore((s) => (agent.current_task_id ? s.tasks[agent.current_task_id] : undefined));
  const action = useMutation({
    mutationFn: (a: "pause" | "resume" | "stop") => agentAction(agent.id, a),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
  const canPause = ACTIVE_STATUSES.has(agent.status);
  const canResume = agent.status === "paused" || task?.status === "waiting";
  const canStop = isAgentBusy(agent) || agent.status === "failed";

  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1">
        {canPause && (
          <Button size={size} variant="outline" disabled={action.isPending} onClick={() => action.mutate("pause")}>
            <Pause /> {t("pause")}
          </Button>
        )}
        {canResume && (
          <Button size={size} variant="outline" disabled={action.isPending} onClick={() => action.mutate("resume")}>
            <Play /> {t("resume")}
          </Button>
        )}
        {canStop && (
          <Button
            size={size}
            variant="ghost"
            disabled={action.isPending}
            onClick={async () => {
              if (await confirm({ title: t("confirmStop", { name: agent.name }), confirmLabel: t("stop"), destructive: true }))
                action.mutate("stop");
            }}
          >
            <Square /> {t("stop")}
          </Button>
        )}
        {children}
      </div>
      {action.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(action.error).message}
        </p>
      )}
    </div>
  );
}

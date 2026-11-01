"use client";

import type { AgentOut, EventOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, Pause, Play, Settings2, Square, X } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusBadge } from "@/features/agents/status-badge";
import { ApprovalCard } from "@/features/approvals/approval-card";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { modelLabel } from "@/features/chat/model-picker";
import { agentAction, agentKeys, taskKeys } from "@/lib/api/agents";
import { listPickerModels, modelKeys } from "@/lib/api/chat";
import { api } from "@/lib/api/client";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

const ACTIVE = new Set(["planning", "working", "waiting", "reviewing"]);

const recentEvents = (agentId: string, signal?: AbortSignal) =>
  api.request<EventOut[]>(`/events?agent_id=${agentId}&latest=true&limit=8`, {
    signal,
  });

/** Spec 18.5: everything about one agent, with its controls. */
export function AgentInspector({
  agent,
  onClose,
  className,
}: {
  agent: AgentOut;
  onClose: () => void;
  className?: string;
}) {
  const t = useTranslations("office.inspector");
  const tStatus = useTranslations("status");
  const tTypes = useTranslations("agents.types");
  const format = useFormatter();
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const [showLogs, setShowLogs] = useState(false);
  const task = useRealtimeStore((s) => (agent.current_task_id ? s.tasks[agent.current_task_id] : undefined));
  const allApprovals = useRealtimeStore((s) => s.approvals);
  const approvals = Object.values(allApprovals).filter((a) => a.agent_id === agent.id && a.status === "pending");
  const models = useQuery({
    queryKey: modelKeys.picker,
    queryFn: ({ signal }) => listPickerModels(signal),
  });
  const events = useQuery({
    queryKey: [...agentKeys.detail(agent.id), "events", agent.status],
    queryFn: ({ signal }) => recentEvents(agent.id, signal),
  });
  const action = useMutation({
    mutationFn: (a: "pause" | "resume" | "stop") => agentAction(agent.id, a),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
  const model = models.data?.find((m) => m.id === agent.model_config_id);
  const isSub = agent.agent_type === "subagent";

  return (
    <aside
      aria-label={t("label", { name: agent.name })}
      className={cn(
        "flex max-h-[70%] flex-col gap-3 overflow-y-auto rounded-lg border bg-card/95 p-4 text-sm shadow-lg backdrop-blur",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <h2 className="truncate text-base font-semibold">{agent.name}</h2>
          <p className="text-xs text-muted-foreground">
            {tTypes(agent.agent_type as "autonomous")}
            {agent.specialization && ` · ${agent.specialization}`}
          </p>
        </div>
        <div className="flex items-center gap-1">
          <StatusBadge status={agent.status} />
          <Button size="icon" variant="ghost" className="size-7" onClick={onClose} aria-label={t("close")}>
            <X />
          </Button>
        </div>
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">{t("task")}</dt>
        <dd className="truncate">
          {task ? (
            <Link href={`/tasks/${task.id}`} className="underline-offset-2 hover:underline">
              {task.title}
            </Link>
          ) : (
            "—"
          )}
        </dd>
        <dt className="text-muted-foreground">{t("model")}</dt>
        <dd className="truncate">{model ? `${model.provider_name} · ${modelLabel(model)}` : t("defaultModel")}</dd>
        <dt className="text-muted-foreground">{t("autonomy")}</dt>
        <dd>{t(`autonomyLevels.${agent.autonomy_level as "supervised"}`)}</dd>
        <dt className="text-muted-foreground">{t("tools")}</dt>
        <dd className="truncate">{agent.allowed_tools.length ? agent.allowed_tools.join(", ") : t("noTools")}</dd>
      </dl>

      {task?.result && <p className="line-clamp-4 rounded-md bg-muted p-2 text-xs">{task.result}</p>}

      <div className="flex flex-wrap gap-1">
        {ACTIVE.has(agent.status) && (
          <Button size="sm" variant="outline" onClick={() => action.mutate("pause")}>
            <Pause /> {t("pause")}
          </Button>
        )}
        {agent.status === "paused" && (
          <Button size="sm" variant="outline" onClick={() => action.mutate("resume")}>
            <Play /> {t("resume")}
          </Button>
        )}
        {(ACTIVE.has(agent.status) || agent.status === "paused") && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (window.confirm(t("confirmStop", { name: agent.name }))) action.mutate("stop");
            }}
          >
            <Square /> {t("stop")}
          </Button>
        )}
        {task && (
          <Button size="sm" variant="ghost" asChild>
            <Link href={`/tasks/${task.id}`}>
              <ExternalLink /> {t("viewTask")}
            </Link>
          </Button>
        )}
        <Button size="sm" variant="ghost" onClick={() => setShowLogs((v) => !v)}>
          {t("logs")}
        </Button>
        {!isSub && (
          <Button size="sm" variant="ghost" asChild>
            <Link href={`/office/agents/${agent.id}`}>
              <Settings2 /> {t("settings")}
            </Link>
          </Button>
        )}
      </div>
      {action.error && (
        <p role="alert" className="text-xs text-destructive">
          {toMessage(action.error).message}
        </p>
      )}

      {approvals.map((a) => (
        <ApprovalCard key={a.id} approval={a} compact />
      ))}
      {showLogs && (
        <ol className="flex flex-col gap-0.5 border-t pt-2 text-xs">
          {events.data?.map((e) => (
            <li key={e.id} className="flex gap-2">
              <span className="text-muted-foreground tabular-nums">
                {format.dateTime(new Date(e.timestamp), {
                  timeStyle: "medium",
                })}
              </span>
              <span className="truncate">
                {e.type === "agent.status_changed"
                  ? tStatus(String((e.payload as { new_status?: string }).new_status) as "idle")
                  : e.type}
              </span>
            </li>
          ))}
        </ol>
      )}
    </aside>
  );
}

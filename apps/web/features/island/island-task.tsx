"use client";

import type { AgentOut } from "@moloko/shared-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useMemo, useState, type FormEvent } from "react";

import { Send } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { isAgentBusy, useOrchestratorBusy } from "@/features/agents/agent-controls";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { MicButton } from "@/features/voice/mic-button";
import { runAgent, taskKeys } from "@/lib/api/agents";
import { startRun } from "@/lib/api/runs";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

/** Who gets the task: the Orchestrator (splits it between agents) or one persistent agent. */
export type TaskTarget = "orchestrator" | string;

/** A task from the island: one line, to the Orchestrator or to an agent (also picked on the map). */
export function IslandTask({
  target,
  onTargetChange,
  className,
}: {
  target: TaskTarget;
  onTargetChange: (target: TaskTarget) => void;
  className?: string;
}) {
  const t = useTranslations("island.task");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const all = useRealtimeStore((s) => s.agents);
  const agents = useMemo(
    () =>
      Object.values(all)
        .filter((a) => a.agent_type === "autonomous")
        .sort((a, b) => a.name.localeCompare(b.name)),
    [all],
  );
  const orchestratorBusy = useOrchestratorBusy();
  const agent: AgentOut | undefined = target === "orchestrator" ? undefined : all[target];
  const busy = agent ? isAgentBusy(agent) : orchestratorBusy;
  const [text, setText] = useState("");
  const [sent, setSent] = useState<{ taskId: string; title: string } | null>(null);

  const start = useMutation({
    mutationFn: (submitted: string) => {
      const title = submitted.split("\n")[0]!.slice(0, 120).trim();
      return agent
        ? runAgent(agent.id, { title, description: submitted })
        : startRun({ title, description: submitted });
    },
    onSuccess: (started, submitted) => {
      // Only the text that was sent: the owner may already be typing the next task.
      setText((current) => (current === submitted ? "" : current));
      setSent({ taskId: started.task.id, title: started.task.title });
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });

  function submit(e: FormEvent) {
    e.preventDefault();
    const value = text.trim();
    if (!value || busy || start.isPending) return;
    setSent(null);
    start.mutate(value);
  }

  const name = agent?.name ?? t("orchestrator");
  return (
    <form onSubmit={submit} className={cn("flex flex-col gap-2", className)} data-testid="island-task">
      <div className="flex items-center gap-3">
        <select
          aria-label={t("to")}
          value={agent ? agent.id : "orchestrator"}
          onChange={(e) => onTargetChange(e.target.value)}
          className="h-10 max-w-48 min-w-0 shrink-0 bg-card px-2 text-sm pixel-frame pixel-sunken"
        >
          <option value="orchestrator">{t("orchestrator")}</option>
          {agents.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          aria-label={t("label")}
          placeholder={agent ? t("placeholderAgent", { name }) : t("placeholder")}
          className="h-10 min-w-0 flex-1 bg-card px-3 text-sm placeholder:text-muted-foreground pixel-frame pixel-sunken focus-visible:outline-none focus-visible:[--frame-color:var(--color-ring)]"
        />
        <MicButton onText={(spoken) => setText((cur) => (cur ? `${cur.trimEnd()} ${spoken}` : spoken))} />
        <Button type="submit" disabled={!text.trim() || busy || start.isPending} title={busy ? t("busy", { name }) : undefined}>
          <Send /> {t("start")}
        </Button>
      </div>
      <p className="min-h-[18px] text-xs text-muted-foreground" aria-live="polite">
        {start.isError ? (
          <span role="alert" className="text-destructive">
            {toMessage(start.error).message}
          </span>
        ) : busy ? (
          t("busy", { name })
        ) : sent ? (
          <>
            {t("sent", { title: sent.title })}{" "}
            <Link href={`/tasks/${sent.taskId}`} className="text-sky underline-offset-2 hover:underline">
              {t("open")}
            </Link>
          </>
        ) : (
          t("pickHint")
        )}
      </p>
    </form>
  );
}

"use client";

import type { AgentOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Plus, Send, Square } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { modelLabel } from "@/features/chat/model-picker";
import { agentAction, agentKeys, createAgent, listAgents, runAgent, taskKeys } from "@/lib/api/agents";
import { listPickerModels, modelKeys } from "@/lib/api/chat";
import { useRealtimeStore } from "@/lib/realtime/store";

import { StatusBadge } from "./status-badge";

const ACTIVE = new Set(["planning", "working", "waiting", "reviewing"]);

export function NewAgentForm({ onDone }: { onDone: () => void }) {
  const t = useTranslations("agents");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const models = useQuery({ queryKey: modelKeys.picker, queryFn: ({ signal }) => listPickerModels(signal) });
  const [name, setName] = useState("");
  const [systemPrompt, setSystemPrompt] = useState("");
  const [modelId, setModelId] = useState("");
  const create = useMutation({
    mutationFn: () => createAgent({ name: name.trim(), system_prompt: systemPrompt, model_config_id: modelId || null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: agentKeys.all });
      onDone();
    },
  });
  return (
    <form
      className="flex flex-col gap-3 rounded-lg border bg-card p-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        if (name.trim()) create.mutate();
      }}
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="agent-name">{t("name")}</Label>
        <Input id="agent-name" value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="agent-model">{t("model")}</Label>
        <select
          id="agent-model"
          value={modelId}
          onChange={(e) => setModelId(e.target.value)}
          className="h-10 rounded-md border border-input bg-background px-2 text-sm"
        >
          <option value="">{t("defaultModel")}</option>
          {models.data?.map((m) => (
            <option key={m.id} value={m.id}>
              {m.provider_name} · {modelLabel(m)}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="agent-prompt">{t("systemPrompt")}</Label>
        <textarea
          id="agent-prompt"
          rows={4}
          value={systemPrompt}
          onChange={(e) => setSystemPrompt(e.target.value)}
          placeholder={t("systemPromptHint")}
          className="rounded-md border border-input bg-background px-3 py-2 text-base md:text-sm"
        />
      </div>
      {create.error && <p role="alert" className="text-sm text-destructive">{toMessage(create.error).message}</p>}
      <div className="flex gap-2">
        <Button type="submit" disabled={!name.trim() || create.isPending}>
          {t("create")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {t("cancelForm")}
        </Button>
      </div>
    </form>
  );
}

function AgentCard({ agent }: { agent: AgentOut }) {
  const t = useTranslations("agents");
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const live = useRealtimeStore((s) => s.agents[agent.id]) ?? agent;
  const task = useRealtimeStore((s) => (live.current_task_id ? s.tasks[live.current_task_id] : undefined));
  const [taskTitle, setTaskTitle] = useState("");
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: agentKeys.all });
    void queryClient.invalidateQueries({ queryKey: taskKeys.all });
  };
  const run = useMutation({
    mutationFn: () => runAgent(agent.id, { title: taskTitle.trim(), description: "" }),
    onSuccess: () => {
      setTaskTitle("");
      invalidate();
    },
  });
  const action = useMutation({
    mutationFn: (a: "pause" | "resume" | "stop") => agentAction(agent.id, a),
    onSuccess: invalidate,
  });
  const error = run.error ?? action.error;
  const busy = ACTIVE.has(live.status) || live.status === "paused" || Boolean(live.current_task_id);

  return (
    <li className="flex flex-col gap-3 rounded-lg border bg-card p-4" data-agent-id={agent.id}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium">{live.name}</p>
          <p className="text-xs text-muted-foreground">{t(`types.${live.agent_type as "autonomous"}`)}</p>
        </div>
        <StatusBadge status={live.status} />
      </div>
      {task && (
        <Link href={`/tasks/${task.id}`} className="truncate text-sm underline-offset-2 hover:underline">
          {t("currentTask")}: {task.title}
        </Link>
      )}
      <div className="flex flex-wrap gap-1">
        {ACTIVE.has(live.status) && (
          <Button size="sm" variant="outline" onClick={() => action.mutate("pause")}>
            <Pause /> {t("pause")}
          </Button>
        )}
        {(live.status === "paused" || task?.status === "waiting") && (
          <Button size="sm" variant="outline" onClick={() => action.mutate("resume")}>
            <Play /> {t("resume")}
          </Button>
        )}
        {(busy || live.status === "failed") && (
          <Button size="sm" variant="ghost" onClick={() => action.mutate("stop")}>
            <Square /> {t("stop")}
          </Button>
        )}
      </div>
      {!busy && (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            if (taskTitle.trim()) run.mutate();
          }}
        >
          <Input
            aria-label={t("giveTask")}
            placeholder={t("giveTask")}
            value={taskTitle}
            onChange={(e) => setTaskTitle(e.target.value)}
          />
          <Button size="icon" type="submit" aria-label={t("start")} disabled={!taskTitle.trim() || run.isPending}>
            <Send />
          </Button>
        </form>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{toMessage(error).message}</p>}
    </li>
  );
}

export function AgentsPanel({ types }: { types?: string[] }) {
  const t = useTranslations("agents");
  const [creating, setCreating] = useState(false);
  const agents = useQuery({ queryKey: agentKeys.all, queryFn: ({ signal }) => listAgents(signal) });
  const shown = (agents.data ?? []).filter((a) => !types || types.includes(a.agent_type));
  return (
    <div className="flex flex-col gap-4">
      <div className="flex justify-end">
        {!creating && (
          <Button onClick={() => setCreating(true)}>
            <Plus /> {t("new")}
          </Button>
        )}
      </div>
      {creating && <NewAgentForm onDone={() => setCreating(false)} />}
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {shown.map((a) => (
          <AgentCard key={a.id} agent={a} />
        ))}
      </ul>
      {agents.data && shown.length === 0 && !creating && (
        <p className="rounded-lg border border-dashed p-8 text-center text-sm text-muted-foreground">{t("empty")}</p>
      )}
    </div>
  );
}

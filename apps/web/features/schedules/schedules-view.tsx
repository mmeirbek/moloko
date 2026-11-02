"use client";

import type { AgentOut, ScheduleOut } from "@moloko/shared-types";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useNow, useTimeZone, useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";

import { Pencil, Play, Plus, Trash2 } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useConfirm } from "@/components/ui/confirm";
import { StatusBadge } from "@/features/agents/status-badge";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { EmptyState } from "@/features/mascot/empty-state";
import { ErrorState, LoadingState } from "@/features/system/query-state";
import { agentKeys, listAgents, taskKeys } from "@/lib/api/agents";
import { deleteSchedule, listSchedules, runScheduleNow, scheduleKeys, updateSchedule } from "@/lib/api/schedules";
import { useRealtimeStore } from "@/lib/realtime/store";
import { cn } from "@/lib/utils";

import { describeRecurrence, formatWhen, type ScheduleT } from "./recurrence";
import { ScheduleForm } from "./schedule-form";

const REASONS = new Set([
  "agent_busy",
  "engine_stopped",
  "budget_exceeded",
  "agent_archived",
  "start_failed",
  "invalid_timezone",
] as const);
type Reason = typeof REASONS extends Set<infer T> ? T : never;

function reasonText(t: ScheduleT, code: string | null): string {
  if (code && REASONS.has(code as Reason)) return t(`reasons.${code as Reason}`);
  return t("reasons.other", { code: code ?? "?" });
}

/** On/off, the pixel way: a sunken track with a square knob. */
function EnabledSwitch({
  on,
  label,
  disabled,
  onChange,
}: {
  on: boolean;
  label: string;
  disabled?: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!on)}
      className={cn(
        "relative inline-flex h-6 w-11 shrink-0 items-center px-1 pixel-frame pixel-sunken outline-none focus-visible:[--frame-color:var(--color-ring)] disabled:opacity-50",
        on ? "bg-grass/30" : "bg-muted",
      )}
    >
      <span
        aria-hidden
        className={cn("size-4 transition-transform", on ? "translate-x-4 bg-grass" : "translate-x-0 bg-muted-foreground")}
      />
    </button>
  );
}

function ScheduleCard({
  schedule: s,
  agents,
  now,
  onEdit,
}: {
  schedule: ScheduleOut;
  agents: AgentOut[];
  now: Date;
  onEdit: () => void;
}) {
  const t = useTranslations("schedules");
  const locale = useLocale();
  const zone = useTimeZone() ?? "UTC";
  const toMessage = useErrorMessage();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const liveStatus = useRealtimeStore((st) => (s.last_task_id ? st.tasks[s.last_task_id]?.status : undefined));
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: scheduleKeys.all });
  };

  const toggle = useMutation({ mutationFn: (enabled: boolean) => updateSchedule(s.id, { enabled }), onSuccess: refresh });
  const runNow = useMutation({
    mutationFn: () => runScheduleNow(s.id),
    onSuccess: () => {
      refresh();
      void queryClient.invalidateQueries({ queryKey: taskKeys.all });
    },
  });
  const remove = useMutation({ mutationFn: () => deleteSchedule(s.id), onSuccess: refresh });
  const error = toggle.error ?? runNow.error ?? remove.error;

  async function askDelete() {
    const yes = await confirm({
      title: t("deleteConfirm", { title: s.title }),
      description: t("deleteHint"),
      confirmLabel: t("delete"),
      destructive: true,
    });
    if (yes) remove.mutate();
  }

  const fmt = (iso: string) => formatWhen(new Date(iso), now, zone, locale, t);
  const rule = describeRecurrence(s.recurrence, locale, t, { now, timeZone: zone });
  const agentName =
    s.target === "orchestrator"
      ? t("orchestrator")
      : (agents.find((a) => a.id === s.agent_id)?.name ?? t("unknownAgent"));
  const taskStatus = liveStatus ?? s.last_task_status;

  let state: { text: string; tone: string };
  if (s.busy_since) state = { text: t("waiting"), tone: "text-amber-700 dark:text-amber-300" };
  else if (s.enabled && s.next_run_at) state = { text: t("next", { when: fmt(s.next_run_at) }), tone: "" };
  else if (s.recurrence.kind === "once" && s.last_outcome === "started") state = { text: t("done"), tone: "text-grass" };
  else state = { text: t("off"), tone: "text-muted-foreground" };

  return (
    <li id={`schedule-${s.id}`} className="scroll-mt-20">
      <Card className="flex flex-col gap-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 flex-col gap-0.5">
            <p className="text-sm font-semibold break-words">{s.title}</p>
            <p className="text-sm text-muted-foreground">{rule}</p>
          </div>
          <EnabledSwitch
            on={s.enabled}
            label={t("toggle", { title: s.title })}
            disabled={toggle.isPending}
            onChange={(on) => toggle.mutate(on)}
          />
        </div>
        <div className="flex flex-col gap-1">
          <p className={cn("text-sm", state.tone)}>{state.text}</p>
          <p className="text-xs text-muted-foreground">{t("doneBy", { name: agentName })}</p>
          {s.last_run_at && (
            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span>{t("last", { when: fmt(s.last_run_at) })}</span>
              {s.last_outcome === "started" && s.last_task_id && (
                <>
                  <Link href={`/tasks/${s.last_task_id}`} className="underline">
                    {t("lastTask")}
                  </Link>
                  {taskStatus && <StatusBadge status={taskStatus} />}
                </>
              )}
              {s.last_outcome === "skipped" && <span>{t("skipped", { reason: reasonText(t, s.last_reason) })}</span>}
              {s.last_outcome === "failed" && (
                <span className="text-destructive">{t("failed", { reason: reasonText(t, s.last_reason) })}</span>
              )}
            </p>
          )}
        </div>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {toMessage(error).message}
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" onClick={() => runNow.mutate()} disabled={runNow.isPending}>
            <Play /> {t("runNow")}
          </Button>
          <Button size="sm" variant="outline" onClick={onEdit}>
            <Pencil /> {t("edit")}
          </Button>
          <Button size="sm" variant="ghost" onClick={askDelete} disabled={remove.isPending}>
            <Trash2 /> {t("delete")}
          </Button>
          {runNow.data && (
            <span role="status" className="text-sm">
              {t("started")}{" "}
              <Link href={`/tasks/${runNow.data.task.id}`} className="underline">
                {t("openTask")}
              </Link>
            </span>
          )}
        </div>
      </Card>
    </li>
  );
}

export function SchedulesView() {
  const t = useTranslations("schedules");
  const now = useNow({ updateInterval: 60_000 }); // "today / tomorrow" stays true
  const list = useQuery({ queryKey: scheduleKeys.all, queryFn: ({ signal }) => listSchedules(signal) });
  const agents = useQuery({ queryKey: agentKeys.all, queryFn: ({ signal }) => listAgents(signal) });
  const [editing, setEditing] = useState<string | null>(null); // "new" or a schedule id

  if (list.isError && !list.data) return <ErrorState error={list.error} onRetry={() => list.refetch()} />;
  if (!list.data) return <LoadingState />;
  const { items, max_schedules: max, min_interval_minutes: minInterval } = list.data;
  const full = items.length >= max;
  const agentList = agents.data ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">{full ? t("limit", { max }) : null}</p>
        {editing !== "new" && (
          <Button onClick={() => setEditing("new")} disabled={full}>
            <Plus /> {t("new")}
          </Button>
        )}
      </div>
      {editing === "new" && (
        <ScheduleForm schedule={null} agents={agentList} minIntervalMinutes={minInterval} onDone={() => setEditing(null)} />
      )}
      {items.length === 0 && editing !== "new" ? (
        <Card>
          <EmptyState
            title={t("empty")}
            hint={t("emptyHint")}
            mood="sleep"
            action={
              <Button onClick={() => setEditing("new")}>
                <Plus /> {t("new")}
              </Button>
            }
          />
        </Card>
      ) : (
        <ul aria-label={t("listLabel")} className="flex flex-col gap-3">
          {items.map((s) =>
            editing === s.id ? (
              <li key={s.id} id={`schedule-${s.id}`}>
                <ScheduleForm
                  schedule={s}
                  agents={agentList}
                  minIntervalMinutes={minInterval}
                  onDone={() => setEditing(null)}
                />
              </li>
            ) : (
              <ScheduleCard key={s.id} schedule={s} agents={agentList} now={now} onEdit={() => setEditing(s.id)} />
            ),
          )}
        </ul>
      )}
    </div>
  );
}

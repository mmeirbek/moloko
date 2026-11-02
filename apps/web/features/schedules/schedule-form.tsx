"use client";

import type { AgentOut, RecurrenceIn, ScheduleOut } from "@moloko/shared-types";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocale, useNow, useTimeZone, useTranslations } from "next-intl";
import { useId, useMemo, useState, type FormEvent } from "react";

import { CalendarDays } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { createSchedule, previewSchedule, scheduleKeys, updateSchedule } from "@/lib/api/schedules";
import { useDebounced } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { HOUR_STEPS, KINDS, WEEKDAYS, localParts, previewText, type Kind } from "./recurrence";

const ORCHESTRATOR = "orchestrator";
const FIELD = "h-10 bg-background px-2 text-sm pixel-frame pixel-sunken";

interface Draft {
  title: string;
  description: string;
  /** "orchestrator" or a persistent agent's id. */
  target: string;
  kind: Kind;
  time: string;
  date: string;
  weekdays: number[];
  dayOfMonth: number;
  intervalHours: number;
}

function addDays(day: string, n: number): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

function draftOf(s: ScheduleOut | null, now: Date, timeZone: string, minHours: number): Draft {
  const today = localParts(now, timeZone).day;
  const base: Draft = {
    title: "",
    description: "",
    target: ORCHESTRATOR,
    kind: "daily",
    time: "08:00",
    date: addDays(today, 1),
    weekdays: [1, 2, 3, 4, 5],
    dayOfMonth: 1,
    intervalHours: HOUR_STEPS.find((h) => h >= Math.max(minHours, 4)) ?? 12,
  };
  if (!s) return base;
  const r = s.recurrence;
  const once = r.kind === "once" && r.run_at ? localParts(new Date(r.run_at), s.timezone) : null;
  return {
    ...base,
    title: s.title,
    description: s.description,
    target: s.target === "agent" && s.agent_id ? s.agent_id : ORCHESTRATOR,
    kind: r.kind,
    time: once?.time ?? r.time ?? base.time,
    date: once?.day ?? base.date,
    weekdays: r.weekdays.length ? r.weekdays : base.weekdays,
    dayOfMonth: r.day_of_month ?? base.dayOfMonth,
    intervalHours: r.interval_hours ?? base.intervalHours,
  };
}

function recurrenceOf(d: Draft): RecurrenceIn {
  switch (d.kind) {
    case "once":
      // A local date-time without an offset: the server reads it in the schedule's zone.
      return { kind: "once", run_at: `${d.date}T${d.time}:00` };
    case "hourly":
      return { kind: "hourly", interval_hours: d.intervalHours, time: d.time };
    case "daily":
      return { kind: "daily", time: d.time };
    case "weekly":
      return { kind: "weekly", weekdays: [...d.weekdays].sort((a, b) => a - b), time: d.time };
    case "monthly":
      return { kind: "monthly", day_of_month: d.dayOfMonth, time: d.time };
  }
}

/** A row of toggle buttons (one or many pressed). */
function Toggles<T extends string | number>({
  label,
  options,
  pressed,
  onToggle,
  render,
}: {
  label: string;
  options: readonly T[];
  pressed: (value: T) => boolean;
  onToggle: (value: T) => void;
  render: (value: T) => string;
}) {
  return (
    <div role="group" aria-label={label} className="flex flex-wrap gap-1">
      {options.map((value) => (
        <button
          key={value}
          type="button"
          aria-pressed={pressed(value)}
          onClick={() => onToggle(value)}
          className={cn(
            "min-h-9 shrink-0 px-3 text-sm whitespace-nowrap",
            pressed(value) ? "bg-primary text-primary-foreground" : "text-muted-foreground hover:bg-accent",
          )}
        >
          {render(value)}
        </button>
      ))}
    </div>
  );
}

export function ScheduleForm({
  schedule,
  agents,
  minIntervalMinutes,
  onDone,
}: {
  /** null = a new schedule. */
  schedule: ScheduleOut | null;
  agents: AgentOut[];
  minIntervalMinutes: number;
  onDone: () => void;
}) {
  const t = useTranslations("schedules");
  const tf = useTranslations("schedules.form");
  const te = useTranslations("errors");
  const locale = useLocale();
  const ownerZone = useTimeZone() ?? "UTC";
  const now = useNow({ updateInterval: 60_000 });
  const toMessage = useErrorMessage();
  const queryClient = useQueryClient();
  const id = useId();
  const minHours = Math.ceil(minIntervalMinutes / 60);
  // A schedule keeps the zone it was made in; a new one gets the owner's.
  const zone = schedule?.timezone ?? ownerZone;
  const [draft, setDraft] = useState<Draft>(() => draftOf(schedule, now, zone, minHours));
  const set = (patch: Partial<Draft>) => setDraft((d) => ({ ...d, ...patch }));

  const recurrence = useMemo(() => recurrenceOf(draft), [draft]);
  const previewBody = useDebounced(useMemo(() => ({ recurrence, timezone: zone }), [recurrence, zone]));
  const preview = useQuery({
    queryKey: scheduleKeys.preview(previewBody),
    queryFn: ({ signal }) => previewSchedule(previewBody, signal),
    retry: false,
    placeholderData: keepPreviousData,
  });
  const nextRun = preview.data?.next_runs[0] ? new Date(preview.data.next_runs[0]) : null;
  const previewLine = previewText(
    {
      kind: draft.kind,
      time: draft.time,
      weekdays: draft.weekdays,
      day_of_month: draft.dayOfMonth,
      interval_hours: draft.intervalHours,
      run_at: draft.kind === "once" ? (nextRun?.toISOString() ?? null) : null,
    },
    nextRun,
    locale,
    t,
    { now, timeZone: ownerZone },
  );

  const save = useMutation({
    mutationFn: () => {
      const common = {
        title: draft.title.trim(),
        description: draft.description,
        target: draft.target === ORCHESTRATOR ? ("orchestrator" as const) : ("agent" as const),
        agent_id: draft.target === ORCHESTRATOR ? null : draft.target,
        recurrence,
        timezone: zone,
      };
      return schedule ? updateSchedule(schedule.id, common) : createSchedule(common);
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: scheduleKeys.all });
      onDone();
    },
  });

  const persistent = agents.filter((a) => a.agent_type === "autonomous" && !a.archived_at);
  const steps = HOUR_STEPS.filter((h) => h >= minHours);
  const weekdayError = draft.kind === "weekly" && draft.weekdays.length === 0;
  const canSave = Boolean(draft.title.trim()) && !weekdayError && !save.isPending;
  const previewError = weekdayError
    ? te("invalid_recurrence")
    : preview.isError
      ? toMessage(preview.error).message
      : null;

  function submit(e: FormEvent) {
    e.preventDefault();
    if (canSave) save.mutate();
  }

  return (
    <form onSubmit={submit} className="flex flex-col gap-4 bg-card p-4 pixel-frame" aria-labelledby={`${id}-h`}>
      <h2 id={`${id}-h`} className="font-pixel text-lg">
        {schedule ? tf("titleEdit") : tf("titleNew")}
      </h2>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-title`}>{tf("title")}</Label>
        <Input
          id={`${id}-title`}
          value={draft.title}
          maxLength={200}
          placeholder={tf("titlePlaceholder")}
          onChange={(e) => set({ title: e.target.value })}
          autoFocus
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-description`}>{tf("description")}</Label>
        <textarea
          id={`${id}-description`}
          rows={3}
          value={draft.description}
          maxLength={50_000}
          placeholder={tf("descriptionPlaceholder")}
          onChange={(e) => set({ description: e.target.value })}
          className="bg-background px-3 py-2 text-sm placeholder:text-muted-foreground pixel-frame pixel-sunken"
        />
      </div>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${id}-target`}>{tf("target")}</Label>
        <select
          id={`${id}-target`}
          value={draft.target}
          onChange={(e) => set({ target: e.target.value })}
          className={FIELD}
        >
          <option value={ORCHESTRATOR}>{tf("targetOrchestrator")}</option>
          {persistent.map((a) => (
            <option key={a.id} value={a.id}>
              {a.name}
            </option>
          ))}
        </select>
      </div>

      <fieldset className="flex flex-col gap-3">
        <legend className="mb-1.5 text-sm">{tf("repeat")}</legend>
        <Toggles
          label={tf("repeat")}
          options={KINDS}
          pressed={(k) => draft.kind === k}
          onToggle={(k) => set({ kind: k })}
          render={(k) => tf(`kinds.${k}`)}
        />
        {draft.kind === "weekly" && (
          <div className="flex flex-col gap-1.5">
            <span className="text-sm">{tf("days")}</span>
            <Toggles
              label={tf("days")}
              options={WEEKDAYS}
              pressed={(d) => draft.weekdays.includes(d)}
              onToggle={(d) =>
                set({
                  weekdays: draft.weekdays.includes(d) ? draft.weekdays.filter((x) => x !== d) : [...draft.weekdays, d],
                })
              }
              render={(d) => t(`dayShort.${d}`)}
            />
            <div className="flex flex-wrap gap-1">
              {(
                [
                  ["presetWorkdays", [1, 2, 3, 4, 5]],
                  ["presetWeekend", [6, 7]],
                  ["presetAll", [1, 2, 3, 4, 5, 6, 7]],
                ] as const
              ).map(([key, days]) => (
                <Button key={key} type="button" size="sm" variant="ghost" onClick={() => set({ weekdays: [...days] })}>
                  {tf(key)}
                </Button>
              ))}
            </div>
          </div>
        )}
        <div className="flex flex-wrap items-end gap-3">
          {draft.kind === "once" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-date`}>{tf("date")}</Label>
              <Input
                id={`${id}-date`}
                type="date"
                required
                value={draft.date}
                onChange={(e) => set({ date: e.target.value })}
                className="w-44"
              />
            </div>
          )}
          {draft.kind === "hourly" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-every`}>{tf("every")}</Label>
              <select
                id={`${id}-every`}
                value={draft.intervalHours}
                onChange={(e) => set({ intervalHours: Number(e.target.value) })}
                className={FIELD}
              >
                {steps.map((h) => (
                  <option key={h} value={h}>
                    {tf("hours", { n: h })}
                  </option>
                ))}
              </select>
            </div>
          )}
          {draft.kind === "monthly" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor={`${id}-day`}>{tf("dayOfMonth")}</Label>
              <select
                id={`${id}-day`}
                value={draft.dayOfMonth}
                onChange={(e) => set({ dayOfMonth: Number(e.target.value) })}
                className={FIELD}
              >
                {Array.from({ length: 31 }, (_, i) => i + 1).map((d) => (
                  <option key={d} value={d}>
                    {d}
                  </option>
                ))}
              </select>
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor={`${id}-time`}>{draft.kind === "hourly" ? tf("startingAt") : tf("time")}</Label>
            <Input
              id={`${id}-time`}
              type="time"
              step={60}
              required
              value={draft.time}
              onChange={(e) => set({ time: e.target.value })}
              className="w-32"
            />
          </div>
        </div>
        {draft.kind === "monthly" && draft.dayOfMonth > 28 && (
          <p className="text-xs text-muted-foreground">{tf("shortMonthHint")}</p>
        )}
        {zone !== ownerZone && <p className="text-xs text-muted-foreground">{tf("zone", { zone })}</p>}
      </fieldset>

      <p
        role="status"
        aria-live="polite"
        className={cn("flex items-start gap-2 bg-muted/60 px-3 py-2 text-sm", previewError && "text-destructive")}
      >
        <CalendarDays className="shrink-0" aria-hidden />
        <span>{previewError ?? (preview.isPending ? tf("previewLoading") : previewLine)}</span>
      </p>

      {save.error && (
        <p role="alert" className="text-sm text-destructive">
          {toMessage(save.error).message}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={!canSave}>
          {schedule ? tf("save") : tf("create")}
        </Button>
        <Button type="button" variant="ghost" onClick={onDone}>
          {tf("cancel")}
        </Button>
      </div>
    </form>
  );
}

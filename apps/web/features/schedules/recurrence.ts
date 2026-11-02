import type { RecurrenceOut } from "@moloko/shared-types";
import type { useTranslations } from "next-intl";

/** The translator of the "schedules" messages (from useTranslations or createTranslator). */
export type ScheduleT = ReturnType<typeof useTranslations<"schedules">>;

export type Kind = RecurrenceOut["kind"];
export const KINDS: Kind[] = ["daily", "weekly", "monthly", "hourly", "once"];
/** "Every N hours": N divides 24, so the times are the same every day (as the server requires). */
export const HOUR_STEPS = [1, 2, 3, 4, 6, 8, 12] as const;
/** ISO weekdays: 1 = Monday … 7 = Sunday (as the API). */
export const WEEKDAYS = [1, 2, 3, 4, 5, 6, 7] as const;
type Weekday = (typeof WEEKDAYS)[number];
const WORKDAYS = "1,2,3,4,5";
const WEEKEND = "6,7";

/** A moment on the wall clock of `timeZone`: day "YYYY-MM-DD", time "HH:MM", year. */
export function localParts(date: Date, timeZone: string) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return { day: `${get("year")}-${get("month")}-${get("day")}`, time: `${get("hour")}:${get("minute")}`, year: get("year") };
}

function addDay(day: string): string {
  const d = new Date(`${day}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 1);
  return d.toISOString().slice(0, 10);
}

/** "today at 08:00", "tomorrow at 08:00" or "Mon, 9 November at 08:00", in `timeZone`. */
export function formatWhen(date: Date, now: Date, timeZone: string, locale: string, t: ScheduleT): string {
  const at = localParts(date, timeZone);
  const today = localParts(now, timeZone);
  if (at.day === today.day) return t("when.today", { time: at.time });
  if (at.day === addDay(today.day)) return t("when.tomorrow", { time: at.time });
  const label = new Intl.DateTimeFormat(locale, {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "long",
    ...(at.year !== today.year ? { year: "numeric" } : {}),
  }).format(date);
  return t("when.date", { date: label, time: at.time });
}

function sameDays(days: readonly number[], list: string): boolean {
  return [...new Set(days)].sort((a, b) => a - b).join(",") === list;
}

/** The rule in words: "Каждый будний день в 08:00", "По понедельникам и средам в 09:00"… */
export function describeRecurrence(
  r: Pick<RecurrenceOut, "kind" | "time" | "weekdays" | "day_of_month" | "interval_hours" | "run_at">,
  locale: string,
  t: ScheduleT,
  opts: { now: Date; timeZone: string },
): string {
  const time = r.time ?? "00:00";
  switch (r.kind) {
    case "once":
      return r.run_at
        ? t("rule.once", { when: formatWhen(new Date(r.run_at), opts.now, opts.timeZone, locale, t) })
        : t("form.kinds.once");
    case "hourly":
      return t("rule.hourly", { n: r.interval_hours ?? 1, time });
    case "daily":
      return t("rule.daily", { time });
    case "monthly":
      return t("rule.monthly", { day: r.day_of_month ?? 1, time });
    case "weekly": {
      const days = [...new Set(r.weekdays)].filter((d): d is Weekday => d >= 1 && d <= 7).sort((a, b) => a - b);
      if (days.length === 7) return t("rule.daily", { time });
      if (sameDays(days, WORKDAYS)) return t("rule.workdays", { time });
      if (sameDays(days, WEEKEND)) return t("rule.weekend", { time });
      if (days.length === 1) return t("rule.oneDay", { day: t(`everyDay.${days[0]!}`), time });
      const list = new Intl.ListFormat(locale, { type: "conjunction" }).format(days.map((d) => t(`onDays.${d}`)));
      return t("rule.someDays", { days: list, time });
    }
  }
}

/** The form's live line: "Каждый будний день в 08:00 · следующий запуск завтра в 08:00". */
export function previewText(
  r: Parameters<typeof describeRecurrence>[0],
  next: Date | null,
  locale: string,
  t: ScheduleT,
  opts: { now: Date; timeZone: string },
): string {
  const rule = describeRecurrence(r, locale, t, opts);
  if (!next || r.kind === "once") return rule;
  return t("preview", { rule, when: formatWhen(next, opts.now, opts.timeZone, locale, t) });
}

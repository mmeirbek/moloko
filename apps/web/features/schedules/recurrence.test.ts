import { createTranslator } from "next-intl";
import { describe, expect, it } from "vitest";

import en from "@/messages/en.json";
import ru from "@/messages/ru.json";

import { describeRecurrence, formatWhen, previewText, type ScheduleT } from "./recurrence";

const tRu = createTranslator({ locale: "ru", messages: ru, namespace: "schedules" }) as unknown as ScheduleT;
const tEn = createTranslator({ locale: "en", messages: en, namespace: "schedules" }) as unknown as ScheduleT;

const ZONE = "Asia/Almaty"; // UTC+5, no DST
// Monday, 2 November 2026, 15:00 in Almaty
const NOW = new Date("2026-11-02T10:00:00Z");
const opts = { now: NOW, timeZone: ZONE };

function rule(r: Partial<Parameters<typeof describeRecurrence>[0]>): Parameters<typeof describeRecurrence>[0] {
  return { kind: "daily", time: "08:00", weekdays: [], day_of_month: null, interval_hours: null, run_at: null, ...r };
}

describe("schedule rule in words", () => {
  it.each([
    [rule({}), "Каждый день в 08:00", "Every day at 08:00"],
    [rule({ kind: "weekly", weekdays: [5, 1, 2, 3, 4] }), "Каждый будний день в 08:00", "Every weekday at 08:00"],
    [rule({ kind: "weekly", weekdays: [6, 7], time: "10:30" }), "По выходным в 10:30", "On weekends at 10:30"],
    [rule({ kind: "weekly", weekdays: [1, 2, 3, 4, 5, 6, 7] }), "Каждый день в 08:00", "Every day at 08:00"],
    [rule({ kind: "weekly", weekdays: [1], time: "09:00" }), "Каждый понедельник в 09:00", "Every Monday at 09:00"],
    [rule({ kind: "weekly", weekdays: [3] }), "Каждую среду в 08:00", "Every Wednesday at 08:00"],
    [
      rule({ kind: "weekly", weekdays: [5, 1, 3], time: "09:00" }),
      "По понедельникам, средам и пятницам в 09:00",
      "On Mondays, Wednesdays, and Fridays at 09:00",
    ],
    [rule({ kind: "monthly", day_of_month: 15, time: "09:00" }), "Каждый месяц 15-го числа в 09:00", "Every month on day 15 at 09:00"],
    [rule({ kind: "hourly", interval_hours: 1, time: "00:00" }), "Каждый час, начиная с 00:00", "Every hour, starting at 00:00"],
    [rule({ kind: "hourly", interval_hours: 3, time: "09:00" }), "Каждые 3 часа, начиная с 09:00", "Every 3 hours, starting at 09:00"],
    [rule({ kind: "hourly", interval_hours: 6, time: "09:00" }), "Каждые 6 часов, начиная с 09:00", "Every 6 hours, starting at 09:00"],
  ])("%j", (r, ruText, enText) => {
    expect(describeRecurrence(r, "ru", tRu, opts)).toBe(ruText);
    expect(describeRecurrence(r, "en", tEn, opts)).toBe(enText);
  });

  it("names a one-off by its moment", () => {
    const r = rule({ kind: "once", time: null, run_at: "2026-11-02T11:00:00Z" });
    expect(describeRecurrence(r, "ru", tRu, opts)).toBe("Один раз, сегодня в 16:00");
  });
});

describe("next run", () => {
  it("says today, tomorrow or the date, in the owner's time zone", () => {
    expect(formatWhen(new Date("2026-11-02T13:00:00Z"), NOW, ZONE, "ru", tRu)).toBe("сегодня в 18:00");
    expect(formatWhen(new Date("2026-11-03T03:00:00Z"), NOW, ZONE, "ru", tRu)).toBe("завтра в 08:00");
    expect(formatWhen(new Date("2026-11-03T03:00:00Z"), NOW, ZONE, "en", tEn)).toBe("tomorrow at 08:00");
    // 2026-11-02 21:00 UTC is already the 3rd in Almaty: "tomorrow", not "today"
    expect(formatWhen(new Date("2026-11-02T21:00:00Z"), NOW, ZONE, "ru", tRu)).toBe("завтра в 02:00");
    expect(formatWhen(new Date("2026-11-09T03:00:00Z"), NOW, ZONE, "ru", tRu)).toBe("пн, 9 ноября в 08:00");
    expect(formatWhen(new Date("2027-01-04T03:00:00Z"), NOW, ZONE, "en", tEn)).toBe("Mon, January 4, 2027 at 08:00");
  });

  it("builds the form's preview line", () => {
    const weekdays = rule({ kind: "weekly", weekdays: [1, 2, 3, 4, 5] });
    const next = new Date("2026-11-03T03:00:00Z");
    expect(previewText(weekdays, next, "ru", tRu, opts)).toBe(
      "Каждый будний день в 08:00 · следующий запуск завтра в 08:00",
    );
    expect(previewText(weekdays, next, "en", tEn, opts)).toBe("Every weekday at 08:00 · next run tomorrow at 08:00");
    // until the server answered: the rule alone
    expect(previewText(weekdays, null, "ru", tRu, opts)).toBe("Каждый будний день в 08:00");
    // a one-off already says when
    const once = rule({ kind: "once", time: null, run_at: next.toISOString() });
    expect(previewText(once, next, "ru", tRu, opts)).toBe("Один раз, завтра в 08:00");
  });
});

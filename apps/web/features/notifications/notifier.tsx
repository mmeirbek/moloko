"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { X } from "@/components/icons";
import { syncPush } from "@/lib/notifications/push";
import { loadPrefs, noticeFor, type Notice } from "@/lib/notifications/rules";
import { useRealtimeClient } from "@/lib/realtime/provider";
import { useRealtimeStore } from "@/lib/realtime/store";

type Toast = Notice & { text: string; heading: string };
type Translate = ReturnType<typeof useTranslations<"notifications">>;

/** Who, and what in plain words (never a raw command or path) — the same as the server's
 *  pushes (apps/api/app/push/dispatcher.py render). */
function noticeText(notice: Notice, name: string | undefined, t: Translate): { heading: string; text: string } {
  if (notice.kind === "approval") {
    const what = notice.op ? t(`ops.${notice.op.key}` as "ops.other", notice.op.params) : notice.subject;
    return { heading: name ? t("approval.titleNamed", { name }) : t("approval.title"), text: what };
  }
  if (notice.title === "taskQuestion") {
    return { heading: name ? t("taskQuestion.titleNamed", { name }) : t("taskQuestion.title"), text: notice.summary ?? "" };
  }
  if (notice.kind === "taskDone" || notice.kind === "taskFailed") {
    const heading = notice.subject ? t(`${notice.kind}.title`, { task: notice.subject }) : t(`${notice.kind}.titlePlain`);
    const detail = notice.summary ?? "";
    return { heading, text: name && detail ? `${name}: ${detail}` : name || detail };
  }
  return { heading: t("budget.title"), text: notice.subject };
}

/** Turns realtime events into in-app toasts and, when the app is in the background and
 *  the owner allowed it, system notifications (spec Sprint 8 "notifications"). */
export function Notifier() {
  const t = useTranslations("notifications");
  const client = useRealtimeClient();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seen = useRef(new Set<string>());
  const locale = useLocale();

  // Keep this device's Web Push subscription known to the server (browsers rotate them).
  useEffect(() => {
    void syncPush(loadPrefs(), locale).catch(() => undefined);
  }, [locale]);

  useEffect(() => {
    if (!client) return;
    return client.subscribe((event) => {
      const notice = noticeFor(event);
      if (!notice || seen.current.has(notice.key)) return;
      const prefs = loadPrefs();
      if (!prefs[notice.kind]) return;
      seen.current.add(notice.key);
      // Who, and what in plain words (never a raw command or path).
      const name = notice.agentName || (notice.agentId ? useRealtimeStore.getState().agents[notice.agentId]?.name : undefined);
      const { heading, text } = noticeText(notice, name, t);
      setToasts((list) => [...list.slice(-3), { ...notice, heading, text }]);
      window.setTimeout(() => setToasts((list) => list.filter((x) => x.key !== notice.key)), 10_000);
      if (
        prefs.system &&
        !prefs.push && // with Web Push the service worker shows it (no duplicates)
        typeof Notification !== "undefined" &&
        Notification.permission === "granted" &&
        document.visibilityState === "hidden"
      ) {
        const options = { body: text, tag: notice.tag ?? notice.key, icon: "/icons/icon-192.png", badge: "/icons/badge-96.png", data: { url: notice.url } };
        void navigator.serviceWorker?.ready
          .then((reg) => reg.showNotification(heading, options))
          .catch(() => new Notification(heading, options));
      }
    });
  }, [client, t]);

  // The live region is always mounted, so screen readers announce the first toast too.
  return (
    <div
      className="pointer-events-none fixed inset-x-4 bottom-[calc(6rem+env(safe-area-inset-bottom))] z-30 flex flex-col gap-2 md:inset-x-auto md:right-6 md:bottom-6 md:w-96"
      role="status"
      aria-live="polite"
    >
      {toasts.map((toast) => (
        <div
          key={toast.key}
          className="pointer-events-auto flex items-start gap-3 bg-card p-3 pixel-frame"
          data-toast={toast.kind}
        >
          <Link
            href={toast.url}
            className="min-w-0 flex-1"
            onClick={() => setToasts((l) => l.filter((x) => x.key !== toast.key))}
          >
            <p className="text-sm font-medium">{toast.heading}</p>
            <p className="truncate text-xs text-muted-foreground">{toast.text}</p>
          </Link>
          <button
            type="button"
            aria-label={t("dismiss")}
            className="-m-2 flex size-9 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
            onClick={() => setToasts((l) => l.filter((x) => x.key !== toast.key))}
          >
            <X className="size-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

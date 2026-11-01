"use client";

import { X } from "lucide-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { loadPrefs, noticeFor, type Notice } from "@/lib/notifications/rules";
import { useRealtimeClient } from "@/lib/realtime/provider";

type Toast = Notice & { text: string; heading: string };

/** Turns realtime events into in-app toasts and, when the app is in the background and
 *  the owner allowed it, system notifications (spec Sprint 8 "notifications"). */
export function Notifier() {
  const t = useTranslations("notifications");
  const client = useRealtimeClient();
  const [toasts, setToasts] = useState<Toast[]>([]);
  const seen = useRef(new Set<string>());

  useEffect(() => {
    if (!client) return;
    return client.subscribe((event) => {
      const notice = noticeFor(event);
      if (!notice || seen.current.has(notice.key)) return;
      const prefs = loadPrefs();
      if (!prefs[notice.kind]) return;
      seen.current.add(notice.key);
      const heading = t(`${notice.kind}.title`);
      const text = t(`${notice.kind}.body`, { subject: notice.subject });
      setToasts((list) => [...list.slice(-3), { ...notice, heading, text }]);
      window.setTimeout(() => setToasts((list) => list.filter((x) => x.key !== notice.key)), 10_000);
      if (
        prefs.system &&
        typeof Notification !== "undefined" &&
        Notification.permission === "granted" &&
        document.visibilityState === "hidden"
      ) {
        const options = { body: text, tag: notice.key, icon: "/icons/icon-192.png", data: { url: notice.url } };
        void navigator.serviceWorker?.ready
          .then((reg) => reg.showNotification(heading, options))
          .catch(() => new Notification(heading, options));
      }
    });
  }, [client, t]);

  if (toasts.length === 0) return null;
  return (
    <div
      className="fixed inset-x-4 bottom-24 z-30 flex flex-col gap-2 md:inset-x-auto md:right-6 md:bottom-6 md:w-96"
      role="status"
      aria-live="polite"
    >
      {toasts.map((toast) => (
        <div
          key={toast.key}
          className="flex items-start gap-3 rounded-lg border bg-card p-3 shadow-lg"
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
            className="text-muted-foreground hover:text-foreground"
            onClick={() => setToasts((l) => l.filter((x) => x.key !== toast.key))}
          >
            <X className="size-4" />
          </button>
        </div>
      ))}
    </div>
  );
}

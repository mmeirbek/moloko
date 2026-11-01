import { api } from "@/lib/api/client";

import type { NotificationKind, NotificationPrefs } from "./rules";

/** Web Push for this device (notifications while moloko is closed). */
export function pushSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    typeof Notification !== "undefined"
  );
}

/** iPhone/iPad: Web Push works only for the app added to the Home Screen. */
export function needsHomeScreen(): boolean {
  if (typeof window === "undefined") return false;
  const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
  const standalone =
    window.matchMedia?.("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true;
  return ios && !standalone;
}

export function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

export function kindsOf(prefs: NotificationPrefs): NotificationKind[] {
  return (["approval", "taskDone", "taskFailed"] as const).filter((k) => prefs[k]);
}

function deviceLabel(): string {
  const ua = navigator.userAgent;
  if (/iPhone|iPad/.test(ua)) return "iPhone/iPad";
  if (/Android/.test(ua)) return "Android";
  if (/Mac OS X/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows";
  return "Browser";
}

async function register(sub: PushSubscription, prefs: NotificationPrefs, locale: string) {
  const json = sub.toJSON() as { endpoint: string; keys: { p256dh: string; auth: string } };
  await api.request("/push/subscriptions", {
    method: "POST",
    body: { endpoint: json.endpoint, keys: json.keys, kinds: kindsOf(prefs), locale, label: deviceLabel() },
  });
}

export async function enablePush(prefs: NotificationPrefs, locale: string): Promise<void> {
  if ((await Notification.requestPermission()) !== "granted") throw new Error("permission");
  const reg = await navigator.serviceWorker.ready;
  const { public_key } = await api.request<{ public_key: string }>("/push/key");
  const sub =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    }));
  await register(sub, prefs, locale);
}

export async function disablePush(): Promise<void> {
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  await api
    .request(`/push/subscriptions?${new URLSearchParams({ endpoint: sub.endpoint })}`, { method: "DELETE" })
    .catch(() => undefined);
  await sub.unsubscribe();
}

/** On app start and when preferences change: the server knows this device's current
 *  subscription (browsers may rotate it) and which kinds it wants. */
export async function syncPush(prefs: NotificationPrefs, locale: string): Promise<void> {
  if (!pushSupported() || !prefs.push || Notification.permission !== "granted") return;
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (sub) await register(sub, prefs, locale);
  else await enablePush(prefs, locale);
}

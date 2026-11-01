/* moloko service worker (spec Sprint 8: PWA).
 * - App shell only: hashed static files are cached; pages are network-first with an
 *   offline fallback. API and WebSocket traffic is NEVER cached — the backend is the
 *   single source of truth, a stale copy of state must not be shown as current.
 * - Opens the right page when a notification is clicked.
 */
const VERSION = "moloko-v4"; // v4: icons from the owner's logo
const OFFLINE_URL = "/offline.html";
const PRECACHE = [OFFLINE_URL, "/icons/icon-192.png", "/icons/icon-512.png", "/icons/badge-96.png", "/icons/cow-sleep.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(VERSION)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return; // never cached

  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/")) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              void caches.open(VERSION).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
  }
});

// Web Push: show the notification unless the owner is looking at moloko right now.
self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { title: "moloko", body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      if (windows.some((w) => w.focused && w.visibilityState === "visible")) return undefined;
      return self.registration.showNotification(data.title || "moloko", {
        body: data.body || "",
        tag: data.tag,
        icon: "/icons/icon-192.png",
        badge: "/icons/badge-96.png",
        data: { url: data.url || "/" },
      });
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const win of windows) {
        if ("focus" in win) {
          void win.navigate(target);
          return win.focus();
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});

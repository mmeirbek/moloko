// Минимальный service worker: делает сайт устанавливаемым на телефон как приложение
// и открывает оболочку без сети. Данные (/api) никогда не кэшируются.
const CACHE = "office-v3";
const SHELL = ["/", "/style.css", "/app.js", "/sprites.js", "/manifest.webmanifest", "/icon.svg", "/icon-192.png", "/fonts/Handjet-cyrillic.woff2", "/fonts/Handjet-latin.woff2"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin || url.pathname.startsWith("/api/")) return;
  // Сначала сеть (чтобы всегда была свежая версия), кэш — только если сети нет.
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy));
        return res;
      })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("/"))),
  );
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  e.waitUntil(
    self.clients.matchAll({ type: "window" }).then((list) => (list[0] ? list[0].focus() : self.clients.openWindow("/"))),
  );
});

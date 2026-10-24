// StormHaven service worker: makes the app installable and lets the app SHELL open offline.   Owner: Nandan
// Registered only in production builds (main.jsx), so `npm run dev` never serves stale files.
// Rules:
//  - /api/* is NEVER cached: a stale risk number or restoration range is worse than an honest error.
//  - Page loads: network first, cached shell if offline (the app then shows its "can't reach the service" message).
//  - Built assets (hashed file names) and icons: cache first; a new build has new names, so nothing goes stale.
//  - Map tiles and other sites: not touched (third-party, large, and their own caching rules apply).
const CACHE = "stormhaven-v1";
const SHELL = ["/", "/manifest.webmanifest", "/favicon.svg", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  // Drop caches from older versions of this file.
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;

  if (req.mode === "navigate") {
    e.respondWith(fetch(req)
      .then((res) => { caches.open(CACHE).then((c) => c.put("/", res.clone())); return res; })
      .catch(() => caches.match("/")));
    return;
  }
  e.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
    if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
    return res;
  })));
});

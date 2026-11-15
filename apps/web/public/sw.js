const CACHE = "hutano-shell-v2";
const SHELL = ["/", "/status", "/offline.html", "/icon.svg", "/manifest.webmanifest"];
self.addEventListener("install", (event) => event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(SHELL))));
self.addEventListener("activate", (event) => event.waitUntil((async () => {
  const keys = await caches.keys();
  await Promise.all(keys.filter(key => key.startsWith("hutano-shell-") && key !== CACHE).map(key => caches.delete(key)));
  await self.clients.claim();
})()));
self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  const publicAsset = SHELL.includes(url.pathname) || url.pathname.startsWith("/_next/static/");
  if (!publicAsset && event.request.mode !== "navigate") return;
  event.respondWith((async () => {
    try {
      const response = await fetch(event.request);
      if (publicAsset && response.ok) {
        const cache = await caches.open(CACHE);
        await cache.put(event.request, response.clone());
      }
      return response;
    } catch (error) {
      const cached = publicAsset && await caches.match(event.request);
      if (cached) return cached;
      if (event.request.mode === "navigate") return await caches.match("/offline.html");
      throw error;
    }
  })());
});


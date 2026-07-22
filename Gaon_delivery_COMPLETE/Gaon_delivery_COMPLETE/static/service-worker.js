const CACHE = "gaon-delivery-v1";
const ASSETS = ["/", "/static/css/style.css", "/static/js/app.js"];
self.addEventListener("install", event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(ASSETS)));
});
self.addEventListener("fetch", event => {
  event.respondWith(fetch(event.request).catch(() => caches.match(event.request)));
});

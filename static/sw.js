// Network-first with cache fallback (v2)
var CACHE_NAME = 'claude-gateway-v25';
var STATIC_ASSETS = [
    '/static/index.html',
    '/static/style.css',
    '/static/app.js',
    '/static/manifest.json',
];

self.addEventListener('install', function (event) {
    // Skip waiting to activate immediately
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.addAll(STATIC_ASSETS);
        })
    );
});

self.addEventListener('activate', function (event) {
    // Delete old caches
    event.waitUntil(
        caches.keys().then(function (keys) {
            return Promise.all(
                keys.filter(function (k) { return k !== CACHE_NAME; })
                    .map(function (k) { return caches.delete(k); })
            );
        })
    );
});

self.addEventListener('fetch', function (event) {
    if (event.request.method !== 'GET') return;
    // Don't cache API calls, SSE streams, or file downloads — pass through directly
    var url = event.request.url;
    if (/\/api\//.test(url)) return;  // bypass SW: all API requests go direct
    event.respondWith(
        fetch(event.request).then(function (response) {
            // Network success — update cache, return fresh
            if (response.ok) {
                var clone = response.clone();
                caches.open(CACHE_NAME).then(function (cache) {
                    cache.put(event.request, clone);
                });
            }
            return response;
        }).catch(function () {
            // Network failed — fall back to cache
            return caches.match(event.request);
        })
    );
});

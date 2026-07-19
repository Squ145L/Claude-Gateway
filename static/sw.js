// Network-first with cache fallback (v3)
var CACHE_NAME = 'claude-gateway-v74';
var STATIC_ASSETS = [
    '/static/index.html',
    '/static/base.css',
    '/static/layout.css',
    '/static/controls.css',
    '/static/chat.css',
    '/static/overlay.css',
    '/static/scrollbar.css',
    '/static/manifest.json',
    '/static/js/app.js',
    '/static/js/core/store.js',
    '/static/js/core/events.js',
    '/static/js/core/dom.js',
    '/static/js/utils/html.js',
    '/static/js/utils/notify.js',
    '/static/js/services/api.js',
    '/static/js/services/stream.js',
    '/static/js/services/theme.js',
    '/static/js/render/markdown.js',
    '/static/js/render/thinking.js',
    '/static/js/render/agent.js',
    '/static/js/render/messages.js',
    '/static/js/components/settings-screen.js',
    '/static/js/components/settings-panel.js',
    '/static/js/components/chat.js',
    '/static/js/components/sidebar.js',
    '/static/js/components/compose.js',
    '/static/js/components/confirm.js',
    '/static/js/components/welcome.js',
];

self.addEventListener('install', function (event) {
    self.skipWaiting();
    event.waitUntil(
        caches.open(CACHE_NAME).then(function (cache) {
            return cache.addAll(STATIC_ASSETS);
        })
    );
});

self.addEventListener('activate', function (event) {
    // clients.claim() — take over all pages immediately
    event.waitUntil(
        Promise.all([
            clients.claim(),
            caches.keys().then(function (keys) {
                return Promise.all(
                    keys.filter(function (k) { return k !== CACHE_NAME; })
                        .map(function (k) { return caches.delete(k); })
                );
            })
        ])
    );
});

self.addEventListener('fetch', function (event) {
    if (event.request.method !== 'GET') return;
    var url = event.request.url;
    if (/\/api\//.test(url)) return;
    event.respondWith(
        fetch(event.request).then(function (response) {
            if (response.ok) {
                var clone = response.clone();
                caches.open(CACHE_NAME).then(function (cache) {
                    cache.put(event.request, clone);
                });
            }
            return response;
        }).catch(function () {
            return caches.match(event.request);
        })
    );
});

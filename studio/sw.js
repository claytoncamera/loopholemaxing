/* LoopholeMaxing Studio — service worker.
   Caches the app shell + self-hosted ffmpeg loader so Studio opens offline,
   and runtime-caches the big ffmpeg-core.wasm from the CDN so trimming works
   offline after the first export. Scope is /studio/ only. */
const CACHE = 'loop-studio-v3';
const SHELL = [
  './',
  './index.html',
  './manifest.webmanifest',
  './icon.svg',
  './vendor/ffmpeg.js',
  './vendor/814.ffmpeg.js',
  './vendor/ffmpeg-core.js',
  '../styles.css'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE).then(c => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys()
      .then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // The ~32MB ffmpeg core wasm (CDN): cache-first, fill on first fetch.
  if (url.hostname === 'unpkg.com') {
    e.respondWith(caches.open(CACHE).then(async c => {
      const hit = await c.match(req);
      if (hit) return hit;
      try { const res = await fetch(req); if (res && res.ok) c.put(req, res.clone()); return res; }
      catch (_) { return hit || Response.error(); }
    }));
    return;
  }

  if (url.origin !== location.origin) return;

  // HTML documents: NETWORK-FIRST so the app always updates when online;
  // fall back to cache (then index.html) when offline. Never serve a stale app.
  const isDoc = req.mode === 'navigate'
    || (req.headers.get('accept') || '').includes('text/html')
    || url.pathname.endsWith('/') || url.pathname.endsWith('index.html');
  if (isDoc) {
    e.respondWith(
      fetch(req).then(res => {
        if (res && res.ok) { const cl = res.clone(); caches.open(CACHE).then(c => c.put(req, cl)); }
        return res;
      }).catch(() => caches.match(req).then(h => h || caches.match('./index.html')))
    );
    return;
  }

  // Other same-origin static assets (css, vendor js, icon): cache-first, then network.
  e.respondWith(
    caches.match(req).then(hit => hit || fetch(req).then(res => {
      if (res && res.ok) { const cl = res.clone(); caches.open(CACHE).then(c => c.put(req, cl)); }
      return res;
    }).catch(() => hit))
  );
});

/**
 * SERVICE WORKER
 * Runs in the background. Handles caching and background scoring.
 * No data leaves the device from here.
 */

const CACHE_NAME = 'munich-markt-v1';
const ASSETS = [
  '/',
  '/index.html',
  '/scoring.js',
  '/manifest.json'
];

// Install: cache core assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: serve from cache first, fall back to network
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Never cache API calls
  if (url.pathname.startsWith('/api/')) {
    return;
  }

  event.respondWith(
    caches.match(event.request).then(cached => {
      return cached || fetch(event.request).then(response => {
        // Cache new static assets
        if (response.ok && event.request.method === 'GET') {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      });
    }).catch(() => {
      // Offline fallback
      if (event.request.destination === 'document') {
        return caches.match('/index.html');
      }
    })
  );
});

// Handle messages from main page
self.addEventListener('message', event => {
  if (event.data.type === 'SHOW_OFFER') {
    const offer = event.data.offer;
    self.registration.showNotification(offer.line2, {
      body: `${offer.line1} · ${offer.line3}`,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      tag: 'offer-' + offer.merchant.id,
      data: { merchant_id: offer.merchant.id },
      actions: [
        { action: 'accept', title: 'Show me' },
        { action: 'dismiss', title: 'Not now' }
      ],
      vibrate: [100, 50, 100],
      renotify: true
    });
  }
});

// Handle notification clicks
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const merchantId = event.notification.data?.merchant_id;

  if (event.action === 'accept' || !event.action) {
    // Open the wallet to the offer
    event.waitUntil(
      self.clients.matchAll({ type: 'window' }).then(clients => {
        const existing = clients.find(c => c.url.includes('/'));
        if (existing) {
          existing.postMessage({ type: 'SHOW_PASS', merchant_id: merchantId });
          return existing.focus();
        }
        return self.clients.openWindow('/?offer=' + merchantId);
      })
    );
  }
});

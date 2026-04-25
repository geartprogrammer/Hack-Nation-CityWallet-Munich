const CACHE = 'citywallet-v3';
const ASSETS = ['/', '/index.html', '/manifest.json', '/icon-192.png', '/icon-512.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k)))));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.url.includes('/api/')) return;
  e.respondWith(caches.match(e.request).then(r => r || fetch(e.request).then(resp => {
    if (resp.ok && e.request.method === 'GET') {
      const clone = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, clone));
    }
    return resp;
  }).catch(() => caches.match('/index.html'))));
});

// When user taps a notification → open the app and navigate to that offer
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const offerId = e.notification.data?.offerId;
  const action = e.action;

  if (action === 'dismiss') return;

  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      // If app is already open, focus it and send the offer ID
      for (const client of clients) {
        if (client.url.includes(self.registration.scope)) {
          client.postMessage({ type: 'OPEN_OFFER', offerId });
          return client.focus();
        }
      }
      // Otherwise open the app with the offer ID as a hash
      return self.clients.openWindow('/#offer=' + (offerId || ''));
    })
  );
});

// Listen for messages from the main page
self.addEventListener('message', e => {
  if (e.data?.type === 'SHOW_NOTIFICATION') {
    const d = e.data;
    self.registration.showNotification(d.title, {
      body: d.body,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      vibrate: [100, 50, 100, 50, 100],
      tag: 'offer-' + (d.offerId || 'new'),
      renotify: true,
      data: { offerId: d.offerId, merchantId: d.merchantId },
      actions: [
        { action: 'open', title: 'View deal' },
        { action: 'dismiss', title: 'Later' }
      ]
    });
  }
});

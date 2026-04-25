const CACHE='citywallet-v5';
const ASSETS=['/','index.html','/manifest.json','/icon-192.png','/icon-512.png'];

self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim()});
self.addEventListener('fetch',e=>{if(e.request.url.includes('/api/'))return;
  e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(resp=>{
    if(resp.ok&&e.request.method==='GET'){caches.open(CACHE).then(c=>c.put(e.request,resp.clone()))}return resp;
  }).catch(()=>caches.match('/index.html'))))});

// ═══ REAL PUSH from server (arrives even when app is closed) ═══
self.addEventListener('push', e => {
  let data = {title: 'City Wallet', body: 'New offer nearby', offerId: ''};
  try { data = e.data.json(); } catch(err) {}

  e.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      vibrate: [80, 40, 80],
      tag: 'cw-' + (data.offerId || Date.now()),
      renotify: true,
      data: { offerId: data.offerId, url: data.url || '/' },
      actions: [
        { action: 'open', title: 'View deal' },
        { action: 'dismiss', title: 'Later' }
      ]
    })
  );
});

// ═══ Notification click → open the deal ═══
self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'dismiss') return;

  const offerId = e.notification.data?.offerId || '';
  const targetUrl = '/#offer=' + offerId;

  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      for (const client of clients) {
        if (client.url.includes(self.registration.scope)) {
          client.postMessage({ type: 'OPEN_OFFER', offerId });
          return client.focus();
        }
      }
      return self.clients.openWindow(targetUrl);
    })
  );
});

// ═══ Local notification from main page ═══
self.addEventListener('message', e => {
  if (e.data?.type === 'SHOW_NOTIFICATION') {
    self.registration.showNotification(e.data.title, {
      body: e.data.body, icon: '/icon-192.png', badge: '/icon-192.png',
      vibrate: [80, 40, 80], tag: 'cw-' + (e.data.offerId || ''),
      renotify: true, data: { offerId: e.data.offerId },
      actions: [{ action: 'open', title: 'View deal' }, { action: 'dismiss', title: 'Later' }]
    });
  }
});

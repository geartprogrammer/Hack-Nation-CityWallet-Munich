const CACHE='citywallet-v8';
const ASSETS=['/','/index.html','/manifest.json','/icon-192.png','/icon-512.png'];

self.addEventListener('install',e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(ASSETS)));self.skipWaiting()});
self.addEventListener('activate',e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));self.clients.claim()});
self.addEventListener('fetch',e=>{if(e.request.url.includes('/api/'))return;
  e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(resp=>{
    if(resp.ok&&e.request.method==='GET'){caches.open(CACHE).then(c=>c.put(e.request,resp.clone()))}return resp;
  }).catch(()=>caches.match('/index.html'))))});

// Push from server — save data and show notification
self.addEventListener('push', e => {
  let data = {};
  try { data = e.data.json(); } catch(err) {}

  // Broadcast the fill data to all open windows so they can cache it
  self.clients.matchAll({type:'window'}).then(clients => {
    clients.forEach(client => client.postMessage({type:'FILL_DATA', data}));
  });

  e.waitUntil(
    self.registration.showNotification(data.title || 'City Wallet', {
      body: data.body || 'A deal appeared near you',
      icon: '/icon-192.png', badge: '/icon-192.png',
      vibrate: [80, 40, 80],
      tag: 'cw-' + (data.fillId || Date.now()),
      renotify: true,
      data: data, // Pass ALL data through
      actions: [{ action: 'open', title: 'View deal' }, { action: 'dismiss', title: 'Later' }]
    })
  );
});

// Notification tap → open app and pass the full data
self.addEventListener('notificationclick', e => {
  e.notification.close();
  if (e.action === 'dismiss') return;
  const data = e.notification.data || {};

  e.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(clients => {
      for (const client of clients) {
        if (client.url.includes(self.registration.scope)) {
          client.postMessage({ type: 'FILL_DATA', data });
          return client.focus();
        }
      }
      // App not open — open it with fill ID in hash
      return self.clients.openWindow('/#fill=' + (data.fillId || ''));
    })
  );
});

// Local notification request from main page
self.addEventListener('message', e => {
  if (e.data?.type === 'SHOW_NOTIFICATION') {
    self.registration.showNotification(e.data.title || 'City Wallet', {
      body: e.data.body || '', icon: '/icon-192.png', badge: '/icon-192.png',
      vibrate: [80, 40, 80], tag: 'cw-' + (e.data.fillId || Date.now()),
      renotify: true, data: e.data,
      actions: [{ action: 'open', title: 'View deal' }, { action: 'dismiss', title: 'Later' }]
    });
  }
});

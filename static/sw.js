/* ============================================================
   Service worker (served at /sw.js): shows push notifications for new
   notifications and chat messages, and opens the right page when one
   is tapped. It does no caching, so the site always loads fresh.
   ============================================================ */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('push', e => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (err) { d = {body: e.data ? e.data.text() : ''}; }
  const title = d.title || 'Social Platform';
  e.waitUntil(self.registration.showNotification(title, {
    body: d.body || '',
    icon: '/static/img/apple-touch-icon.png',
    badge: '/static/img/favicon-64.png',
    tag: d.tag || undefined,
    renotify: !!d.tag,                 // a newer message in the same chat still alerts
    data: {link: d.link || 'notifications', url: d.url || '/'},
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const {link, url} = e.notification.data || {};
  e.waitUntil((async () => {
    const wins = await self.clients.matchAll({type: 'window', includeUncontrolled: true});
    const here = wins.find(w => new URL(w.url).origin === self.location.origin);
    if (here) {                         // the site is open: bring it forward and go to the item
      try { await here.focus(); } catch (err) {}
      here.postMessage({type: 'push-open', link});
      return;
    }
    await self.clients.openWindow(url || '/');
  })());
});

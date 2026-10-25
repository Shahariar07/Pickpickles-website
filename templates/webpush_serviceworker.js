// Pickpickles PWA & Web Push Service Worker
self.addEventListener('install', function(event) {
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(self.clients.claim());
});

// Pass-through fetch event handler required for Android Chrome PWA install criteria
self.addEventListener('fetch', function(event) {
  return;
});

// Web Push event listener
self.addEventListener('push', function(event) {
  let data = {
    head: "🛒 New Pickpickles Order!",
    body: "A new order has been received.",
    icon: "/static/images/icon-192.png",
    url: "/dashboard/orders/"
  };

  if (event.data) {
    try {
      const parsed = JSON.parse(event.data.text());
      data = Object.assign(data, parsed);
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const notificationOptions = {
    body: data.body,
    icon: data.icon || "/static/images/icon-192.png",
    badge: "/static/images/favicon.png",
    vibrate: [200, 100, 200, 100, 200],
    tag: 'pickpickles-order-' + Date.now(),
    renotify: true,
    requireInteraction: true,
    data: {
      url: data.url || "/dashboard/orders/"
    }
  };

  event.waitUntil(
    self.registration.showNotification(data.head, notificationOptions)
  );
});

// Open order / dashboard on notification click
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  const targetUrl = (event.notification.data && event.notification.data.url) 
    ? event.notification.data.url 
    : '/dashboard/orders/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(clientList) {
      for (let i = 0; i < clientList.length; i++) {
        const client = clientList[i];
        if (client.url.indexOf(targetUrl) !== -1 && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});

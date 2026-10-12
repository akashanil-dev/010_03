// TallyTime service worker: shows "check finished" push notifications and opens the shipment when clicked.

self.addEventListener("push", (event) => {
  const data = event.data ? event.data.json() : {};
  event.waitUntil((async () => {
    const windows = await clients.matchAll({ type: "window", includeUncontrolled: true });
    // The open, focused page already shows its own message
    if (windows.some((w) => w.focused && w.visibilityState === "visible")) return;
    await self.registration.showNotification(data.title || "TallyTime", {
      body: data.body || "Your shipment check is finished.",
      tag: data.tag, icon: "/favicon.svg", data: { url: data.url || "/" },
    });
  })());
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url || "/", self.location.origin).href;
  event.waitUntil((async () => {
    const windows = await clients.matchAll({ type: "window", includeUncontrolled: true });
    const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
    if (open) { await open.navigate(url); return open.focus(); }
    return clients.openWindow(url);
  })());
});

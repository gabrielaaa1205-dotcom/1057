/*
 * Service Worker deliberadamente vacio de logica de cache. Su unico
 * proposito es cumplir el requisito tecnico de los navegadores para que la
 * app se pueda "Instalar" como programa (icono propio, ventana sin barra de
 * direcciones). NUNCA guarda ni sirve datos viejos -- cada peticion va
 * siempre a la red, para que varios trabajadores en distintas laptops sigan
 * viendo la informacion compartida en tiempo real, exactamente igual que en
 * el navegador comun.
 */
self.addEventListener("install", (event) => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});

self.addEventListener("fetch", (event) => {
  // Passthrough puro: no cache, no respuestas guardadas. Se declara el
  // listener solo porque su presencia es lo que activa la opcion "Instalar"
  // en Chrome/Edge de escritorio.
  event.respondWith(fetch(event.request));
});

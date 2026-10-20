/*
 * App-shell cache only.  Field authorisation, sessions and guest data must
 * never be cached by the browser HTTP cache or by this worker.  The encrypted
 * Encrypted shift packs and the queue live in IndexedDB under a non-exportable
 * Web Crypto device key; this worker still caches only the public app shell.
 */
const BASE = '/field/'
const CACHE_NAME = 'dawaa-field-shell-v3'
const APP_SHELL = [BASE, `${BASE}index.html`, `${BASE}manifest.webmanifest`, `${BASE}brand/dawaa-app-icon-navy.png`, `${BASE}brand/dawaa-app-icon-ivory.png`]

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)))
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
    )),
  )
  self.clients.claim()
})

self.addEventListener('fetch', (event) => {
  const request = event.request
  const url = new URL(request.url)

  // Never cache authenticated API responses, check-in results, or data from
  // another origin.  The browser will fetch them with their normal security
  // headers and with `cache: no-store` from the application client.
  if (request.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) {
    return
  }

  event.respondWith(
    fetch(request)
      .then((response) => {
        if (response.ok && request.destination !== 'document') {
          const copy = response.clone()
          void caches.open(CACHE_NAME).then((cache) => cache.put(request, copy))
        }
        return response
      })
      .catch(async () => {
        if (request.mode === 'navigate') return caches.match(`${BASE}index.html`)
        return (await caches.match(request)) || Response.error()
      }),
  )
})

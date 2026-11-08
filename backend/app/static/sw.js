/**
 * 智慧記帳本 Service Worker (PWA 支援與離線快取管理)
 * Version: 2.16.2
 */

const CACHE_NAME = 'account-book-v2.16.2';

const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/static/vendor/tailwindcss.js',
  '/static/vendor/lucide.min.js',
  '/static/vendor/vue.global.prod.js',
  '/static/vendor/chart.min.js',
  '/static/js/app.js?v=2.16.2',
  '/static/js/api.js?v=2.16.2',
  '/static/js/chart.js?v=2.12.5',
  '/static/js/formatters.js?v=2.12.5',
  '/static/js/insurance.js?v=2.12.5',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/courage_computer.png',
  '/static/icons/courage_empty_tx.jpg'
];

// 安裝階段：平行預載核心靜態資源（容錯保護：單一圖示或資源不阻塞其餘快取）
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await Promise.allSettled(
        PRECACHE_ASSETS.map((asset) => cache.add(asset).catch((err) => {
          console.warn('[SW] Precache asset partial warning:', asset, err);
        }))
      );
    }).then(() => self.skipWaiting())
  );
});

// 啟動階段：清除舊版快取並接管所有客戶端
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[SW] Clearing old cache:', name);
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 請求攔截策略
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 1. 後端 REST API 請求：優先走網路，確保財務數據與登入驗證的即時真實性
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => {
        return new Response(
          JSON.stringify({
            offline: true,
            detail: '目前處於離線狀態，請連接網路以同步最新財務資料'
          }),
          {
            status: 503,
            headers: { 'Content-Type': 'application/json' }
          }
        );
      })
    );
    return;
  }

  // 2. 頁面導航（Navigate HTML）：網路優先，離線時自動回退至快取的 App Shell
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((networkResp) => {
          if (networkResp && networkResp.status === 200) {
            const copy = networkResp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
          }
          return networkResp;
        })
        .catch(() => {
          return caches.match('/').then((cached) => cached || caches.match('/static/index.html'));
        })
    );
    return;
  }

  // 3. 靜態資源（CSS、JS、圖示、第三方庫）：Stale-While-Revalidate（快取優先且背景更新）
  event.respondWith(
    caches.match(req).then((cachedResp) => {
      const fetchPromise = fetch(req)
        .then((networkResp) => {
          if (networkResp && networkResp.status === 200 && req.method === 'GET') {
            const copy = networkResp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
          }
          return networkResp;
        })
        .catch(() => null);

      return cachedResp || fetchPromise;
    })
  );
});

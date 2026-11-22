/**
 * 智慧記帳本 Service Worker (網路優先同步 + 離線自動快取引擎)
 * Version: 3.0.2
 */

const CACHE_NAME = 'account-book-ios-v3.0.2';

const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/static/vendor/tailwindcss.js',
  '/static/vendor/lucide.min.js',
  '/static/vendor/vue.global.prod.js',
  '/static/vendor/chart.min.js',
  '/static/js/app.js?v=3.0.2',
  '/static/js/api.js?v=3.0.2',
  '/static/js/local-db.js?v=3.0.2',
  '/static/js/seed-snapshot.js?v=3.0.2',
  '/static/js/chart.js',
  '/static/js/formatters.js',
  '/static/js/insurance.js',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
  '/static/icons/courage_computer.png',
  '/static/icons/courage_empty_tx.jpg',
  '/static/icons/courage_cash.png',
  '/static/icons/courage_manual_tx.png',
  '/static/icons/courage_scan.png'
];

// 安裝階段：快顯預載並立即接管
self.addEventListener('install', (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await Promise.allSettled(
        PRECACHE_ASSETS.map((asset) =>
          fetch(asset, { headers: { 'ngrok-skip-browser-warning': '1' } })
            .then((resp) => {
              if (resp && resp.status === 200) {
                return cache.put(asset, resp);
              }
            })
            .catch(() => {})
        )
      );
    })
  );
});

// 啟動階段：徹底清除所有舊版快取並立即控制現有頁面
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            console.log('[SW] 刪除舊快取:', name);
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 網路連線超時輔助函式
function fetchWithTimeout(request, timeoutMs = 3500) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Network timeout')), timeoutMs);
    const reqHeaders = new Headers(request.headers);
    reqHeaders.set('ngrok-skip-browser-warning', '1');
    const newReq = new Request(request, { headers: reqHeaders });

    fetch(newReq)
      .then((res) => {
        clearTimeout(timer);
        resolve(res);
      })
      .catch((err) => {
        clearTimeout(timer);
        reject(err);
      });
  });
}

// 請求攔截策略：網路優先 (確保隨時同步最新刷卡)，離線自動回退快取
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 1. API 請求：直接走網路
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => {
        return new Response(
          JSON.stringify({
            offline: true,
            detail: '目前處於離線模式，已由手機本地資料庫接管'
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

  // 2. 頁面導航 (HTML / 首頁)：網路優先，超時或離線回退快取
  if (req.mode === 'navigate') {
    event.respondWith(
      fetchWithTimeout(req, 3000)
        .then((networkResp) => {
          if (networkResp && networkResp.status === 200) {
            const copy = networkResp.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
          }
          return networkResp;
        })
        .catch(() => {
          return caches.match('/', { ignoreSearch: true })
            .then((cached) => cached || caches.match('/static/index.html', { ignoreSearch: true }));
        })
    );
    return;
  }

  // 3. 靜態資源 (JS / CSS / 圖示)：網路優先以確保代碼更新即時生效，離線自動回退快取
  event.respondWith(
    fetchWithTimeout(req, 3000)
      .then((networkResp) => {
        if (networkResp && networkResp.status === 200 && req.method === 'GET') {
          const copy = networkResp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
        }
        return networkResp;
      })
      .catch(() => {
        return caches.match(req, { ignoreSearch: true });
      })
  );
});

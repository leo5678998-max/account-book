/**
 * 智慧記帳本 Service Worker (iOS Local-First 離線秒開與防 ngrok 攔截引擎)
 * Version: 3.0.0
 */

const CACHE_NAME = 'account-book-ios-v3.0.0';

const PRECACHE_ASSETS = [
  '/',
  '/manifest.json',
  '/static/vendor/tailwindcss.js',
  '/static/vendor/lucide.min.js',
  '/static/vendor/vue.global.prod.js',
  '/static/vendor/chart.min.js',
  '/static/js/app.js',
  '/static/js/api.js',
  '/static/js/local-db.js',
  '/static/js/seed-snapshot.js',
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

// 安裝階段：平行預載所有核心資源與本地資料庫種子
self.addEventListener('install', (event) => {
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
            .catch((err) => {
              console.warn('[SW] Precache partial warning:', asset, err);
            })
        )
      );
    }).then(() => self.skipWaiting())
  );
});

// 啟動階段：清除舊版快取並立即接管所有頁面
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames.map((name) => {
          if (name !== CACHE_NAME) {
            return caches.delete(name);
          }
        })
      );
    }).then(() => self.clients.claim())
  );
});

// 安全背景更新首頁 App Shell（嚴格過濾 ngrok 警告頁或錯誤頁，防止覆蓋正常快取）
async function revalidateAppShellInBackground() {
  try {
    const resp = await fetch('/', {
      headers: { 'ngrok-skip-browser-warning': '1' }
    });
    if (resp && resp.status === 200) {
      const text = await resp.clone().text();
      if (text.includes('英雄記帳') && !text.includes('ERR_NGROK')) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put('/', new Response(text, {
          status: 200,
          headers: { 'Content-Type': 'text/html; charset=utf-8' }
        }));
      }
    }
  } catch {
    // 離線狀態或電腦關機時靜默忽略
  }
}

// 請求攔截策略：iOS App Shell 快取優先 (0 延遲秒開、免除 ngrok 警告頁、支援離線 URL 捷徑記帳)
self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // 1. API 請求：若前端走網路模式，自動附帶 ngrok-skip-browser-warning
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req).catch(() => {
        return new Response(
          JSON.stringify({
            offline: true,
            detail: '目前處於離線模式，已自動由手機本地資料庫接管'
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

  // 2. 頁面導航 (Navigate HTML / iOS 捷徑喚醒 /?ios_shortcut=1...)：快取優先秒開！
  if (req.mode === 'navigate') {
    event.respondWith(
      caches.match('/', { ignoreSearch: true }).then((cachedShell) => {
        if (cachedShell) {
          // 背景靜默檢查更新，前景 0ms 直接返回快取的 App Shell
          event.waitUntil(revalidateAppShellInBackground());
          return cachedShell;
        }
        return fetch(req, { headers: { 'ngrok-skip-browser-warning': '1' } })
          .then((networkResp) => {
            if (networkResp && networkResp.status === 200) {
              const copy = networkResp.clone();
              caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
            }
            return networkResp;
          })
          .catch(() => caches.match('/static/index.html', { ignoreSearch: true }));
      })
    );
    return;
  }

  // 3. 靜態資源 (JS / CSS / 圖示 / Vendor)：忽略版號查詢參數快取優先 (Cache-First + Background Revalidate)
  event.respondWith(
    caches.match(req, { ignoreSearch: true }).then((cachedResp) => {
      const fetchPromise = fetch(req, { headers: { 'ngrok-skip-browser-warning': '1' } })
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

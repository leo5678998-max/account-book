/**
 * 後端 REST API 通訊封裝層 (Isolating HTTP, Auth Token & iOS Local-First Engine)
 */

import { localDb, handleLocalApiRequest, processIosShortcutUrlParams } from './local-db.js?v=3.0.3';

const TOKEN_KEY = 'account_book_auth_token';
const USER_KEY = 'account_book_auth_user';
const DEFAULT_LOCAL_TOKEN = 'ios-local-first-token';

let unauthorizedHandler = null;

export { localDb, processIosShortcutUrlParams };

export const AuthStorage = {
  getToken: () => {
    const stored = localStorage.getItem(TOKEN_KEY);
    if (stored) return stored;
    return DEFAULT_LOCAL_TOKEN;
  },
  setToken: (token) => {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  },
  getUser: () => {
    try {
      const raw = localStorage.getItem(USER_KEY);
      if (raw) return JSON.parse(raw);
      return { id: 1, username: 'admin', display_name: '預設管理者' };
    } catch {
      return { id: 1, username: 'admin', display_name: '預設管理者' };
    }
  },
  setUser: (user) => {
    if (user) localStorage.setItem(USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(USER_KEY);
  },
  clear: () => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  },
  onUnauthorized: (cb) => {
    unauthorizedHandler = cb;
  }
};

const authFetch = async (url, options = {}) => {
  const token = AuthStorage.getToken();
  const headers = {
    'ngrok-skip-browser-warning': '1',
    ...(options.headers || {})
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  // 優先連線伺服器，確保能即時獲取 Webhook 刷卡記帳最新明細
  try {
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 4000);
    const response = await fetch(url, { ...options, headers, signal: options.signal || controller.signal });
    clearTimeout(timeoutId);

    if (response.status === 401 && unauthorizedHandler && !localDb.isLocalFirstEnabled()) {
      unauthorizedHandler();
    }
    if (response.status === 503 || response.status === 502 || response.status === 504) {
      return handleLocalApiRequest(url, options);
    }
    // 防禦 ngrok 警告頁面：若 API 請求收到 HTML 回應，自動降級至本地快顯資料庫
    const contentType = response.headers.get('content-type') || '';
    if (contentType.includes('text/html') && url.startsWith('/api/')) {
      console.warn('[Offline Mode] 檢測到 API 被 ngrok 攔截為 HTML 頁面，自動由本地快顯資料庫接管:', url);
      return handleLocalApiRequest(url, options);
    }
    return response;
  } catch (err) {
    // 網路斷線、超時或電腦未開機時，無縫自動切換至手機本地快取資料庫
    console.warn('[Offline Mode] 伺服器連線離線，切換至本地資料庫:', url);
    return handleLocalApiRequest(url, options);
  }
};

const safeJson = async (respPromise, fallbackFn, defaultValue = []) => {
  try {
    const resp = await respPromise;
    if (!resp.ok) {
      if (fallbackFn) {
        const fbResp = await fallbackFn();
        return await fbResp.json();
      }
      return defaultValue;
    }
    const contentType = resp.headers.get('content-type') || '';
    if (contentType.includes('text/html')) {
      if (fallbackFn) {
        const fbResp = await fallbackFn();
        return await fbResp.json();
      }
      return defaultValue;
    }
    return await resp.json();
  } catch (err) {
    console.warn('[ApiService] JSON 解析異常，回退本地資料庫:', err);
    if (fallbackFn) {
      try {
        const fbResp = await fallbackFn();
        return await fbResp.json();
      } catch {}
    }
    return defaultValue;
  }
};

const jsonHeaders = { 'Content-Type': 'application/json' };

export const ApiService = {
  // iOS 本地優先資料庫模式與備份管理 API
  isLocalFirstMode: () => localDb.isLocalFirstEnabled(),
  setLocalFirstMode: (enabled) => localDb.setLocalFirstEnabled(enabled),
  getLocalSnapshot: () => localDb.getSnapshot(),
  importLocalSnapshot: (snapshot) => localDb.replaceSnapshot(snapshot),

  // 認證與帳號管理 API
  getAuthConfig: () =>
    authFetch('/api/auth/config').then(r => (r.ok ? r.json() : { allow_registration: false })).catch(() => ({ allow_registration: false })),
  login: (username, password) =>
    authFetch('/api/auth/login', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ username, password })
    }),
  register: (username, password, displayName = '') =>
    authFetch('/api/auth/register', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ username, password, display_name: displayName })
    }),
  getMe: () => authFetch('/api/auth/me'),
  updateProfile: (payload) =>
    authFetch('/api/auth/profile', {
      method: 'PUT',
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    }),

  // 帳戶 API
  getAccounts: () => safeJson(authFetch('/api/accounts'), () => handleLocalApiRequest('/api/accounts'), []),
  saveAccount: (acc) => {
    const method = acc.id ? 'PUT' : 'POST';
    const url = acc.id ? `/api/accounts/${acc.id}` : '/api/accounts';
    return authFetch(url, { method, headers: jsonHeaders, body: JSON.stringify(acc) });
  },
  deleteAccount: (id) => authFetch(`/api/accounts/${id}`, { method: 'DELETE' }),
  setDefaultDebit: (id) => authFetch(`/api/accounts/${id}`, {
    method: 'PUT',
    headers: jsonHeaders,
    body: JSON.stringify({ is_dbs_default_debit: true })
  }),

  // 交易流水帳與幣別匯率 API
  getExchangeRates: () => authFetch('/api/transactions/exchange-rates').then(r => (r.ok ? r.json() : null)),
  getTransactions: (limit = 1000) => safeJson(authFetch(`/api/transactions?limit=${limit}`), () => handleLocalApiRequest(`/api/transactions?limit=${limit}`), []),
  createTransaction: (tx) => authFetch('/api/transactions', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(tx)
  }),
  updateTransaction: (txId, tx) => authFetch(`/api/transactions/${txId}`, {
    method: 'PUT',
    headers: jsonHeaders,
    body: JSON.stringify(tx)
  }),
  deleteTransaction: (txId) => authFetch(`/api/transactions/${txId}`, { method: 'DELETE' }),

  // 自訂常用分類 API
  getCategories: () => authFetch('/api/categories').then(r => (r.ok ? r.json() : { categories: [] })),
  saveCategories: (categories) => authFetch('/api/categories', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ categories })
  }).then(r => (r.ok ? r.json() : null)),
  resetCategories: () => authFetch('/api/categories/reset', { method: 'POST' }).then(r => (r.ok ? r.json() : null)),

  // 自訂分類色彩 API
  getCategoryColors: () => authFetch('/api/category-colors').then(r => (r.ok ? r.json() : { colors: {} })),
  saveCategoryColors: (colors) => authFetch('/api/category-colors', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ colors })
  }).then(r => (r.ok ? r.json() : null)),
  resetCategoryColors: () => authFetch('/api/category-colors/reset', { method: 'POST' }).then(r => (r.ok ? r.json() : null)),

  // 信用卡帳單 API
  getBills: () => safeJson(authFetch('/api/bills'), () => handleLocalApiRequest('/api/bills'), []),
  saveBill: (bill) => {
    const isEdit = !!bill.id;
    const url = isEdit ? `/api/bills/${bill.id}` : '/api/bills';
    const method = isEdit ? 'PUT' : 'POST';
    return authFetch(url, { method, headers: jsonHeaders, body: JSON.stringify(bill) });
  },
  deleteBill: (billId) => authFetch(`/api/bills/${billId}`, { method: 'DELETE' }),
  payBillNow: (billId) => authFetch(`/api/bills/${billId}/pay`, { method: 'POST' }),

  // 信用卡分期付款 API
  getInstallments: (status = '') => {
    const qs = status ? `?status=${encodeURIComponent(status)}` : '';
    return authFetch(`/api/installments${qs}`).then(r => (r.ok ? r.json() : []));
  },
  getInstallmentSummary: (forecastMonths = 12) =>
    authFetch(`/api/installments/summary?forecast_months=${encodeURIComponent(forecastMonths)}`).then(r => (r.ok ? r.json() : null)),
  getInstallmentDetail: (planId) =>
    authFetch(`/api/installments/${planId}`).then(r => (r.ok ? r.json() : null)),
  saveInstallment: (plan) => {
    const isEdit = !!plan.id;
    const url = isEdit ? `/api/installments/${plan.id}` : '/api/installments';
    const method = isEdit ? 'PUT' : 'POST';
    return authFetch(url, { method, headers: jsonHeaders, body: JSON.stringify(plan) }).then(r => r.json());
  },
  deleteInstallment: (planId, deleteTransactions = false) => {
    const qs = deleteTransactions ? '?delete_transactions=true' : '';
    return authFetch(`/api/installments/${planId}${qs}`, { method: 'DELETE' }).then(r => r.json());
  },
  chargeNextInstallmentPeriod: (planId, period = null) => {
    const qs = period ? `?period=${encodeURIComponent(period)}` : '';
    return authFetch(`/api/installments/${planId}/charge-next${qs}`, { method: 'POST' }).then(r => r.json());
  },
  settleInstallmentInFull: (planId, accountId = null) => {
    const qs = accountId ? `?account_id=${encodeURIComponent(accountId)}` : '';
    return authFetch(`/api/installments/${planId}/settle-in-full${qs}`, { method: 'POST' }).then(r => r.json());
  },

  // 月底帳單對帳核銷 API
  getBillReconciliation: (billId, params = {}) => {
    const q = new URLSearchParams();
    if (params.credit_account_id) q.set('credit_account_id', params.credit_account_id);
    if (params.start_date) q.set('start_date', params.start_date);
    if (params.end_date) q.set('end_date', params.end_date);
    if (params.include_all) q.set('include_all', 'true');
    const qs = q.toString() ? `?${q.toString()}` : '';
    return authFetch(`/api/bills/${billId}/reconciliation${qs}`).then(r => (r.ok ? r.json() : null));
  },
  checkBillTransactions: (billId, transactionIds, isReconciled = true) => authFetch(`/api/bills/${billId}/reconciliation/check`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify({ transaction_ids: transactionIds, is_reconciled: isReconciled })
  }).then(r => r.json()),
  quickAddBillTx: (billId, data) => authFetch(`/api/bills/${billId}/reconciliation/quick-add`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(data)
  }).then(r => r.json()),
  settleAndClearBill: (billId, data) => authFetch(`/api/bills/${billId}/reconciliation/settle`, {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(data)
  }).then(r => r.json()),

  // AI 單據辨識與同步 API
  parseDocument: (formData) => authFetch('/api/ai/parse-document', { method: 'POST', body: formData }),
  applySalary: (payload) => authFetch('/api/salary/apply', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }),
  batchSave: (payload) => authFetch('/api/ai/batch-save', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }).then(r => r.json()),
  syncGmail: async () => {
    const res = await authFetch('/api/sync/gmail', { method: 'POST' });
    const text = await res.text();
    try {
      const data = JSON.parse(text);
      if (!res.ok) {
        throw new Error(data.detail || data.message || `連線錯誤 (${res.status})`);
      }
      return data;
    } catch (parseErr) {
      if (!res.ok) {
        throw new Error(`伺服器或閘道回應錯誤 (${res.status})`);
      }
      throw new Error('伺服器回應非預期格式');
    }
  },
  triggerAutoDebit: () => authFetch('/api/sync/auto-debit', { method: 'POST' }).then(r => r.json()),
  getMonthlyTrends: (months = 6) => authFetch(`/api/analytics/monthly-trends?months=${encodeURIComponent(months)}`).then(r => (r.ok ? r.json() : null)),

  // 股票投資組合 API
  getStocks: () => authFetch('/api/stocks'),
  saveStock: (stock) => {
    const method = stock.id ? 'PUT' : 'POST';
    const url = stock.id ? `/api/stocks/${stock.id}` : '/api/stocks';
    return authFetch(url, { method, headers: jsonHeaders, body: JSON.stringify(stock) });
  },
  deleteStock: (stockId) => authFetch(`/api/stocks/${stockId}`, { method: 'DELETE' }),
  refreshStockQuotes: () => authFetch('/api/stocks/refresh', { method: 'POST' }).then(r => r.json()),

  // 固定花費 API
  getRecurringExpenses: () => authFetch('/api/recurring-expenses'),
  saveRecurring: (item) => {
    const method = item.id ? 'PUT' : 'POST';
    const url = item.id ? `/api/recurring-expenses/${item.id}` : '/api/recurring-expenses';
    return authFetch(url, { method, headers: jsonHeaders, body: JSON.stringify(item) });
  },
  deleteRecurring: (id) => authFetch(`/api/recurring-expenses/${id}`, { method: 'DELETE' }),
  chargeRecurring: (id) => authFetch(`/api/recurring-expenses/${id}/charge`, { method: 'POST' }).then(r => r.json()),

  // 系統設定與 IMAP / OAuth API
  getSettings: () => authFetch('/api/settings').then(r => (r.ok ? r.json() : {})),
  saveSettings: (payload) => authFetch('/api/settings', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }),
  testImap: (payload) => authFetch('/api/settings/test-imap', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }),
  calculateInsurance: (salary, dependents, pensionRate = 0, taxRate = 0) =>
    authFetch(`/api/settings/calculate-insurance?salary=${encodeURIComponent(salary)}&dependents=${encodeURIComponent(dependents)}&pension_rate=${encodeURIComponent(pensionRate)}&tax_rate=${encodeURIComponent(taxRate)}`).then(r => r.json()),
  getGoogleAuthUrl: (redirectUri) =>
    authFetch(`/api/auth/google/url?redirect_uri=${encodeURIComponent(redirectUri)}`).then(r => r.json()),

  // Webhook (Apple Pay / iOS 捷徑自動化) API
  getWebhookToken: () => authFetch('/api/webhook/token').then(r => (r.ok ? r.json() : null)),
  regenerateWebhookToken: () => authFetch('/api/webhook/token/regenerate', { method: 'POST' }).then(r => (r.ok ? r.json() : null)),
  testWebhookTransaction: (payload) => authFetch('/api/webhook/apple-pay/test', {
    method: 'POST',
    headers: jsonHeaders,
    body: JSON.stringify(payload)
  }).then(r => r.json()),

  // AI 智慧財務顧問 API
  getAdvisorSnapshot: () => authFetch('/api/ai/advisor/snapshot').then(r => (r.ok ? r.json() : null)),
  askAdvisor: async (question, history = [], courageMode = false) => {
    const res = await authFetch('/api/ai/advisor/ask', {
      method: 'POST',
      headers: jsonHeaders,
      body: JSON.stringify({ question, history, courage_mode: courageMode })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || data.message || `連線錯誤 (${res.status})`);
    }
    return data;
  }
};

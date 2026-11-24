/**
 * iOS 本地優先資料庫引擎與離線 API 路由器 (Local-First Storage & Offline API Engine)
 * ------------------------------------------------------------------------------
 * 職責：
 * 1. 將所有帳務資料（帳戶、流水帳、固定開銷、股票、帳單、分期、設定）持久化儲存於手機本地 (localStorage)。
 * 2. 攔截並於手機本地 (< 0.5ms) 處理所有 /api/* 請求，徹底消除 ngrok 網路延遲、警告頁面與電腦開機依賴。
 * 3. 支援 iOS 捷徑「手機本地直連記帳」(URL Scheme / Deep Link Query Params)，刷卡後不需經過伺服器直接在手機內秒入帳。
 * 4. 支援與電腦後端雙向快照同步 (Sync) 以及 JSON 檔案匯出/匯入備份。
 */

import { INITIAL_SEED_SNAPSHOT } from './seed-snapshot.js?v=3.0.3';
import { calculateInsuranceSummary } from './insurance.js?v=2.9.0';

// ==============================================================================
// 領域常數定義 (Domain Constants) - 消除魔法字串與硬編碼
// ==============================================================================
export const STORAGE_KEY_LOCAL_DB = 'account_book_local_db_v1';
export const STORAGE_KEY_LOCAL_MODE = 'account_book_ios_local_mode';
export const STORAGE_KEY_PENDING_SYNC = 'account_book_pending_sync_txs';

export const TX_TYPE_EXPENSE = 'EXPENSE';
export const TX_TYPE_INCOME = 'INCOME';
export const TX_TYPE_TRANSFER = 'TRANSFER';
export const TX_TYPE_REFUND = 'REFUND';

export const FREQUENCY_MONTHLY = 'MONTHLY';
export const FREQUENCY_YEARLY = 'YEARLY';

export const BILL_STATUS_PENDING = 'PENDING';
export const BILL_STATUS_PAID = 'PAID';

export const INSTALLMENT_STATUS_ACTIVE = 'ACTIVE';
export const INSTALLMENT_STATUS_COMPLETED = 'COMPLETED';

export const CATEGORY_DEFAULT = '其他';
export const CATEGORY_SALARY = '薪資收入';
export const CATEGORY_CREDIT_CARD = '信用卡費';

export const DEFAULT_EXPENSE_CATEGORIES = [
  '飲食', '房租水電', '交通', '日常採買', '娛樂休閒', '保險醫療', '信用卡費', '薪資收入', '其他'
];

export const DEFAULT_CURRENCIES = [
  { code: 'TWD', name: '新台幣', symbol: 'NT$', rate_to_twd: 1.0, flag: '🇹🇼' },
  { code: 'USD', name: '美金', symbol: 'US$', rate_to_twd: 32.15, flag: '🇺🇸' },
  { code: 'JPY', name: '日圓', symbol: '¥', rate_to_twd: 0.211, flag: '🇯🇵' },
  { code: 'EUR', name: '歐元', symbol: '€', rate_to_twd: 34.2, flag: '🇪🇺' },
  { code: 'CNY', name: '人民幣', symbol: '¥', rate_to_twd: 4.45, flag: '🇨🇳' },
  { code: 'HKD', name: '港幣', symbol: 'HK$', rate_to_twd: 4.13, flag: '🇭🇰' },
  { code: 'KRW', name: '韓元', symbol: '₩', rate_to_twd: 0.0231, flag: '🇰🇷' },
  { code: 'GBP', name: '英鎊', symbol: '£', rate_to_twd: 40.8, flag: '🇬🇧' },
  { code: 'AUD', name: '澳幣', symbol: 'A$', rate_to_twd: 21.1, flag: '🇦🇺' },
  { code: 'SGD', name: '新幣', symbol: 'S$', rate_to_twd: 23.9, flag: '🇸🇬' },
  { code: 'THB', name: '泰銖', symbol: '฿', rate_to_twd: 0.93, flag: '🇹🇭' },
  { code: 'CAD', name: '加幣', symbol: 'C$', rate_to_twd: 23.1, flag: '🇨🇦' }
];

// 智能商家自動分類規則表
const MERCHANT_CATEGORY_RULES = [
  ['飲食', [
    '7-11', '7-eleven', '全家', 'familymart', '萊爾富', 'ok超商', '麥當勞', 'mcdonald',
    '肯德基', 'kfc', '摩斯', '星巴克', 'starbucks', '路易莎', 'louisa', 'lu yi sha', 'cama',
    'foodpanda', 'uber eats', 'ubereats', '餐廳', '食堂', '咖啡', 'coffee', 'cafe',
    '茶', '麵', '飯', '便當', '飲料', '手搖', '壽司', '火鍋', '牛排', '早餐', '宵夜',
    '清心', '麻古', '迷客夏', '50嵐', '五十嵐', '可不可', '得正', '爭鮮', '壽司郎',
    '藏壽司', '石二鍋', 'subway', '漢堡王', '拉麵', '甜點', '蛋糕', '披薩', 'pizza'
  ]],
  ['交通', [
    '高鐵', '台鐵', '捷運', '悠遊卡', '一卡通', 'icash', 'uber', 'yoxi', 'line go',
    '計程車', 'taxi', '中油', '台亞', '加油', '停車', '嘟嘟房', 'irent', 'goshare',
    'wemo', '車麻吉', 'etag', '航空', '機票', 'tpass'
  ]],
  ['日常採買', [
    '全聯', '家樂福', '好市多', 'costco', '大潤發', '屈臣氏', '康是美', '寶雅', 'poya',
    '蝦皮', 'shopee', 'momo', 'pchome', 'ikea', '無印良品', 'muji', 'uniqlo', 'net',
    'gu', 'zara', '超市', '生活百貨', '大創', 'daiso', '新光三越', 'sogo', '遠百', '誠品'
  ]],
  ['娛樂休閒', [
    '威秀', '國賓', '秀泰', 'show time', '電影', 'cinema', 'netflix', 'spotify',
    'youtube', 'disney', 'apple.com/bill', 'itunes', 'app store', 'google play',
    'steam', 'playstation', 'nintendo', 'klook', 'kkday', '飯店', '旅館', 'hotel',
    'ktv', '錢櫃', '好樂迪', '健身', 'world gym', 'gemini'
  ]],
  ['保險醫療', [
    '診所', '醫院', '藥局', '健保', '牙醫', '眼科', '耳鼻喉', '皮膚科', '保險',
    '富邦人壽', '國泰人壽', '南山人壽', '儲蓄險', '掛號'
  ]]
];

// ==============================================================================
// 純商業邏輯運算函式 (Pure Business Logic - Decoupled from Storage I/O)
// ==============================================================================
export function calculateBalanceDelta(txType, amount, reverse = false) {
  const numAmount = Number(amount) || 0;
  const multiplier = reverse ? -1 : 1;
  if (txType === TX_TYPE_EXPENSE || txType === TX_TYPE_TRANSFER) {
    return -numAmount * multiplier;
  }
  if (txType === TX_TYPE_INCOME) {
    return numAmount * multiplier;
  }
  if (txType === TX_TYPE_REFUND) {
    return Math.abs(numAmount) * multiplier;
  }
  return 0;
}

export function autoCategorizeMerchant(merchant) {
  if (!merchant || typeof merchant !== 'string') return CATEGORY_DEFAULT;
  const lower = merchant.toLowerCase().trim();
  for (const [category, keywords] of MERCHANT_CATEGORY_RULES) {
    for (const kw of keywords) {
      if (lower.includes(kw.toLowerCase())) {
        return category;
      }
    }
  }
  return CATEGORY_DEFAULT;
}

export function parseNotificationRawText(text = '', app = '', title = '') {
  const combined = `${app || ''} ${title || ''} ${text || ''}`.replace(/\u00a0/g, ' ').trim();
  if (!combined) return { amount: null, merchant: null, card_name: null, is_refund: false };

  let amount = null;
  const mAmt1 = combined.match(/(?:NT\$|NTD|TWD|USD|\$|新台幣)\s*([0-9,]+(?:\.[0-9]+)?)/i);
  const mAmt2 = !mAmt1 && combined.match(/([0-9,]+(?:\.[0-9]+)?)\s*(?:元|TWD|NTD)/i);
  const mAmt3 = !mAmt1 && !mAmt2 && combined.match(/(?:消費|扣款|付款|刷卡|金額|交易)[^\d\r\n]{0,8}([0-9,]+(?:\.[0-9]+)?)/);
  const matchAmt = mAmt1 || mAmt2 || mAmt3;
  if (matchAmt) {
    const val = parseFloat(matchAmt[1].replace(/,/g, ''));
    if (!isNaN(val) && val > 0) amount = val;
  }

  let merchant = null;
  let cleaned = String(text || combined)
    .replace(/(?:於|在)?\s*\d{1,4}[/-]\d{1,2}(?:[/-]\d{1,2})?/g, '')
    .replace(/(?:於|在)?\s*\d{1,2}月\d{1,2}日?/g, '')
    .replace(/(?:於|在)?\s*\d{1,2}:\d{2}(?::\d{2})?/g, '');

  const mMer1 = cleaned.match(/(?:商店名稱|特約商店|特店名稱|店家名稱|商店|特店|店家)[：:\s]+([^\r\n,，。!！]+)/);
  const mMer2 = !mMer1 && cleaned.match(/(?:在|於)\s*([^\r\n,，。!！]{2,30}?)\s*(?:消費|扣款|付款|刷卡|成功|交易)/);
  if (mMer1 || mMer2) {
    merchant = (mMer1 || mMer2)[1].trim().replace(/^(?:LINEPAY\*|LINEPAY_)/i, '');
  }
  if (!merchant) {
    const lowerText = combined.toLowerCase();
    for (const [, keywords] of MERCHANT_CATEGORY_RULES) {
      for (const kw of keywords) {
        if (kw.length >= 2 && lowerText.includes(kw.toLowerCase())) {
          merchant = kw;
          break;
        }
      }
      if (merchant) break;
    }
  }

  let cardName = null;
  const knownBanks = ['富邦', '台北富邦', '華南', '星展', '國泰', '中信', '中國信託', '台新', '玉山', '永豐', '聯邦', 'LINE Pay', '街口', '現金', '錢包'];
  for (const b of knownBanks) {
    if (combined.toLowerCase().includes(b.toLowerCase())) {
      cardName = b;
      break;
    }
  }

  const isRefund = ['退款', '退刷', '刷退', '沖正', '取消交易'].some(kw => combined.includes(kw));
  return { amount, merchant, card_name: cardName, is_refund: isRefund };
}

export function resolveTargetAccountFromList(accounts, cardName = '') {
  if (!Array.isArray(accounts) || accounts.length === 0) return null;
  if (cardName && typeof cardName === 'string') {
    const target = cardName.trim().toLowerCase();
    if (target) {
      const exact = accounts.find(a => (a.name || '').toLowerCase() === target);
      if (exact) return exact;
      const partial = accounts.find(a => {
        const al = (a.name || '').toLowerCase();
        return al && (target.includes(al) || al.includes(target));
      });
      if (partial) return partial;
    }
  }
  return accounts.find(a => a.is_dbs_default_debit) || accounts[0];
}

// ==============================================================================
// 本地資料庫狀態管理 (Local Database State Manager)
// ==============================================================================
function cloneDeep(obj) {
  return JSON.parse(JSON.stringify(obj));
}

class LocalDbManager {
  constructor() {
    this.db = null;
    this._init();
  }

  _init() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY_LOCAL_DB);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && Array.isArray(parsed.accounts) && Array.isArray(parsed.transactions)) {
          this.db = parsed;
          // 自動合併種子快照中新增的後端交易紀錄（例如透過舊版 Webhook 寫入之最新紀錄）
          const existingIds = new Set(this.db.transactions.map(t => Number(t.id)));
          let mergedCount = 0;
          for (const seedTx of (INITIAL_SEED_SNAPSHOT.transactions || [])) {
            if (!existingIds.has(Number(seedTx.id))) {
              this.db.transactions.push(cloneDeep(seedTx));
              mergedCount++;
            }
          }
          if (mergedCount > 0 || this.db.transactions.length === 0 || this.db.accounts.length === 0) {
            if (this.db.transactions.length === 0 && (INITIAL_SEED_SNAPSHOT.transactions || []).length > 0) {
              this.db.transactions = cloneDeep(INITIAL_SEED_SNAPSHOT.transactions);
            }
            if (this.db.accounts.length === 0 && (INITIAL_SEED_SNAPSHOT.accounts || []).length > 0) {
              this.db.accounts = cloneDeep(INITIAL_SEED_SNAPSHOT.accounts);
            }
            this._sortTransactions();
            this._save();
          }
          return;
        }
      }
    } catch (e) {
      console.warn('[LocalDB] 讀取本地資料庫快取異常，重新載入初始種子:', e);
    }
    this.db = cloneDeep(INITIAL_SEED_SNAPSHOT);
    this._save();
  }

  _save() {
    try {
      this.db.updated_at = new Date().toISOString();
      localStorage.setItem(STORAGE_KEY_LOCAL_DB, JSON.stringify(this.db));
    } catch (e) {
      console.error('[LocalDB] 儲存本地資料庫失敗:', e);
    }
  }

  isLocalFirstEnabled() {
    const val = localStorage.getItem(STORAGE_KEY_LOCAL_MODE);
    // 預設優先伺服器連線模式，確保 Webhook 刷卡即時同步
    return val === 'true';
  }

  setLocalFirstEnabled(enabled) {
    localStorage.setItem(STORAGE_KEY_LOCAL_MODE, enabled ? 'true' : 'false');
  }

  getSnapshot() {
    return cloneDeep(this.db);
  }

  replaceSnapshot(newSnapshot) {
    if (!newSnapshot || !Array.isArray(newSnapshot.accounts) || !Array.isArray(newSnapshot.transactions)) {
      throw new Error('無效的資料庫備份格式');
    }
    this.db = {
      ...cloneDeep(INITIAL_SEED_SNAPSHOT),
      ...cloneDeep(newSnapshot),
      updated_at: new Date().toISOString()
    };
    this._save();
    return this.db;
  }

  getCurrencyRate(code) {
    const c = (code || 'TWD').toUpperCase();
    if (c === 'TWD') return 1.0;
    const found = (this.db.currencies || DEFAULT_CURRENCIES).find(item => item.code === c);
    return found ? Number(found.rate_to_twd) : 1.0;
  }

  // ----------------------------------------------------------------------------
  // 交易記錄新增 / 修改 / 刪除 (含帳戶餘額聯動)
  // ----------------------------------------------------------------------------
  createTransaction(txIn) {
    const accounts = this.db.accounts || [];
    const currency = (txIn.currency || 'TWD').toUpperCase();
    const origAmt = txIn.original_amount !== undefined && txIn.original_amount !== null
      ? Number(txIn.original_amount)
      : Number(txIn.amount) || 0;
    const rate = currency === 'TWD'
      ? 1.0
      : (Number(txIn.exchange_rate) > 0 ? Number(txIn.exchange_rate) : this.getCurrencyRate(currency));
    const twdAmount = currency === 'TWD' ? (Number(txIn.amount) || origAmt) : Math.round(origAmt * rate * 100) / 100;

    const txType = txIn.tx_type || TX_TYPE_EXPENSE;
    const affectsBalance = txIn.affects_balance !== undefined ? Boolean(txIn.affects_balance) : true;
    const accountId = txIn.account_id ? Number(txIn.account_id) : (accounts[0]?.id || 1);
    const targetAccountId = txIn.target_account_id ? Number(txIn.target_account_id) : null;

    if (affectsBalance) {
      const sourceAcc = accounts.find(a => a.id === accountId);
      if (sourceAcc) {
        sourceAcc.balance = Math.round((Number(sourceAcc.balance || 0) + calculateBalanceDelta(txType, twdAmount, false)) * 100) / 100;
      }
      if (txType === TX_TYPE_TRANSFER && targetAccountId) {
        const targetAcc = accounts.find(a => a.id === targetAccountId);
        if (targetAcc) {
          targetAcc.balance = Math.round((Number(targetAcc.balance || 0) - calculateBalanceDelta(txType, twdAmount, false)) * 100) / 100;
        }
      }
    }

    const maxId = (this.db.transactions || []).reduce((max, t) => Math.max(max, Number(t.id) || 0), 0);
    const nowIso = new Date().toISOString();
    let dateStr = txIn.date || nowIso;
    if (dateStr.length === 10) {
      dateStr = `${dateStr}T00:00:00`;
    }

    const newTx = {
      id: maxId + 1,
      user_id: 1,
      date: dateStr,
      amount: twdAmount,
      tx_type: txType,
      account_id: accountId,
      target_account_id: targetAccountId,
      category: txIn.category || CATEGORY_DEFAULT,
      description: txIn.description || '',
      is_reconciled: Boolean(txIn.is_reconciled),
      affects_balance: affectsBalance,
      currency,
      original_amount: origAmt,
      exchange_rate: rate,
      created_at: nowIso
    };

    this.db.transactions.unshift(newTx);
    this._sortTransactions();
    this._save();
    return cloneDeep(newTx);
  }

  updateTransaction(txId, txIn) {
    const id = Number(txId);
    const idx = (this.db.transactions || []).findIndex(t => Number(t.id) === id);
    if (idx === -1) throw new Error('找不到該筆交易紀錄');

    const oldTx = this.db.transactions[idx];
    const accounts = this.db.accounts || [];

    // 1. 還原舊交易對餘額的影響
    if (oldTx.affects_balance !== false) {
      const oldSource = accounts.find(a => a.id === Number(oldTx.account_id));
      if (oldSource) {
        oldSource.balance = Math.round((Number(oldSource.balance || 0) + calculateBalanceDelta(oldTx.tx_type, oldTx.amount, true)) * 100) / 100;
      }
      if (oldTx.tx_type === TX_TYPE_TRANSFER && oldTx.target_account_id) {
        const oldTarget = accounts.find(a => a.id === Number(oldTx.target_account_id));
        if (oldTarget) {
          oldTarget.balance = Math.round((Number(oldTarget.balance || 0) - calculateBalanceDelta(oldTx.tx_type, oldTx.amount, true)) * 100) / 100;
        }
      }
    }

    // 2. 計算新交易金額與幣別
    const currency = (txIn.currency || oldTx.currency || 'TWD').toUpperCase();
    const origAmt = txIn.original_amount !== undefined && txIn.original_amount !== null
      ? Number(txIn.original_amount)
      : (txIn.amount !== undefined ? Number(txIn.amount) : Number(oldTx.original_amount || oldTx.amount));
    const rate = currency === 'TWD'
      ? 1.0
      : (Number(txIn.exchange_rate) > 0 ? Number(txIn.exchange_rate) : this.getCurrencyRate(currency));
    const twdAmount = currency === 'TWD'
      ? (txIn.amount !== undefined ? Number(txIn.amount) : origAmt)
      : Math.round(origAmt * rate * 100) / 100;

    const newType = txIn.tx_type || oldTx.tx_type;
    const newAccId = txIn.account_id !== undefined ? Number(txIn.account_id) : Number(oldTx.account_id);
    const newTargetId = txIn.target_account_id !== undefined
      ? (txIn.target_account_id ? Number(txIn.target_account_id) : null)
      : oldTx.target_account_id;
    const newAffects = txIn.affects_balance !== undefined ? Boolean(txIn.affects_balance) : (oldTx.affects_balance !== false);

    // 3. 套用新交易對餘額的影響
    if (newAffects) {
      const newSource = accounts.find(a => a.id === newAccId);
      if (newSource) {
        newSource.balance = Math.round((Number(newSource.balance || 0) + calculateBalanceDelta(newType, twdAmount, false)) * 100) / 100;
      }
      if (newType === TX_TYPE_TRANSFER && newTargetId) {
        const newTarget = accounts.find(a => a.id === newTargetId);
        if (newTarget) {
          newTarget.balance = Math.round((Number(newTarget.balance || 0) - calculateBalanceDelta(newType, twdAmount, false)) * 100) / 100;
        }
      }
    }

    let dateStr = txIn.date !== undefined ? txIn.date : oldTx.date;
    if (dateStr && dateStr.length === 10) {
      dateStr = `${dateStr}T00:00:00`;
    }

    const updated = {
      ...oldTx,
      date: dateStr,
      amount: twdAmount,
      tx_type: newType,
      account_id: newAccId,
      target_account_id: newTargetId,
      category: txIn.category !== undefined ? txIn.category : oldTx.category,
      description: txIn.description !== undefined ? txIn.description : oldTx.description,
      affects_balance: newAffects,
      currency,
      original_amount: origAmt,
      exchange_rate: rate
    };

    this.db.transactions[idx] = updated;
    this._sortTransactions();
    this._save();
    return cloneDeep(updated);
  }

  deleteTransaction(txId, rollbackBalance = true) {
    const id = Number(txId);
    const idx = (this.db.transactions || []).findIndex(t => Number(t.id) === id);
    if (idx === -1) return { status: 'success', message: '交易已刪除' };

    const oldTx = this.db.transactions[idx];
    if (rollbackBalance && oldTx.affects_balance !== false) {
      const accounts = this.db.accounts || [];
      const sourceAcc = accounts.find(a => a.id === Number(oldTx.account_id));
      if (sourceAcc) {
        sourceAcc.balance = Math.round((Number(sourceAcc.balance || 0) + calculateBalanceDelta(oldTx.tx_type, oldTx.amount, true)) * 100) / 100;
      }
      if (oldTx.tx_type === TX_TYPE_TRANSFER && oldTx.target_account_id) {
        const targetAcc = accounts.find(a => a.id === Number(oldTx.target_account_id));
        if (targetAcc) {
          targetAcc.balance = Math.round((Number(targetAcc.balance || 0) - calculateBalanceDelta(oldTx.tx_type, oldTx.amount, true)) * 100) / 100;
        }
      }
    }

    this.db.transactions.splice(idx, 1);
    this._save();
    return { status: 'success', message: '交易明細已刪除，帳戶餘額已同步還原' };
  }

  _sortTransactions() {
    this.db.transactions.sort((a, b) => {
      const da = String(a.date || '');
      const db = String(b.date || '');
      if (da !== db) return db.localeCompare(da);
      return (Number(b.id) || 0) - (Number(a.id) || 0);
    });
  }

  // ----------------------------------------------------------------------------
  // 固定開銷自動扣款巡檢與彙總 (Recurring Expenses)
  // ----------------------------------------------------------------------------
  executeAutoRecurringDebits() {
    const now = new Date();
    const currentMonthStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    const currentMonthInt = now.getMonth() + 1;
    const todayDay = now.getDate();

    let executedCount = 0;
    for (const item of (this.db.recurring_expenses || [])) {
      if (!item.is_active || !item.auto_debit || !item.account_id) continue;
      if (item.last_charged_month === currentMonthStr) continue;
      if (item.frequency === FREQUENCY_YEARLY && item.due_month && Number(item.due_month) !== currentMonthInt) {
        continue;
      }
      if (item.due_day && todayDay < Number(item.due_day)) {
        continue;
      }
      this._chargeSingleRecurringItem(item, currentMonthStr, true);
      executedCount++;
    }
    if (executedCount > 0) this._save();
    return executedCount;
  }

  _chargeSingleRecurringItem(item, currentMonthStr, isAuto = false) {
    const periodDesc = item.frequency === FREQUENCY_YEARLY ? '年繳' : '固定開銷';
    const modeLabel = isAuto ? '自動扣款' : '扣款';
    this.createTransaction({
      date: new Date().toISOString(),
      amount: Number(item.amount) || 0,
      tx_type: TX_TYPE_EXPENSE,
      account_id: item.account_id,
      category: item.category || CATEGORY_DEFAULT,
      description: `${periodDesc}${modeLabel}: ${item.name} (${currentMonthStr})`,
      affects_balance: true
    });
    item.last_charged_month = currentMonthStr;
    item.updated_at = new Date().toISOString();
    this._save();
  }

  getRecurringSummary() {
    this.executeAutoRecurringDebits();
    const now = new Date();
    const currentMonthInt = now.getMonth() + 1;
    let totalMonthlyAmortized = 0;
    let totalYearlyAmount = 0;
    let monthlyCount = 0;
    let yearlyCount = 0;

    const items = (this.db.recurring_expenses || []).map(item => {
      const freq = item.frequency || FREQUENCY_MONTHLY;
      const amt = Number(item.amount) || 0;
      const amortized = freq === FREQUENCY_YEARLY ? Math.round((amt / 12) * 100) / 100 : amt;
      const isDueThisMonth = freq === FREQUENCY_YEARLY
        ? (item.due_month ? Number(item.due_month) === currentMonthInt : false)
        : true;

      if (item.is_active !== false) {
        totalMonthlyAmortized += amortized;
        if (freq === FREQUENCY_YEARLY) {
          yearlyCount++;
          totalYearlyAmount += amt;
        } else {
          monthlyCount++;
        }
      }

      return {
        ...item,
        frequency: freq,
        auto_debit: Boolean(item.auto_debit),
        is_active: item.is_active !== false,
        monthly_amortized_amount: amortized,
        is_due_this_month: isDueThisMonth
      };
    });

    return {
      total_monthly_amount: Math.round(totalMonthlyAmortized * 100) / 100,
      total_yearly_amount: Math.round(totalYearlyAmount * 100) / 100,
      monthly_count: monthlyCount,
      yearly_count: yearlyCount,
      items
    };
  }

  // ----------------------------------------------------------------------------
  // 股票投資組合計算 (Stock Portfolio Summary)
  // ----------------------------------------------------------------------------
  getStockPortfolioSummary() {
    const usdRate = this.getCurrencyRate('USD');
    const rawHoldings = this.db.stock_holdings || [];
    let totalMvTwd = 0;
    let totalCostTwd = 0;

    const enriched = rawHoldings.map(h => {
      const shares = Number(h.shares) || 0;
      const costPrice = Number(h.cost_price) || 0;
      const currentPrice = Number(h.current_price) || costPrice;
      const currency = (h.currency || 'TWD').toUpperCase();
      const rate = currency === 'USD' ? usdRate : this.getCurrencyRate(currency);

      const mvOriginal = shares * currentPrice;
      const costOriginal = shares * costPrice;
      const mvTwd = mvOriginal * rate;
      const costTwd = costOriginal * rate;
      const pnlTwd = mvTwd - costTwd;
      const pnlPct = costTwd > 0 ? ((mvTwd - costTwd) / costTwd) * 100 : 0;

      totalMvTwd += mvTwd;
      totalCostTwd += costTwd;

      return {
        ...h,
        stock_name: h.name || h.symbol,
        shares,
        cost_price: costPrice,
        current_price: currentPrice,
        currency,
        market_value_twd: Math.round(mvTwd * 100) / 100,
        total_cost_twd: Math.round(costTwd * 100) / 100,
        unrealized_pnl_twd: Math.round(pnlTwd * 100) / 100,
        unrealized_pnl_percent: Math.round(pnlPct * 100) / 100,
        return_rate: Math.round(pnlPct * 100) / 100,
        weight_percent: 0
      };
    });

    for (const item of enriched) {
      item.weight_percent = totalMvTwd > 0
        ? Math.round((item.market_value_twd / totalMvTwd) * 1000) / 10
        : 0;
    }

    const totalPnl = totalMvTwd - totalCostTwd;
    const totalRet = totalCostTwd > 0 ? (totalPnl / totalCostTwd) * 100 : 0;

    return {
      total_market_value_twd: Math.round(totalMvTwd * 100) / 100,
      total_cost_twd: Math.round(totalCostTwd * 100) / 100,
      total_unrealized_pnl_twd: Math.round(totalPnl * 100) / 100,
      total_return_rate: Math.round(totalRet * 100) / 100,
      usd_to_twd_rate: usdRate,
      holdings: enriched
    };
  }

  // ----------------------------------------------------------------------------
  // 系統設定與勞健保預覽 (Settings Status)
  // ----------------------------------------------------------------------------
  getSettingsStatus() {
    const s = this.db.settings || {};
    const salary = Number(s.monthly_salary) || 75168;
    const deduct = Boolean(s.deduct_labor_health);
    const dependents = Number(s.health_insurance_dependents) || 0;
    const pensionRate = Number(s.pension_rate) || 0;
    const taxRate = Number(s.tax_rate) || 0;
    const autoCalc = s.labor_health_auto_calc !== false;

    let laborFee = Number(s.labor_insurance_fee) || 0;
    let healthFee = Number(s.health_insurance_fee) || 0;
    let pensionFee = Number(s.pension_fee) || 0;
    let taxFee = Number(s.tax_fee) || 0;

    if (autoCalc) {
      const calc = calculateInsuranceSummary(salary, dependents, pensionRate, taxRate);
      laborFee = calc.labor.fee;
      healthFee = calc.health.fee;
      pensionFee = calc.pension.fee;
      taxFee = calc.tax.fee;
    }

    const netSalary = deduct ? Math.max(0, salary - laborFee - healthFee - pensionFee - taxFee) : salary;
    const defaultAcc = (this.db.accounts || []).find(a => a.is_dbs_default_debit) || this.db.accounts?.[0];
    const salaryAcc = (this.db.accounts || []).find(a => a.id === Number(s.salary_account_id)) || defaultAcc;

    return {
      is_google_connected: false,
      is_imap_configured: false,
      has_pdf_password: false,
      google_client_id_configured: false,
      has_gemini_api_key: Boolean(s.gemini_api_key),
      default_debit_account_name: defaultAcc ? defaultAcc.name : null,
      auto_debit_bills: Boolean(s.auto_debit_bills),
      salary_account_id: salaryAcc ? salaryAcc.id : null,
      salary_account_name: salaryAcc ? salaryAcc.name : null,
      salary_pay_day: Number(s.salary_pay_day) || 5,
      auto_salary_income: Boolean(s.auto_salary_income),
      monthly_salary: salary,
      deduct_labor_health: deduct,
      health_insurance_dependents: dependents,
      labor_insurance_fee: laborFee,
      health_insurance_fee: healthFee,
      pension_rate: pensionRate,
      pension_fee: pensionFee,
      tax_rate: taxRate,
      tax_fee: taxFee,
      show_deductions_in_chart: s.show_deductions_in_chart !== false,
      labor_health_auto_calc: autoCalc,
      net_salary: netSalary,
      gemini_api_key: s.gemini_api_key || '',
      dbs_pdf_password: '',
      id_card_password: '',
      imap_email: s.imap_email || '',
      imap_app_password: '',
      imap_server: s.imap_server || 'imap.gmail.com',
      google_client_id: '',
      google_redirect_uri: '',
      webhook_token: 'ios-local-direct',
      webhook_url: '/?ios_shortcut=1&amount=100&merchant=消費商家&card=預設帳戶',
      bookkeeping_start_month: s.bookkeeping_start_month || '2026-11'
    };
  }

  // ----------------------------------------------------------------------------
  // 收支與存款趨勢分析 (Monthly Trends Analytics)
  // ----------------------------------------------------------------------------
  getMonthlyTrends(months = 6) {
    const validMonths = [6, 12, 24].includes(Number(months)) ? Number(months) : 6;
    const now = new Date();
    const monthKeys = [];
    for (let i = validMonths; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      monthKeys.push(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`);
    }

    const currentBalance = (this.db.accounts || []).reduce((sum, a) => sum + (Number(a.balance) || 0), 0);
    const s = this.getSettingsStatus();
    const startMonth = s.bookkeeping_start_month || '2026-11';
    const baseSalary = s.monthly_salary || 0;

    const monthlyStats = {};
    for (const m of monthKeys) {
      monthlyStats[m] = { income: 0, expense: 0, categories: {} };
    }

    const salaryKeywords = ['薪資收入', '固定月薪', '薪資', '薪水', 'salary'];
    const manualSalaryMonths = new Set();

    for (const tx of (this.db.transactions || [])) {
      if (!tx.date) continue;
      const mStr = tx.date.substring(0, 7);
      if (startMonth && mStr < startMonth) continue;
      if (!monthlyStats[mStr]) continue;

      const amt = Number(tx.amount) || 0;
      if (tx.tx_type === TX_TYPE_INCOME) {
        monthlyStats[mStr].income += amt;
        const cat = tx.category || '';
        const desc = (tx.description || '').toLowerCase();
        if (salaryKeywords.includes(cat) || salaryKeywords.some(k => desc.includes(k))) {
          manualSalaryMonths.add(mStr);
        }
      } else if (tx.tx_type === TX_TYPE_EXPENSE) {
        monthlyStats[mStr].expense += amt;
        const cat = tx.category || CATEGORY_DEFAULT;
        monthlyStats[mStr].categories[cat] = (monthlyStats[mStr].categories[cat] || 0) + amt;
      } else if (tx.tx_type === TX_TYPE_REFUND) {
        const refVal = -Math.abs(amt);
        monthlyStats[mStr].expense += refVal;
        const cat = tx.category || CATEGORY_DEFAULT;
        monthlyStats[mStr].categories[cat] = (monthlyStats[mStr].categories[cat] || 0) + refVal;
      }
    }

    const activeRecurring = (this.db.recurring_expenses || []).filter(r => r.is_active !== false);
    for (const m of monthKeys) {
      if (startMonth && m < startMonth) continue;
      if (!manualSalaryMonths.has(m) && baseSalary > 0) {
        monthlyStats[m].income += s.net_salary;
      }
      for (const item of activeRecurring) {
        const amt = item.frequency === FREQUENCY_YEARLY
          ? Math.round((Number(item.amount) / 12) * 100) / 100
          : (Number(item.amount) || 0);
        const alreadyCharged = (this.db.transactions || []).some(
          t => t.date && t.date.substring(0, 7) === m && (t.description || '').includes(item.name)
        );
        if (!alreadyCharged) {
          const cat = item.category || CATEGORY_DEFAULT;
          monthlyStats[m].expense += amt;
          monthlyStats[m].categories[cat] = (monthlyStats[m].categories[cat] || 0) + amt;
        }
      }
    }

    let targetMonths = monthKeys.slice(1).filter(m => !startMonth || m >= startMonth);
    if (targetMonths.length === 0 && monthKeys.length > 0) {
      targetMonths = [monthKeys[monthKeys.length - 1]];
    }

    const endBalances = {};
    let runningBalance = currentBalance;
    for (let i = targetMonths.length - 1; i >= 0; i--) {
      const m = targetMonths[i];
      endBalances[m] = runningBalance;
      const net = monthlyStats[m].income - monthlyStats[m].expense;
      runningBalance -= net;
    }

    const monthsData = targetMonths.map((m, idx) => {
      const stat = monthlyStats[m];
      const inc = Math.round(stat.income * 100) / 100;
      const exp = Math.round(stat.expense * 100) / 100;
      const net = Math.round((inc - exp) * 100) / 100;
      const savingsRate = inc > 0 ? Math.round((net / inc) * 1000) / 10 : 0;

      const prevM = monthKeys[monthKeys.indexOf(m) - 1] || '';
      const prevStat = monthlyStats[prevM] || { income: 0, expense: 0 };
      const prevExp = prevStat.expense || 0;
      const prevNet = (prevStat.income || 0) - prevExp;

      const expMomDiff = Math.round((exp - prevExp) * 100) / 100;
      const expMomPct = prevExp > 0 ? Math.round((expMomDiff / prevExp) * 1000) / 10 : 0;
      const netMomDiff = Math.round((net - prevNet) * 100) / 100;

      const topCats = Object.entries(stat.categories)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 3)
        .map(([category, amount]) => ({
          category,
          amount: Math.round(amount * 100) / 100,
          pct: exp > 0 ? Math.round((amount / exp) * 1000) / 10 : 0
        }));

      const parts = m.split('-');
      return {
        month: m,
        label: parts.length === 2 ? `${parseInt(parts[1], 10)}月` : m,
        full_label: parts.length === 2 ? `${parts[0]}年${parseInt(parts[1], 10)}月` : m,
        income: inc,
        expense: exp,
        net,
        savings_rate: savingsRate,
        end_balance: Math.round(endBalances[m] * 100) / 100,
        expense_mom_diff: expMomDiff,
        expense_mom_pct: expMomPct,
        net_mom_diff: netMomDiff,
        top_categories: topCats
      };
    });

    const cur = monthsData[monthsData.length - 1] || null;
    const totInc = monthsData.reduce((acc, d) => acc + d.income, 0);
    const totExp = monthsData.reduce((acc, d) => acc + d.expense, 0);
    const totNet = monthsData.reduce((acc, d) => acc + d.net, 0);
    const cnt = Math.max(1, monthsData.length);

    return {
      range_months: validMonths,
      current_balance: Math.round(currentBalance * 100) / 100,
      summary: {
        current_month: cur ? cur.month : '',
        current_month_expense: cur ? cur.expense : 0,
        current_month_income: cur ? cur.income : 0,
        current_month_net: cur ? cur.net : 0,
        current_month_savings_rate: cur ? cur.savings_rate : 0,
        expense_mom_diff: cur ? cur.expense_mom_diff : 0,
        expense_mom_pct: cur ? cur.expense_mom_pct : 0,
        net_mom_diff: cur ? cur.net_mom_diff : 0,
        total_period_income: Math.round(totInc * 100) / 100,
        total_period_expense: Math.round(totExp * 100) / 100,
        total_period_net: Math.round(totNet * 100) / 100,
        avg_monthly_expense: Math.round((totExp / cnt) * 100) / 100,
        avg_monthly_income: Math.round((totInc / cnt) * 100) / 100,
        start_balance: Math.round(runningBalance * 100) / 100,
        end_balance: Math.round(currentBalance * 100) / 100,
        period_growth_amount: Math.round(totNet * 100) / 100,
        period_growth_pct: runningBalance > 0 ? Math.round((totNet / runningBalance) * 1000) / 10 : 0
      },
      months_data: monthsData
    };
  }

  // ----------------------------------------------------------------------------
  // AI 財務顧問快照與本地智慧分析 (Advisor Snapshot & Local Advisor)
  // ----------------------------------------------------------------------------
  getAdvisorSnapshot() {
    const totalSavings = (this.db.accounts || []).reduce((sum, a) => sum + (Number(a.balance) || 0), 0);
    const s = this.getSettingsStatus();
    const portfolio = this.getStockPortfolioSummary();
    const rec = this.getRecurringSummary();
    const trends = this.getMonthlyTrends(6);
    const curMonth = trends.months_data[trends.months_data.length - 1];

    const avgExp = curMonth ? curMonth.expense : rec.total_monthly_amount;
    const avgInc = curMonth && curMonth.income > 0 ? curMonth.income : s.net_salary;
    const avgNet = Math.round((avgInc - avgExp) * 100) / 100;
    const netWorth = Math.round((totalSavings + portfolio.total_market_value_twd) * 100) / 100;
    const emergencyMonths = avgExp > 0 ? Math.round((totalSavings / avgExp) * 10) / 10 : 99.9;
    const savingsRate = avgInc > 0 ? Math.round((avgNet / avgInc) * 1000) / 10 : 0;

    return {
      as_of_date: new Date().toISOString().substring(0, 10),
      total_savings_twd: Math.round(totalSavings * 100) / 100,
      estimated_net_worth_twd: netWorth,
      base_monthly_salary_twd: s.monthly_salary,
      effective_monthly_salary_twd: s.net_salary,
      insurance_deduction_twd: s.monthly_salary - s.net_salary,
      avg_monthly_expense_twd: Math.round(avgExp * 100) / 100,
      avg_monthly_income_twd: Math.round(avgInc * 100) / 100,
      avg_monthly_net_savings_twd: avgNet,
      savings_rate_percent: savingsRate,
      emergency_fund_months: emergencyMonths,
      monthly_recurring_fixed_cost_twd: rec.total_monthly_amount,
      recurring_items: rec.items.map(r => ({ name: r.name, category: r.category, amount: r.amount })),
      pending_bill_amount_twd: 0,
      installments_summary: {
        active_plans_count: 0,
        total_remaining_unpaid_twd: 0,
        next_month_installment_amount_twd: 0
      },
      stocks_summary: {
        total_market_value_twd: portfolio.total_market_value_twd,
        total_cost_twd: portfolio.total_cost_twd,
        total_unrealized_pnl_twd: portfolio.total_unrealized_pnl_twd,
        total_return_rate: portfolio.total_return_rate,
        holdings_count: portfolio.holdings.length,
        holdings: portfolio.holdings
      },
      top_expense_categories: (curMonth?.top_categories || []).map(c => ({
        category: c.category,
        amount: c.amount,
        percentage: c.pct
      })),
      accounts_count: (this.db.accounts || []).length
    };
  }

  buildLocalAdvisorReply(question, courageMode = false) {
    const snap = this.getAdvisorSnapshot();
    const fmt = (n) => Number(n || 0).toLocaleString('zh-TW', { maximumFractionDigits: 0 });
    if (courageMode) {
      return {
        snapshot: snap,
        advice: `*(喀噠喀噠... 閣樓老電腦離線高速運算中)*\n\n**你這笨狗（You twit）！** 就算沒連上電腦伺服器，本電腦的本地晶片一樣能秒算你的身家：\n\n- **總存款現金**：NT$ ${fmt(snap.total_savings_twd)}\n- **股票投資市值**：NT$ ${fmt(snap.stocks_summary.total_market_value_twd)}（未實現損益 NT$ ${fmt(snap.stocks_summary.total_unrealized_pnl_twd)}，報酬率 ${snap.stocks_summary.total_return_rate}%）\n- **預估總淨值**：**NT$ ${fmt(snap.estimated_net_worth_twd)}**\n- **本月實領收入**：NT$ ${fmt(snap.effective_monthly_salary_twd)} ｜ **月均支出**：NT$ ${fmt(snap.avg_monthly_expense_twd)}\n- **儲蓄率**：**${snap.savings_rate_percent}%**（緊急預備金可撐 **${snap.emergency_fund_months} 個月**）\n\n針對你問的「${question}」：\n你的緊急預備金非常充裕，固定扣款（0050、VOO 等每月 NT$ ${fmt(snap.monthly_recurring_fixed_cost_twd)}）也在穩定累積資產。繼續保持紀律，別亂買奧斯提的怪東西！`
      };
    }
    return {
      snapshot: snap,
      advice: `### 📊 本地即時財務診斷報告 (iOS Local-First Engine)\n\n- **銀行存款總計**：NT$ ${fmt(snap.total_savings_twd)}\n- **股票投資組合市值**：NT$ ${fmt(snap.stocks_summary.total_market_value_twd)}（報酬率 ${snap.stocks_summary.total_return_rate}%）\n- **個人預估總淨資產**：**NT$ ${fmt(snap.estimated_net_worth_twd)}**\n- **每月自由結餘現金流**：NT$ ${fmt(snap.avg_monthly_net_savings_twd)}（儲蓄率 **${snap.savings_rate_percent}%**）\n- **緊急預備金倍數**：可支應 **${snap.emergency_fund_months} 個月** 開銷\n\n針對您的問題「**${question}**」：\n您目前的現金水位與儲蓄率表現優異，每月固定開銷與定期定額（NT$ ${fmt(snap.monthly_recurring_fixed_cost_twd)}）結構健康，可在維持 6 個月緊急預備金的前提下持續執行長期指數化投資。`
    };
  }
}

export const localDb = new LocalDbManager();

// ==============================================================================
// iOS 捷徑「手機本地直連記帳」URL 參數攔截器 (0 網路延遲、免伺服器)
// ==============================================================================
const SHORTCUT_DEDUP_KEY = 'account_book_last_ios_shortcut_sig';

export function processIosShortcutUrlParams(customUrlStr = null) {
  if (typeof window === 'undefined') return null;
  let searchStr = '';
  if (customUrlStr && typeof customUrlStr === 'string') {
    const qIdx = customUrlStr.indexOf('?');
    searchStr = qIdx !== -1 ? customUrlStr.substring(qIdx) : '';
  } else {
    searchStr = window.location.search || (window.location.hash.includes('?') ? window.location.hash.substring(window.location.hash.indexOf('?')) : '');
  }
  if (!searchStr) return null;

  const params = new URLSearchParams(searchStr);
  const isShortcut = params.get('ios_shortcut') === '1' || params.get('quick_add') === '1' || params.get('auto_tx') === '1';
  if (!isShortcut) return null;

  let rawAmount = params.get('amount');
  let merchant = params.get('merchant') || params.get('store') || params.get('description') || '';
  let cardName = params.get('card') || params.get('account') || params.get('payment') || '';
  let category = params.get('category') || '';
  const rawText = params.get('text') || params.get('msg') || '';
  const appName = params.get('app') || '';

  let isRefund = params.get('tx_type') === TX_TYPE_REFUND;

  if (rawText) {
    const parsed = parseNotificationRawText(rawText, appName, '');
    if (!rawAmount && parsed.amount) rawAmount = String(parsed.amount);
    if (!merchant && parsed.merchant) merchant = parsed.merchant;
    if (!cardName && parsed.card_name) cardName = parsed.card_name;
    if (parsed.is_refund) isRefund = true;
  }

  const cleanAmount = rawAmount ? parseFloat(String(rawAmount).replace(/[^0-9.-]/g, '')) : NaN;
  if (isNaN(cleanAmount) || cleanAmount <= 0) {
    // 清除參數避免卡住
    const cleanUrl = window.location.pathname + (window.location.hash.split('?')[0] || '');
    window.history.replaceState({}, document.title, cleanUrl);
    return null;
  }

  // 防重複觸發保護 (30 秒內相同金額+商家不重複入帳)
  const sig = `${cleanAmount}|${merchant}|${cardName}`;
  try {
    const lastRaw = sessionStorage.getItem(SHORTCUT_DEDUP_KEY);
    if (lastRaw) {
      const last = JSON.parse(lastRaw);
      if (last.sig === sig && Date.now() - last.ts < 30000) {
        const cleanUrl = window.location.pathname + (window.location.hash.split('?')[0] || '');
        window.history.replaceState({}, document.title, cleanUrl);
        return null;
      }
    }
    sessionStorage.setItem(SHORTCUT_DEDUP_KEY, JSON.stringify({ sig, ts: Date.now() }));
  } catch (e) {
    // ignore sessionStorage errors
  }

  const targetAcc = resolveTargetAccountFromList(localDb.db.accounts, cardName);
  const resolvedCategory = category || autoCategorizeMerchant(merchant);
  const txType = isRefund ? TX_TYPE_REFUND : (params.get('tx_type') || TX_TYPE_EXPENSE);

  const createdTx = localDb.createTransaction({
    date: new Date().toISOString(),
    amount: cleanAmount,
    tx_type: txType,
    account_id: targetAcc ? targetAcc.id : 1,
    category: resolvedCategory,
    description: merchant || (cardName ? `${cardName} 自動記帳` : 'iOS 捷徑快速記帳'),
    affects_balance: true,
    currency: (params.get('currency') || 'TWD').toUpperCase()
  });

  // 立即清理網址列參數，保持 iOS App 介面乾淨
  const cleanUrl = window.location.pathname + (window.location.hash.split('?')[0] || '');
  window.history.replaceState({}, document.title, cleanUrl);

  return {
    transaction: createdTx,
    account_name: targetAcc ? targetAcc.name : '預設帳戶',
    account_balance: targetAcc ? targetAcc.balance : 0
  };
}

// ==============================================================================
// 本地 REST API 攔截路由器 (0ms Instant Response Simulator)
// ==============================================================================
function jsonResponse(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      'Content-Type': 'application/json',
      'X-Local-First': 'true'
    }
  });
}

export async function handleLocalApiRequest(urlStr, options = {}) {
  const url = new URL(urlStr, typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000');
  const path = url.pathname;
  const method = (options.method || 'GET').toUpperCase();
  let body = {};
  if (options.body && typeof options.body === 'string') {
    try {
      body = JSON.parse(options.body);
    } catch {
      body = {};
    }
  }

  // 1. Auth APIs (本地模式永不登出、0 延遲自動認證)
  if (path === '/api/auth/config') {
    return jsonResponse({ allow_registration: false, local_first: true });
  }
  if (path === '/api/auth/login' || path === '/api/auth/register') {
    const user = localDb.db.user || { id: 1, username: 'admin', display_name: '預設管理員' };
    return jsonResponse({ access_token: 'ios-local-first-token', token_type: 'bearer', user });
  }
  if (path === '/api/auth/me') {
    return jsonResponse(localDb.db.user || { id: 1, username: 'admin', display_name: '預設管理員' });
  }
  if (path === '/api/auth/profile' && method === 'PUT') {
    localDb.db.user = {
      ...(localDb.db.user || { id: 1, username: 'admin' }),
      display_name: body.display_name || localDb.db.user?.display_name || '預設管理員'
    };
    localDb._save();
    return jsonResponse(localDb.db.user);
  }

  // 2. Accounts APIs
  if (path === '/api/accounts' && method === 'GET') {
    return jsonResponse(localDb.db.accounts || []);
  }
  if (path === '/api/accounts' && method === 'POST') {
    const maxId = (localDb.db.accounts || []).reduce((m, a) => Math.max(m, Number(a.id) || 0), 0);
    const newAcc = {
      id: maxId + 1,
      user_id: 1,
      name: body.name || '新帳戶',
      account_type: body.account_type || 'SAVINGS',
      balance: Number(body.balance) || 0,
      currency: (body.currency || 'TWD').toUpperCase(),
      is_dbs_default_debit: Boolean(body.is_dbs_default_debit)
    };
    if (newAcc.is_dbs_default_debit) {
      (localDb.db.accounts || []).forEach(a => { a.is_dbs_default_debit = false; });
    }
    localDb.db.accounts.push(newAcc);
    localDb._save();
    return jsonResponse(newAcc);
  }
  const accMatch = path.match(/^\/api\/accounts\/(\d+)$/);
  if (accMatch) {
    const accId = Number(accMatch[1]);
    const acc = (localDb.db.accounts || []).find(a => Number(a.id) === accId);
    if (!acc) return jsonResponse({ detail: '找不到帳戶' }, 404);

    if (method === 'PUT') {
      if (body.is_dbs_default_debit) {
        (localDb.db.accounts || []).forEach(a => { a.is_dbs_default_debit = false; });
        acc.is_dbs_default_debit = true;
      }
      if (body.name !== undefined) acc.name = body.name;
      if (body.account_type !== undefined) acc.account_type = body.account_type;
      if (body.balance !== undefined) acc.balance = Number(body.balance) || 0;
      if (body.currency !== undefined) acc.currency = body.currency;
      localDb._save();
      return jsonResponse(acc);
    }
    if (method === 'DELETE') {
      localDb.db.accounts = (localDb.db.accounts || []).filter(a => Number(a.id) !== accId);
      localDb._save();
      return jsonResponse({ status: 'success' });
    }
  }

  // 3. Transactions & Exchange Rates APIs
  if (path === '/api/transactions/exchange-rates') {
    return jsonResponse({
      base_currency: 'TWD',
      currencies: localDb.db.currencies || DEFAULT_CURRENCIES
    });
  }
  if (path === '/api/transactions' && method === 'GET') {
    const limit = Number(url.searchParams.get('limit')) || 1000;
    return jsonResponse((localDb.db.transactions || []).slice(0, limit));
  }
  if (path === '/api/transactions' && method === 'POST') {
    const created = localDb.createTransaction(body);
    return jsonResponse(created);
  }
  const txMatch = path.match(/^\/api\/transactions\/(\d+)$/);
  if (txMatch) {
    const txId = Number(txMatch[1]);
    if (method === 'PUT') {
      try {
        const updated = localDb.updateTransaction(txId, body);
        return jsonResponse(updated);
      } catch (e) {
        return jsonResponse({ detail: e.message }, 404);
      }
    }
    if (method === 'DELETE') {
      return jsonResponse(localDb.deleteTransaction(txId, true));
    }
  }

  // 4. Categories & Category Colors APIs
  if (path === '/api/categories' && method === 'GET') {
    return jsonResponse({ categories: localDb.db.categories || DEFAULT_EXPENSE_CATEGORIES });
  }
  if (path === '/api/categories' && method === 'POST') {
    if (Array.isArray(body.categories) && body.categories.length > 0) {
      localDb.db.categories = body.categories;
      localDb._save();
    }
    return jsonResponse({ status: 'success', categories: localDb.db.categories });
  }
  if (path === '/api/categories/reset' && method === 'POST') {
    localDb.db.categories = [...DEFAULT_EXPENSE_CATEGORIES];
    localDb._save();
    return jsonResponse({ status: 'success', categories: localDb.db.categories });
  }
  if (path === '/api/category-colors' && method === 'GET') {
    return jsonResponse({ colors: localDb.db.category_colors || {} });
  }
  if (path === '/api/category-colors' && method === 'POST') {
    localDb.db.category_colors = body.colors || {};
    localDb._save();
    return jsonResponse({ status: 'success', colors: localDb.db.category_colors });
  }
  if (path === '/api/category-colors/reset' && method === 'POST') {
    localDb.db.category_colors = {};
    localDb._save();
    return jsonResponse({ status: 'success', colors: {} });
  }

  // 5. Recurring Expenses APIs
  if (path === '/api/recurring-expenses' && method === 'GET') {
    return jsonResponse(localDb.getRecurringSummary());
  }
  if (path === '/api/recurring-expenses' && method === 'POST') {
    const list = localDb.db.recurring_expenses || [];
    const maxId = list.reduce((m, r) => Math.max(m, Number(r.id) || 0), 0);
    const newItem = {
      id: maxId + 1,
      user_id: 1,
      name: body.name || '固定開銷',
      amount: Number(body.amount) || 0,
      category: body.category || CATEGORY_DEFAULT,
      frequency: body.frequency || FREQUENCY_MONTHLY,
      due_month: body.due_month ? Number(body.due_month) : null,
      due_day: body.due_day ? Number(body.due_day) : 1,
      account_id: body.account_id ? Number(body.account_id) : null,
      auto_debit: Boolean(body.auto_debit),
      is_active: body.is_active !== false,
      last_charged_month: null,
      notes: body.notes || '',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    };
    list.push(newItem);
    localDb.db.recurring_expenses = list;
    localDb._save();
    return jsonResponse(newItem);
  }
  const recChargeMatch = path.match(/^\/api\/recurring-expenses\/(\d+)\/charge$/);
  if (recChargeMatch && method === 'POST') {
    const id = Number(recChargeMatch[1]);
    const item = (localDb.db.recurring_expenses || []).find(r => Number(r.id) === id);
    if (!item) return jsonResponse({ detail: '找不到固定花費項目' }, 404);
    const now = new Date();
    const curMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    localDb._chargeSingleRecurringItem(item, curMonth, false);
    return jsonResponse({ status: 'success', message: `已完成【${item.name}】扣款記帳 NT$ ${Number(item.amount).toLocaleString()}` });
  }
  const recMatch = path.match(/^\/api\/recurring-expenses\/(\d+)$/);
  if (recMatch) {
    const id = Number(recMatch[1]);
    const list = localDb.db.recurring_expenses || [];
    const idx = list.findIndex(r => Number(r.id) === id);
    if (idx === -1) return jsonResponse({ detail: '找不到固定花費項目' }, 404);
    if (method === 'PUT') {
      list[idx] = { ...list[idx], ...body, id, updated_at: new Date().toISOString() };
      localDb._save();
      return jsonResponse(list[idx]);
    }
    if (method === 'DELETE') {
      const removed = list.splice(idx, 1)[0];
      localDb._save();
      return jsonResponse({ status: 'success', message: `已刪除 ${removed.name}` });
    }
  }

  // 6. Stocks APIs
  if (path === '/api/stocks' && method === 'GET') {
    return jsonResponse(localDb.getStockPortfolioSummary());
  }
  if (path === '/api/stocks' && method === 'POST') {
    const list = localDb.db.stock_holdings || [];
    const maxId = list.reduce((m, s) => Math.max(m, Number(s.id) || 0), 0);
    const newStock = {
      id: maxId + 1,
      user_id: 1,
      symbol: (body.symbol || '').toUpperCase(),
      name: body.name || (body.symbol || '').toUpperCase(),
      shares: Number(body.shares) || 0,
      cost_price: Number(body.cost_price) || 0,
      current_price: Number(body.current_price || body.cost_price) || 0,
      currency: (body.currency || 'TWD').toUpperCase(),
      notes: body.notes || '',
      updated_at: new Date().toISOString(),
      created_at: new Date().toISOString()
    };
    list.push(newStock);
    localDb.db.stock_holdings = list;
    localDb._save();
    return jsonResponse(newStock);
  }
  if (path === '/api/stocks/refresh' && method === 'POST') {
    return jsonResponse(localDb.getStockPortfolioSummary());
  }
  const stockMatch = path.match(/^\/api\/stocks\/(\d+)$/);
  if (stockMatch) {
    const id = Number(stockMatch[1]);
    const list = localDb.db.stock_holdings || [];
    const idx = list.findIndex(s => Number(s.id) === id);
    if (idx === -1) return jsonResponse({ detail: '找不到持股' }, 404);
    if (method === 'PUT') {
      list[idx] = { ...list[idx], ...body, id, updated_at: new Date().toISOString() };
      localDb._save();
      return jsonResponse(list[idx]);
    }
    if (method === 'DELETE') {
      list.splice(idx, 1);
      localDb._save();
      return jsonResponse({ status: 'success' });
    }
  }

  // 7. Bills & Installments APIs
  if (path === '/api/bills' && method === 'GET') {
    return jsonResponse(localDb.db.bills || []);
  }
  if (path === '/api/bills' && method === 'POST') {
    const list = localDb.db.bills || [];
    const maxId = list.reduce((m, b) => Math.max(m, Number(b.id) || 0), 0);
    const newBill = { id: maxId + 1, status: BILL_STATUS_PENDING, ...body };
    list.push(newBill);
    localDb.db.bills = list;
    localDb._save();
    return jsonResponse(newBill);
  }
  const billMatch = path.match(/^\/api\/bills\/(\d+)$/);
  if (billMatch) {
    const id = Number(billMatch[1]);
    const list = localDb.db.bills || [];
    const idx = list.findIndex(b => Number(b.id) === id);
    if (method === 'PUT' && idx !== -1) {
      list[idx] = { ...list[idx], ...body, id };
      localDb._save();
      return jsonResponse(list[idx]);
    }
    if (method === 'DELETE' && idx !== -1) {
      list.splice(idx, 1);
      localDb._save();
      return jsonResponse({ status: 'success' });
    }
  }
  const billPayMatch = path.match(/^\/api\/bills\/(\d+)\/pay$/);
  if (billPayMatch && method === 'POST') {
    const id = Number(billPayMatch[1]);
    const bill = (localDb.db.bills || []).find(b => Number(b.id) === id);
    if (bill && bill.status !== BILL_STATUS_PAID) {
      bill.status = BILL_STATUS_PAID;
      const defaultAcc = (localDb.db.accounts || []).find(a => a.is_dbs_default_debit) || localDb.db.accounts?.[0];
      localDb.createTransaction({
        amount: Number(bill.total_amount) || 0,
        tx_type: TX_TYPE_EXPENSE,
        account_id: defaultAcc ? defaultAcc.id : 1,
        category: CATEGORY_CREDIT_CARD,
        description: `繳納信用卡帳單: ${bill.bank_name || ''}`
      });
    }
    return jsonResponse({ status: 'success' });
  }

  if (path === '/api/installments' && method === 'GET') {
    return jsonResponse(localDb.db.installments || []);
  }
  if (path === '/api/installments/summary' && method === 'GET') {
    return jsonResponse({
      active_plans_count: 0,
      completed_plans_count: 0,
      total_principal: 0,
      total_paid_amount: 0,
      total_remaining_amount: 0,
      this_month_payment: 0,
      next_month_payment: 0,
      monthly_forecast: []
    });
  }

  // 8. Settings & Salary & Insurance APIs
  if (path === '/api/settings' && method === 'GET') {
    return jsonResponse(localDb.getSettingsStatus());
  }
  if (path === '/api/settings' && method === 'POST') {
    localDb.db.settings = {
      ...(localDb.db.settings || {}),
      ...body
    };
    localDb._save();
    return jsonResponse(localDb.getSettingsStatus());
  }
  if (path === '/api/settings/calculate-insurance') {
    const sal = Number(url.searchParams.get('salary')) || 0;
    const dep = Number(url.searchParams.get('dependents')) || 0;
    const pen = Number(url.searchParams.get('pension_rate')) || 0;
    const tax = Number(url.searchParams.get('tax_rate')) || 0;
    return jsonResponse(calculateInsuranceSummary(sal, dep, pen, tax));
  }
  if (path === '/api/salary/apply' && method === 'POST') {
    const netAmt = Number(body.net_pay || body.amount || localDb.getSettingsStatus().net_salary) || 0;
    const accId = body.account_id || localDb.getSettingsStatus().salary_account_id || 1;
    const tx = localDb.createTransaction({
      amount: netAmt,
      tx_type: TX_TYPE_INCOME,
      account_id: accId,
      category: CATEGORY_SALARY,
      description: body.description || '本月實領薪資入帳'
    });
    return jsonResponse({ status: 'success', transaction: tx });
  }
  if (path === '/api/sync/auto-debit' && method === 'POST') {
    const cnt = localDb.executeAutoRecurringDebits();
    return jsonResponse({ status: 'success', message: `本地自動扣款檢查完成（新執行 ${cnt} 筆到期固定開銷）` });
  }

  // 9. Analytics & AI Advisor & Webhook Test APIs
  if (path === '/api/analytics/monthly-trends') {
    const m = Number(url.searchParams.get('months')) || 6;
    return jsonResponse(localDb.getMonthlyTrends(m));
  }
  if (path === '/api/ai/advisor/snapshot') {
    return jsonResponse(localDb.getAdvisorSnapshot());
  }
  if (path === '/api/ai/advisor/ask' && method === 'POST') {
    return jsonResponse(localDb.buildLocalAdvisorReply(body.question || '', Boolean(body.courage_mode)));
  }
  if (path === '/api/webhook/token') {
    return jsonResponse({
      webhook_token: 'ios-local-direct',
      webhook_url: '/?ios_shortcut=1&amount=100&merchant=消費商家&card=預設帳戶'
    });
  }
  if (path === '/api/webhook/apple-pay/test' && method === 'POST') {
    const targetAcc = resolveTargetAccountFromList(localDb.db.accounts, body.card_name);
    const tx = localDb.createTransaction({
      amount: Number(body.amount) || 65,
      tx_type: TX_TYPE_EXPENSE,
      account_id: targetAcc ? targetAcc.id : 1,
      category: body.category || '飲食',
      description: body.merchant || '星巴克咖啡 (iOS 本地測試)'
    });
    return jsonResponse({
      status: 'success',
      transaction_id: tx.id,
      amount: tx.amount,
      merchant: tx.description,
      category: tx.category,
      account_name: targetAcc ? targetAcc.name : '預設帳戶',
      account_balance: targetAcc ? targetAcc.balance : 0
    });
  }

  // 預設回退
  return jsonResponse({ status: 'ok', local_first: true });
}

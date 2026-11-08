/**
 * 前端主應用程式狀態與互動控制層 (Vue 3 Composition API)
 */

import {
  QUICK_CATEGORIES,
  CHART_PALETTE,
  CATEGORY_COLORS,
  SAVINGS_COLOR,
  MASTER_UNIQUE_PALETTE,
  assignUniqueColors,
  getCategoryColor,
  formatMoney,
  formatStockPrice,
  formatStockShares,
  formatStockTotal,
  isDueSoon,
  evaluateMathExpression
} from './formatters.js?v=2.9.0';
import { ApiService, AuthStorage } from './api.js?v=2.15.1';
import { renderExpenseDoughnutChart, renderMonthlyTrendChart } from './chart.js?v=2.9.0';
import {
  calculateLaborInsurance,
  calculateHealthInsurance,
  calculateInsuranceSummary
} from './insurance.js?v=2.9.0';

// PWA Service Worker 註冊
if (typeof window !== 'undefined' && 'serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' })
      .then((reg) => {
        console.log('[PWA] Service Worker 註冊成功，管理範圍:', reg.scope);
      })
      .catch((err) => {
        console.warn('[PWA] Service Worker 註冊失敗:', err);
      });
  });
}

const safeCategoryColor = (cat, idx = 0, customColors = {}) => {
  try {
    if (customColors && typeof customColors === 'object' && customColors[cat]) {
      return customColors[cat];
    }
    if (typeof getCategoryColor === 'function') {
      return getCategoryColor(cat, idx, customColors);
    }
    if (typeof CATEGORY_COLORS !== 'undefined' && cat && CATEGORY_COLORS[cat]) {
      return CATEGORY_COLORS[cat];
    }
    if (cat && (cat.includes('投資') || cat.includes('理財') || cat.includes('基金') || cat.includes('ETF'))) {
      return '#8B5CF6';
    }
    if (typeof CHART_PALETTE !== 'undefined' && CHART_PALETTE.length) {
      return CHART_PALETTE[idx % CHART_PALETTE.length];
    }
  } catch (e) {
    console.warn('safeCategoryColor error:', e);
  }
  return '#8B5CF6';
};

const { createApp, ref, computed, onMounted, nextTick, watch } = window.Vue;

createApp({
  setup() {
    // 認證與多使用者狀態
    const isAuthenticated = ref(Boolean(AuthStorage.getToken()));
    const currentUser = ref(AuthStorage.getUser());
    const authMode = ref('login'); // 'login' | 'register'
    const allowRegistration = ref(false); // 伺服器是否開放外網註冊 (資安保護預設關閉)
    const authLoading = ref(false);
    const authError = ref('');
    const authForm = ref({
      username: '',
      password: '',
      display_name: ''
    });
    const testingImap = ref(false);
    const imapTestResult = ref(null);

    // Apple Pay / iOS 捷徑 Webhook 狀態
    const webhookToken = ref('');
    const webhookUrl = ref('');
    const webhookCopySuccess = ref(false);
    const webhookTutorialOpen = ref(false);
    const testingWebhook = ref(false);
    const webhookTestResult = ref(null);

    const profileForm = ref({
      display_name: '',
      current_password: '',
      new_password: ''
    });

    const accounts = ref([]);
    const bills = ref([]);
    const transactions = ref([]);

    // 導航分頁與選單狀態 (方案 B: 4 大核心分頁 + 子分頁)
    const currentTab = ref('dashboard'); // 'dashboard' | 'transactions' | 'assets' | 'trends'
    const txSubTab = ref('list'); // 'list' | 'recurring'
    const assetSubTab = ref('accounts'); // 'accounts' | 'bills' | 'stocks'
    const mobileMenuOpen = ref(false);

    // 資產金額隱私開關 (預設隱藏)
    const savedHideAssets = localStorage.getItem('hideAssets');
    const hideAssets = ref(savedHideAssets !== null ? savedHideAssets === 'true' : true);

    const refreshIcons = () => {
      nextTick(() => {
        if (window.lucide) {
          window.lucide.createIcons();
        }
      });
    };

    const toggleHideAssets = () => {
      hideAssets.value = !hideAssets.value;
      localStorage.setItem('hideAssets', hideAssets.value ? 'true' : 'false');
      refreshIcons();
    };

    // 深色模式 (Dark Mode)
    const isDarkMode = ref(
      document.documentElement.classList.contains('dark') ||
      localStorage.getItem('theme') === 'dark' ||
      (!('theme' in localStorage) && window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)
    );

    const updateThemeColorMeta = () => {
      const metas = document.querySelectorAll('meta[name="theme-color"]');
      const color = isDarkMode.value ? '#1e293b' : '#ffffff';
      metas.forEach(m => m.setAttribute('content', color));
    };

    const toggleDarkMode = () => {
      isDarkMode.value = !isDarkMode.value;
      if (isDarkMode.value) {
        document.documentElement.classList.add('dark');
        localStorage.setItem('theme', 'dark');
      } else {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('theme', 'light');
      }
      updateThemeColorMeta();
      refreshIcons();
      renderChart();
      if (typeof renderTrendChart === 'function') {
        renderTrendChart();
      }
    };

    // 視覺風格主題 (Theme: 'default' | 'courage')
    const currentTheme = ref(localStorage.getItem('app_theme') || 'default');

    const applyThemeToDOM = (themeName) => {
      if (themeName === 'courage') {
        document.documentElement.classList.add('theme-courage');
      } else {
        document.documentElement.classList.remove('theme-courage');
      }
    };

    // 初始化載入主題
    applyThemeToDOM(currentTheme.value);

    const setTheme = (themeName) => {
      currentTheme.value = themeName;
      localStorage.setItem('app_theme', themeName);
      applyThemeToDOM(themeName);
      triggerHaptic('light');
      refreshIcons();
      renderChart();
      if (typeof renderTrendChart === 'function') {
        renderTrendChart();
      }
    };

    const toggleTheme = () => {
      setTheme(currentTheme.value === 'courage' ? 'default' : 'courage');
    };

    const currentTabTitle = computed(() => {
      switch (currentTab.value) {
        case 'dashboard': return '總覽儀表板';
        case 'transactions':
          return txSubTab.value === 'recurring' ? '固定開銷規劃' : '收支記帳流水帳';
        case 'assets':
          if (assetSubTab.value === 'bills') return '信用卡帳單總覽';
          if (assetSubTab.value === 'stocks') return '股票投資';
          if (assetSubTab.value === 'installments') return '信用卡分期付款管理';
          return '各帳戶存款資產';
        case 'trends': return '收支與存款趨勢報表';
        default: return '總覽儀表板';
      }
    });

    const getAccountName = (accId) => {
      const acc = accounts.value.find(a => a.id === accId);
      return acc ? acc.name : '';
    };

    // 流水帳專屬搜尋與篩選 (支援年度與月份獨立或組合選擇)
    const txSearch = ref('');
    const txTypeFilter = ref('ALL');
    const txYearFilter = ref('');   // '' 代表全部年份，或 '2026'
    const txMonthFilter = ref('');  // '' 代表全部月份，或 '11'，亦相容舊版 '2026-11'

    // 自動偵測現有交易紀錄中存在的年份，並納入當前年份
    const availableTxYears = computed(() => {
      const currentYear = new Date().getFullYear();
      const yearsSet = new Set([String(currentYear)]);
      (transactions.value || []).forEach(tx => {
        if (tx.date && tx.date.length >= 4) {
          const y = tx.date.substring(0, 4);
          if (/^\d{4}$/.test(y)) {
            yearsSet.add(y);
          }
        }
      });
      return Array.from(yearsSet).sort().reverse();
    });

    const filteredTransactions = computed(() => {
      return (transactions.value || []).filter(tx => {
        if (txTypeFilter.value !== 'ALL' && tx.tx_type !== txTypeFilter.value) {
          return false;
        }
        const txDate = tx.date || '';
        // 1. 年度篩選
        if (txYearFilter.value) {
          const txYear = txDate.substring(0, 4);
          if (txYear !== txYearFilter.value) {
            return false;
          }
        }
        // 2. 月份篩選 (相容 '11' 或 '2026-11' 格式)
        if (txMonthFilter.value) {
          if (txMonthFilter.value.includes('-')) {
            if (txDate.substring(0, 7) !== txMonthFilter.value) {
              return false;
            }
          } else {
            const txMonth = txDate.length >= 7 ? txDate.substring(5, 7) : '';
            if (txMonth !== txMonthFilter.value) {
              return false;
            }
          }
        }
        // 3. 關鍵字搜尋
        if (txSearch.value.trim()) {
          const q = txSearch.value.trim().toLowerCase();
          const desc = (tx.description || '').toLowerCase();
          const cat = (tx.category || '').toLowerCase();
          const acc = (getAccountName(tx.account_id) || '').toLowerCase();
          if (!desc.includes(q) && !cat.includes(q) && !acc.includes(q)) {
            return false;
          }
        }
        return true;
      });
    });

    const setTxCurrentMonth = () => {
      triggerHaptic('light');
      const now = new Date();
      txYearFilter.value = String(now.getFullYear());
      txMonthFilter.value = String(now.getMonth() + 1).padStart(2, '0');
      nextTick(() => refreshIcons());
    };

    const prevTxMonth = () => {
      triggerHaptic('light');
      const now = new Date();
      let y = txYearFilter.value ? parseInt(txYearFilter.value, 10) : now.getFullYear();
      let m = txMonthFilter.value ? parseInt(txMonthFilter.value, 10) : (now.getMonth() + 1);
      m -= 1;
      if (m < 1) {
        m = 12;
        y -= 1;
      }
      txYearFilter.value = String(y);
      txMonthFilter.value = String(m).padStart(2, '0');
      nextTick(() => refreshIcons());
    };

    const nextTxMonth = () => {
      triggerHaptic('light');
      const now = new Date();
      let y = txYearFilter.value ? parseInt(txYearFilter.value, 10) : now.getFullYear();
      let m = txMonthFilter.value ? parseInt(txMonthFilter.value, 10) : (now.getMonth() + 1);
      m += 1;
      if (m > 12) {
        m = 1;
        y += 1;
      }
      txYearFilter.value = String(y);
      txMonthFilter.value = String(m).padStart(2, '0');
      nextTick(() => refreshIcons());
    };

    const clearTxDateFilter = () => {
      triggerHaptic('light');
      txYearFilter.value = '';
      txMonthFilter.value = '';
      nextTick(() => refreshIcons());
    };

    const triggerHaptic = (type = 'light') => {
      if (typeof navigator !== 'undefined' && 'vibrate' in navigator) {
        try {
          if (type === 'light') navigator.vibrate(10);
          else if (type === 'medium') navigator.vibrate(25);
          else if (type === 'success') navigator.vibrate([15, 40, 20]);
        } catch (e) {
          // ignore
        }
      }
    };

    const formatGroupDate = (dateStr) => {
      if (!dateStr) return '未指定日期';
      try {
        const rawDate = dateStr.substring(0, 10);
        const parts = rawDate.split('-');
        if (parts.length !== 3) return rawDate;
        const year = parseInt(parts[0], 10);
        const month = parseInt(parts[1], 10);
        const day = parseInt(parts[2], 10);
        const d = new Date(year, month - 1, day);
        if (isNaN(d.getTime())) return rawDate;

        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const target = new Date(year, month - 1, day);
        const diffDays = Math.round((today - target) / (1000 * 60 * 60 * 24));

        const weekdays = ['日', '一', '二', '三', '四', '五', '六'];
        const dayName = '週' + weekdays[d.getDay()];

        if (diffDays === 0) return `今天 · ${month}月${day}日 ${dayName}`;
        if (diffDays === 1) return `昨天 · ${month}月${day}日 ${dayName}`;
        if (diffDays === 2) return `前天 · ${month}月${day}日 ${dayName}`;
        if (year === today.getFullYear()) {
          return `${month}月${day}日 ${dayName}`;
        }
        return `${year}年${month}月${day}日 ${dayName}`;
      } catch (e) {
        return dateStr.substring(0, 10);
      }
    };

    const groupedTransactionsByDate = computed(() => {
      const list = filteredTransactions.value || [];
      const groupsMap = new Map();

      list.forEach(tx => {
        const dateKey = tx.date ? tx.date.substring(0, 10) : '未指定日期';
        if (!groupsMap.has(dateKey)) {
          groupsMap.set(dateKey, {
            dateStr: dateKey,
            dateDisplay: formatGroupDate(dateKey),
            dayExpenseTotal: 0,
            dayIncomeTotal: 0,
            transactions: []
          });
        }
        const group = groupsMap.get(dateKey);
        group.transactions.push(tx);
        if (tx.tx_type === 'EXPENSE') {
          group.dayExpenseTotal += (tx.amount || 0);
        } else if (tx.tx_type === 'REFUND') {
          group.dayExpenseTotal -= Math.abs(tx.amount || 0);
        } else if (tx.tx_type === 'INCOME') {
          group.dayIncomeTotal += (tx.amount || 0);
        }
      });

      return Array.from(groupsMap.values());
    });

    watch(groupedTransactionsByDate, () => {
      nextTick(() => refreshIcons());
    });

    const txStats = computed(() => {
      let exp = 0;
      let inc = 0;
      filteredTransactions.value.forEach(t => {
        if (t.tx_type === 'EXPENSE') exp += (t.amount || 0);
        else if (t.tx_type === 'REFUND') exp -= Math.abs(t.amount || 0);
        else if (t.tx_type === 'INCOME') inc += (t.amount || 0);
      });
      return {
        expense: exp,
        income: inc,
        net: inc - exp,
        count: filteredTransactions.value.length
      };
    });

    // 總覽主頁專用最近 5 筆紀錄
    const recentTransactions = computed(() => {
      return (transactions.value || []).slice(0, 5);
    });

    const settings = ref({
      is_google_connected: false,
      is_imap_configured: false,
      has_pdf_password: false,
      has_gemini_api_key: false,
      default_debit_account_name: null,
      monthly_salary: 50000,
      deduct_labor_health: false,
      health_insurance_dependents: 1,
      labor_insurance_fee: 1100,
      health_insurance_fee: 785,
      pension_rate: 0.0,
      pension_fee: 0,
      tax_rate: 0.05,
      tax_fee: 2500,
      show_deductions_in_chart: true,
      labor_health_auto_calc: true,
      net_salary: 50000,
      imap_email: '',
      imap_app_password: '',
      imap_server: 'imap.gmail.com'
    });

    const salaryInput = ref(50000);
    const todayStr = new Date().toISOString().substring(0, 10);
    const currentMonth = ref(todayStr.substring(0, 7));
    const selectedMonth = ref(todayStr.substring(0, 7));

    const syncing = ref(false);
    const uploading = ref(false);
    const showAccountModal = ref(false);
    const showTxModal = ref(false);
    const showUploadModal = ref(false);
    const showQuickActionSheet = ref(false);
    const showParseResultModal = ref(false);
    const showEditBillModal = ref(false);
    const showSettingsModal = ref(false);
    const settingsTab = ref('salary'); // 'salary' | 'sync' | 'account'

    // 月底帳單對帳核銷狀態
    const showReconcileModal = ref(false);
    const reconcileLoading = ref(false);
    const reconcileBill = ref(null);
    const reconcileData = ref(null);
    const reconcileAccountFilter = ref('');
    const reconcileStartDate = ref('');
    const reconcileEndDate = ref('');
    const reconcileIncludeAll = ref(false);
    const reconcileTabFilter = ref('ALL');
    const reconcileSelectedIds = ref(new Set());
    const isSavingReconcile = ref(false);
    const isSettlingReconcile = ref(false);
    const showQuickAddModal = ref(false);
    const quickAddForm = ref({
      date: '',
      category: '其他',
      description: '',
      amount: 0,
      tx_type: 'EXPENSE',
      credit_account_id: null
    });
    const showSettleConfirm = ref(false);
    const settleForm = ref({
      debit_account_id: null,
      credit_account_id: null,
      settlement_mode: 'TRANSFER'
    });

    // 股票投資組合狀態
    const stockPortfolio = ref({
      total_market_value_twd: 0,
      total_cost_twd: 0,
      total_unrealized_pnl_twd: 0,
      total_return_rate: 0,
      usd_to_twd_rate: 32.0,
      holdings: []
    });
    const showStockModal = ref(false);
    const refreshingStocks = ref(false);
    const savingStock = ref(false);
    const currentStock = ref({
      id: null,
      symbol: '',
      name: '',
      shares: null,
      cost_price: null,
      currency: '',
      notes: ''
    });

    // 每月固定花費狀態
    const recurringExpenses = ref({
      total_monthly_amount: 0,
      charged_count: 0,
      pending_count: 0,
      items: []
    });
    const showRecurringModal = ref(false);
    const savingRecurring = ref(false);
    const currentRecurring = ref({
      id: null,
      name: '',
      amount: null,
      category: '保險',
      frequency: 'MONTHLY',
      due_month: new Date().getMonth() + 1,
      due_day: null,
      account_id: null,
      is_active: true,
      notes: ''
    });

    // 信用卡分期付款狀態
    const installments = ref([]);
    const installmentSummary = ref(null);
    const installmentFilterStatus = ref('ACTIVE'); // 'ACTIVE' | 'ALL' | 'COMPLETED'
    const showInstallmentModal = ref(false);
    const showInstallmentDetailModal = ref(false);
    const savingInstallment = ref(false);
    const chargingInstallment = ref(false);
    const currentInstallment = ref({
      id: null,
      name: '',
      total_amount: null,
      total_periods: 3,
      current_period: 0,
      monthly_amount: null,
      first_amount: null,
      interest_rate: 0,
      monthly_fee: 0,
      category: '購物',
      account_id: null,
      start_date: todayStr,
      billing_day: new Date().getDate(),
      status: 'ACTIVE',
      notes: '',
      auto_record: false,
      record_first_period: false
    });
    const selectedPlanDetail = ref(null);
    const loadingPlanDetail = ref(false);

    // AI 智慧財務顧問狀態
    const showAdvisorModal = ref(false);
    const advisorLoading = ref(false);
    const advisorQuestion = ref('');
    const advisorChat = ref([]);
    const advisorSnapshot = ref(null);
    const advisorCopiedId = ref(null);

    const uploadPwd = ref('');
    const documentInput = ref(null);
    const selectedFilesCount = ref(0);
    const batchProgress = ref({ current: 0, total: 0, currentFileName: '' });
    const batchParsedList = ref([]);
    const showBatchResultModal = ref(false);
    const isSavingBatch = ref(false);

    // 單筆辨識結果暫存
    const parsedData = ref({
      document_type: 'EXPENSE_RECEIPT',
      bank_or_company: '',
      statement_month: '',
      total_amount: 0,
      due_date: '',
      category: '其他',
      description: '',
      debit_account_id: null,
      confidence_summary: '',
      record_salary_tx: true,
      salary_account_id: null,
      pdf_filename: '',
      currency: 'TWD',
      original_amount: 0,
      exchange_rate: 1.0
    });

    // 帳單編輯暫存
    const currentBill = ref({
      id: null,
      bank_name: '星展銀行',
      statement_month: '',
      due_date: todayStr,
      total_amount: 0,
      debit_account_id: null,
      status: 'PENDING'
    });

    const currentAcc = ref({ name: '', account_type: 'SAVINGS', balance: 0, account_number: '', is_dbs_default_debit: false });
    const currentTx = ref({ amount: null, tx_type: 'EXPENSE', account_id: null, category: '飲食', description: '', date: todayStr, affects_balance: false });
    const settingsForm = ref({
      google_client_id: '',
      google_client_secret: '',
      google_redirect_uri: window.location.origin + '/api/auth/google/callback',
      imap_email: '',
      imap_app_password: '',
      imap_server: 'imap.gmail.com',
      id_card_password: '',
      dbs_pdf_password: '',
      gemini_api_key: '',
      monthly_salary: 50000,
      deduct_labor_health: false,
      health_insurance_dependents: 1,
      labor_insurance_fee: 1100,
      health_insurance_fee: 785,
      pension_rate: 0.0,
      pension_fee: 0,
      tax_rate: 0.05,
      tax_fee: 2500,
      show_deductions_in_chart: true,
      labor_health_auto_calc: true,
      auto_debit_bills: false,
      salary_account_id: null,
      salary_pay_day: 5,
      auto_salary_income: false
    });

    // 勞健保與實領薪資計算 (Effective Net Salary)
    const effectiveSalary = computed(() => {
      const gross = Number(salaryInput.value) || 0;
      if (!settings.value.deduct_labor_health) {
        return gross;
      }
      const labor = Number(settings.value.labor_insurance_fee || 0);
      const health = Number(settings.value.health_insurance_fee || 0);
      const pension = Number(settings.value.pension_fee || 0);
      const tax = Number(settings.value.tax_fee || 0);
      return Math.max(0, gross - labor - health - pension - tax);
    });

    const totalInsuranceDeduction = computed(() => {
      if (!settings.value.deduct_labor_health) return 0;
      const labor = Number(settings.value.labor_insurance_fee || 0);
      const health = Number(settings.value.health_insurance_fee || 0);
      const pension = Number(settings.value.pension_fee || 0);
      const tax = Number(settings.value.tax_fee || 0);
      return labor + health + pension + tax;
    });

    // 設定彈窗中的即時預覽計算
    const settingsInsurancePreview = computed(() => {
      const sal = Number(settingsForm.value.monthly_salary) || 0;
      const dep = Number(settingsForm.value.health_insurance_dependents) || 1;
      const pen = Number(settingsForm.value.pension_rate) || 0;
      const taxRate = Number(settingsForm.value.tax_rate) || 0;
      return calculateInsuranceSummary(sal, dep, pen, taxRate);
    });

    const onInsuranceSettingChange = () => {
      if (settingsForm.value.labor_health_auto_calc) {
        const preview = settingsInsurancePreview.value;
        settingsForm.value.labor_insurance_fee = preview.labor.fee;
        settingsForm.value.health_insurance_fee = preview.health.fee;
        settingsForm.value.pension_fee = preview.pension.fee;
        settingsForm.value.tax_fee = preview.tax.fee;
      }
    };

    const resetToAutoInsuranceFees = () => {
      settingsForm.value.labor_health_auto_calc = true;
      const preview = settingsInsurancePreview.value;
      settingsForm.value.labor_insurance_fee = preview.labor.fee;
      settingsForm.value.health_insurance_fee = preview.health.fee;
      settingsForm.value.pension_fee = preview.pension.fee;
      settingsForm.value.tax_fee = preview.tax.fee;
    };

    const totalSavings = computed(() => {
      return accounts.value
        .filter(a => a.account_type === 'SAVINGS' || a.account_type === 'CASH')
        .reduce((sum, a) => sum + (a.balance || 0), 0);
    });

    const totalNetWorth = computed(() => {
      return (totalSavings.value || 0) + (stockPortfolio.value?.total_market_value_twd || 0);
    });

    const pendingBillAmount = computed(() => {
      return bills.value
        .filter(b => b.status === 'PENDING')
        .reduce((sum, b) => sum + (b.total_amount || 0), 0);
    });

    const nextDueBill = computed(() => {
      const pending = bills.value.filter(b => b.status === 'PENDING');
      return pending.length > 0 ? pending[0] : null;
    });

    // 對帳篩選後候選清單
    const filteredReconcileTxList = computed(() => {
      if (!reconcileData.value || !reconcileData.value.transactions) return [];
      const list = reconcileData.value.transactions;
      if (reconcileTabFilter.value === 'CHECKED') {
        return list.filter(t => reconcileSelectedIds.value.has(t.id));
      } else if (reconcileTabFilter.value === 'UNCHECKED') {
        return list.filter(t => !reconcileSelectedIds.value.has(t.id));
      }
      return list;
    });

    // 即時計算已勾選金額 (支出為正，退款為負)
    const currentReconcileCheckedAmount = computed(() => {
      if (!reconcileData.value || !reconcileData.value.transactions) return 0;
      let sum = 0;
      for (const t of reconcileData.value.transactions) {
        if (reconcileSelectedIds.value.has(t.id)) {
          if (t.tx_type === 'REFUND') {
            sum -= Math.abs(t.amount || 0);
          } else {
            sum += Math.abs(t.amount || 0);
          }
        }
      }
      return Math.round(sum * 100) / 100;
    });

    // 即時對帳差額 (帳單應繳總額 - 目前已勾選金額)
    const currentReconcileDiff = computed(() => {
      if (!reconcileData.value) return 0;
      const billTotal = Number(reconcileData.value.bill_total_amount || 0);
      return Math.round((billTotal - currentReconcileCheckedAmount.value) * 100) / 100;
    });

    const isCurrentReconcileBalanced = computed(() => {
      return Math.abs(currentReconcileDiff.value) < 0.01;
    });

    // 圖表顯示模式 (支出分析 vs 收入結構)
    const chartViewMode = ref('expense'); // 'expense' | 'income'

    const isDeductionsInChart = computed(() => {
      return settings.value.deduct_labor_health && settings.value.show_deductions_in_chart !== false;
    });

    // 當月手動記錄的所有收入進帳總和
    const monthlyRecordedIncome = computed(() => {
      const targetMonth = selectedMonth.value;
      return transactions.value
        .filter(tx => tx.tx_type === 'INCOME' && (tx.date || '').substring(0, 7) === targetMonth)
        .reduce((sum, tx) => sum + (Number(tx.amount) || 0), 0);
    });

    // 當月可用總收入母數 = 基準薪資 + 當月手動記錄之各項收入
    const chartBaseSalary = computed(() => {
      const baseSalary = (isDeductionsInChart.value ? Number(salaryInput.value) : effectiveSalary.value) || 0;
      return Math.max(baseSalary + monthlyRecordedIncome.value, 1);
    });

    // 當月收入項目明細結構清單
    const monthlyIncomesList = computed(() => {
      const targetMonth = selectedMonth.value;
      const incomesByCategory = {};

      const baseSalary = (isDeductionsInChart.value ? Number(salaryInput.value) : effectiveSalary.value) || 0;
      if (baseSalary > 0) {
        incomesByCategory['固定月薪'] = baseSalary;
      }

      transactions.value.forEach(tx => {
        if (tx.tx_type === 'INCOME') {
          const txMonth = (tx.date || '').substring(0, 7);
          if (txMonth === targetMonth) {
            const cat = tx.category || '其他進帳';
            incomesByCategory[cat] = (incomesByCategory[cat] || 0) + (Number(tx.amount) || 0);
          }
        }
      });

      const totalInc = Object.values(incomesByCategory).reduce((s, a) => s + a, 0) || 1;
      const rawIncomes = Object.keys(incomesByCategory).map(cat => {
        const amt = incomesByCategory[cat];
        return {
          category: cat,
          amount: amt,
          ratioOfTotal: (amt / totalInc) * 100
        };
      });

      rawIncomes.sort((a, b) => b.amount - a.amount);
      return assignUniqueColors(rawIncomes, false, customCategoryColors.value);
    });

    const monthlyExpensesList = computed(() => {
      const expensesByCategory = {};
      const fixedByCategory = {};
      const targetMonth = selectedMonth.value;

      // 1. 該月份的一般開銷 / 信用卡手動與匯入交易
      transactions.value.forEach(tx => {
        if (tx.tx_type === 'EXPENSE') {
          const txMonth = (tx.date || '').substring(0, 7);
          if (txMonth === targetMonth) {
            const cat = tx.category || '其他';
            expensesByCategory[cat] = (expensesByCategory[cat] || 0) + tx.amount;
          }
        } else if (tx.tx_type === 'REFUND') {
          const txMonth = (tx.date || '').substring(0, 7);
          if (txMonth === targetMonth) {
            const cat = tx.category || '其他';
            expensesByCategory[cat] = (expensesByCategory[cat] || 0) - Math.abs(tx.amount);
          }
        }
      });

      // 2. 啟用中的每日常態/固定開銷 (月繳或年繳月平攤)
      if (recurringExpenses.value && recurringExpenses.value.items) {
        recurringExpenses.value.items.forEach(item => {
          if (item.is_active) {
            const cat = item.category || '其他';
            const amt = Number(item.monthly_amortized_amount || item.amount || 0);
            expensesByCategory[cat] = (expensesByCategory[cat] || 0) + amt;
            fixedByCategory[cat] = (fixedByCategory[cat] || 0) + amt;
          }
        });
      }

      const salary = chartBaseSalary.value || 1;
      const rawExpenses = Object.keys(expensesByCategory).map(cat => {
        const amount = expensesByCategory[cat];
        const fixedAmt = fixedByCategory[cat] || 0;
        return {
          category: cat,
          amount: amount,
          fixedAmount: fixedAmt,
          isDeduction: false,
          ratioOfSalary: (amount / salary) * 100
        };
      });

      // 3. 薪資法定扣繳 (全民健保、勞工保險、勞退自提、預繳所得稅) 直接納入圓餅圖與明細
      if (isDeductionsInChart.value) {
        const healthFee = Number(settings.value.health_insurance_fee || 0);
        const laborFee = Number(settings.value.labor_insurance_fee || 0);
        const pensionFee = Number(settings.value.pension_fee || 0);
        const taxFee = Number(settings.value.tax_fee || 0);

        if (healthFee > 0) {
          rawExpenses.push({
            category: '全民健保費',
            amount: healthFee,
            fixedAmount: 0,
            isDeduction: true,
            deductionLabel: '健保扣繳',
            ratioOfSalary: (healthFee / salary) * 100
          });
        }
        if (laborFee > 0) {
          rawExpenses.push({
            category: '勞工保險費',
            amount: laborFee,
            fixedAmount: 0,
            isDeduction: true,
            deductionLabel: '勞保扣繳',
            ratioOfSalary: (laborFee / salary) * 100
          });
        }
        if (pensionFee > 0) {
          const penRate = Math.round((Number(settings.value.pension_rate) || 0.06) * 100);
          rawExpenses.push({
            category: `勞退自提 (${penRate}%)`,
            amount: pensionFee,
            fixedAmount: 0,
            isDeduction: true,
            deductionLabel: '退休專戶',
            ratioOfSalary: (pensionFee / salary) * 100
          });
        }
        if (taxFee > 0) {
          const taxRate = Math.round((Number(settings.value.tax_rate) || 0.05) * 100);
          rawExpenses.push({
            category: `預繳所得稅 (${taxRate}%)`,
            amount: taxFee,
            fixedAmount: 0,
            isDeduction: true,
            deductionLabel: '薪資預扣',
            ratioOfSalary: (taxFee / salary) * 100
          });
        }
      }

      rawExpenses.sort((a, b) => b.amount - a.amount);
      return assignUniqueColors(rawExpenses, true, customCategoryColors.value);
    });

    const monthlyTotalExpense = computed(() => {
      return monthlyExpensesList.value.reduce((sum, item) => sum + item.amount, 0);
    });

    const monthlyLivingExpense = computed(() => {
      return monthlyExpensesList.value
        .filter(item => !item.isDeduction)
        .reduce((sum, item) => sum + item.amount, 0);
    });

    const expenseRatio = computed(() => {
      const salary = chartBaseSalary.value || 1;
      return (monthlyTotalExpense.value / salary) * 100;
    });

    const remainingSalary = computed(() => {
      return (chartBaseSalary.value || 0) - monthlyTotalExpense.value;
    });

    const freeBudget = computed(() => {
      return (chartBaseSalary.value || 0) - monthlyTotalExpense.value;
    });

    const renderChart = () => {
      nextTick(() => {
        renderExpenseDoughnutChart({
          canvasId: 'expenseChart',
          salary: chartBaseSalary.value,
          totalExp: monthlyTotalExpense.value,
          expensesList: monthlyExpensesList.value,
          incomesList: monthlyIncomesList.value,
          mode: chartViewMode.value
        });
      });
    };

    const setChartViewMode = (mode) => {
      chartViewMode.value = mode;
      renderChart();
      refreshIcons();
    };

    // ==================== 首頁自訂版面與自由拖曳排序 ====================
    const isEditingLayout = ref(false);
    const defaultDashboardBlocks = [
      { id: 'kpi', name: '三大核心財務指標卡片' },
      { id: 'chart', name: '收支結構與支出分析圓餅圖' },
      { id: 'transactions', name: '近期收支流水速覽' },
      { id: 'recurring', name: '每月固定開銷規劃速覽' }
    ];

    const dashboardBlockOrder = ref(defaultDashboardBlocks.map(b => b.id));
    const kpiCardsOrder = ref(['networth', 'expense', 'income', 'bills']);

    const draggedBlockIndex = ref(null);
    const dragOverBlockIndex = ref(null);

    const getBlockTitle = (id) => {
      const map = {
        'kpi': '四項核心財務指標卡片',
        'chart': '收支結構與支出分析圓餅圖',
        'transactions': '近期收支流水速覽',
        'recurring': '每月固定開銷規劃速覽'
      };
      return map[id] || id;
    };

    const loadDashboardLayout = () => {
      try {
        const saved = localStorage.getItem('account_book_dashboard_layout');
        if (saved) {
          const parsed = JSON.parse(saved);
          const allIds = defaultDashboardBlocks.map(b => b.id);
          if (Array.isArray(parsed) && parsed.length === allIds.length && allIds.every(id => parsed.includes(id))) {
            dashboardBlockOrder.value = parsed;
          }
        }
        const savedKpis = localStorage.getItem('account_book_kpi_order');
        if (savedKpis) {
          const parsedKpi = JSON.parse(savedKpis);
          const validKpiIds = ['networth', 'expense', 'income', 'bills'];
          if (Array.isArray(parsedKpi) && parsedKpi.length >= 3 && parsedKpi.every(id => validKpiIds.includes(id))) {
            if (!parsedKpi.includes('income')) {
              parsedKpi.splice(2, 0, 'income');
            }
            kpiCardsOrder.value = parsedKpi;
          }
        }
      } catch (e) {
        console.warn('載入自訂版面設定失敗:', e);
      }
    };

    const saveDashboardLayout = () => {
      try {
        localStorage.setItem('account_book_dashboard_layout', JSON.stringify(dashboardBlockOrder.value));
        localStorage.setItem('account_book_kpi_order', JSON.stringify(kpiCardsOrder.value));
      } catch (e) {
        console.warn('儲存自訂版面設定失敗:', e);
      }
    };

    const resetDashboardLayout = () => {
      dashboardBlockOrder.value = defaultDashboardBlocks.map(b => b.id);
      kpiCardsOrder.value = ['networth', 'expense', 'income', 'bills'];
      try {
        localStorage.removeItem('account_book_dashboard_layout');
        localStorage.removeItem('account_book_kpi_order');
      } catch (e) {}
      nextTick(() => {
        renderChart();
        refreshIcons();
      });
    };

    const toggleEditLayout = () => {
      isEditingLayout.value = !isEditingLayout.value;
      if (!isEditingLayout.value) {
        saveDashboardLayout();
      }
      nextTick(() => {
        renderChart();
        refreshIcons();
      });
    };

    const moveBlockUp = (index) => {
      if (index <= 0) return;
      const list = [...dashboardBlockOrder.value];
      const temp = list[index - 1];
      list[index - 1] = list[index];
      list[index] = temp;
      dashboardBlockOrder.value = list;
      saveDashboardLayout();
      nextTick(() => {
        renderChart();
        refreshIcons();
      });
    };

    const moveBlockDown = (index) => {
      if (index >= dashboardBlockOrder.value.length - 1) return;
      const list = [...dashboardBlockOrder.value];
      const temp = list[index + 1];
      list[index + 1] = list[index];
      list[index] = temp;
      dashboardBlockOrder.value = list;
      saveDashboardLayout();
      nextTick(() => {
        renderChart();
        refreshIcons();
      });
    };

    const moveKpiCardLeft = (index) => {
      if (index <= 0) return;
      const list = [...kpiCardsOrder.value];
      const temp = list[index - 1];
      list[index - 1] = list[index];
      list[index] = temp;
      kpiCardsOrder.value = list;
      saveDashboardLayout();
      nextTick(refreshIcons);
    };

    const moveKpiCardRight = (index) => {
      if (index >= kpiCardsOrder.value.length - 1) return;
      const list = [...kpiCardsOrder.value];
      const temp = list[index + 1];
      list[index + 1] = list[index];
      list[index] = temp;
      kpiCardsOrder.value = list;
      saveDashboardLayout();
      nextTick(refreshIcons);
    };

    const onBlockDragStart = (index, event) => {
      if (!isEditingLayout.value) return;
      draggedBlockIndex.value = index;
      if (event && event.dataTransfer) {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', String(index));
      }
    };

    const onBlockDragOver = (index, event) => {
      if (!isEditingLayout.value) return;
      if (event) event.preventDefault();
      dragOverBlockIndex.value = index;
      if (event && event.dataTransfer) {
        event.dataTransfer.dropEffect = 'move';
      }
    };

    const onBlockDrop = (index, event) => {
      if (!isEditingLayout.value) return;
      if (event) event.preventDefault();
      const fromIndex = draggedBlockIndex.value;
      const toIndex = index;
      if (fromIndex !== null && fromIndex !== toIndex) {
        const list = [...dashboardBlockOrder.value];
        const [moved] = list.splice(fromIndex, 1);
        list.splice(toIndex, 0, moved);
        dashboardBlockOrder.value = list;
        saveDashboardLayout();
        nextTick(() => {
          renderChart();
          refreshIcons();
        });
      }
      draggedBlockIndex.value = null;
      dragOverBlockIndex.value = null;
    };

    const onBlockDragEnd = () => {
      draggedBlockIndex.value = null;
      dragOverBlockIndex.value = null;
    };

    // 財務趨勢分析狀態
    const analyticsRange = ref(6); // 6 | 12 | 24
    const analyticsChartMode = ref('savings'); // 'savings' (月末總存款) | 'net' (當月淨結餘)
    const analyticsData = ref({
      summary: {},
      months_data: []
    });
    const loadingAnalytics = ref(false);

    const renderTrendChart = () => {
      nextTick(() => {
        renderMonthlyTrendChart({
          canvasId: 'monthlyTrendChart',
          monthsData: analyticsData.value?.months_data || [],
          chartMode: analyticsChartMode.value
        });
      });
    };

    const fetchAnalytics = async (months = analyticsRange.value) => {
      loadingAnalytics.value = true;
      try {
        const res = await ApiService.getMonthlyTrends(months);
        if (res) {
          analyticsData.value = res;
          renderTrendChart();
        }
      } catch (err) {
        console.error('Failed to fetch analytics:', err);
      } finally {
        loadingAnalytics.value = false;
        refreshIcons();
      }
    };

    const setAnalyticsRange = (r) => {
      analyticsRange.value = r;
      fetchAnalytics(r);
    };

    const setAnalyticsChartMode = (mode) => {
      analyticsChartMode.value = mode;
      renderTrendChart();
    };

    const jumpToTransactionsMonth = (monthStr) => {
      if (monthStr && monthStr.includes('-')) {
        const parts = monthStr.split('-');
        txYearFilter.value = parts[0];
        txMonthFilter.value = parts[1];
      } else {
        txMonthFilter.value = monthStr || '';
      }
      switchTab('transactions');
    };

    const switchTab = (tab, subTab = null) => {
      triggerHaptic('light');
      if (tab === 'transactions' || tab === 'recurring') {
        currentTab.value = 'transactions';
        txSubTab.value = subTab || (tab === 'recurring' ? 'recurring' : 'list');
        window.location.hash = txSubTab.value === 'recurring' ? 'recurring' : 'transactions';
      } else if (tab === 'assets' || tab === 'accounts' || tab === 'bills' || tab === 'stocks' || tab === 'installments') {
        currentTab.value = 'assets';
        assetSubTab.value = subTab || (tab === 'assets' ? assetSubTab.value : tab);
        window.location.hash = assetSubTab.value;
      } else {
        currentTab.value = tab;
        window.location.hash = tab;
      }
      mobileMenuOpen.value = false;
      nextTick(() => {
        refreshIcons();
        if (currentTab.value === 'dashboard') {
          renderChart();
        } else if (currentTab.value === 'trends') {
          fetchAnalytics();
        }
      });
    };

    // 資料載入方法
    const fetchAccounts = async () => {
      accounts.value = await ApiService.getAccounts();
      if (accounts.value.length > 0 && !currentTx.value.account_id) {
        currentTx.value.account_id = accounts.value[0].id;
      }
      refreshIcons();
    };

    const fetchBills = async () => {
      bills.value = await ApiService.getBills();
      refreshIcons();
    };

    const fetchTransactions = async () => {
      transactions.value = await ApiService.getTransactions();
      renderChart();
      refreshIcons();
    };

    const fetchSettings = async () => {
      const data = await ApiService.getSettings();
      if (!data || typeof data !== 'object') return;
      settings.value = data;
      if (data.monthly_salary) {
        salaryInput.value = data.monthly_salary;
        settingsForm.value.monthly_salary = data.monthly_salary;
      }
      settingsForm.value.gemini_api_key = data.gemini_api_key || '';
      settingsForm.value.id_card_password = data.id_card_password || '';
      settingsForm.value.dbs_pdf_password = data.dbs_pdf_password || '';
      settingsForm.value.imap_email = data.imap_email || '';
      settingsForm.value.imap_app_password = data.imap_app_password || '';
      settingsForm.value.imap_server = data.imap_server || 'imap.gmail.com';
      settingsForm.value.google_client_id = data.google_client_id || '';
      if (data.google_redirect_uri) {
        settingsForm.value.google_redirect_uri = data.google_redirect_uri;
      }
      settingsForm.value.deduct_labor_health = Boolean(data.deduct_labor_health);
      settingsForm.value.health_insurance_dependents = Number(data.health_insurance_dependents) || 1;
      settingsForm.value.pension_rate = Number(data.pension_rate) || 0.0;
      settingsForm.value.tax_rate = Number(data.tax_rate) !== undefined ? Number(data.tax_rate) : 0.05;
      settingsForm.value.show_deductions_in_chart = data.show_deductions_in_chart !== false;
      settingsForm.value.labor_health_auto_calc = data.labor_health_auto_calc !== false;
      settingsForm.value.auto_debit_bills = Boolean(data.auto_debit_bills);
      settingsForm.value.salary_account_id = data.salary_account_id || null;
      settingsForm.value.salary_pay_day = Number(data.salary_pay_day) || 5;
      settingsForm.value.auto_salary_income = Boolean(data.auto_salary_income);
      settingsForm.value.labor_insurance_fee = Number(data.labor_insurance_fee) || 0;
      settingsForm.value.health_insurance_fee = Number(data.health_insurance_fee) || 0;
      settingsForm.value.pension_fee = Number(data.pension_fee) || 0;
      settingsForm.value.tax_fee = Number(data.tax_fee) || 0;

      if (data.webhook_token) {
        webhookToken.value = data.webhook_token;
        webhookUrl.value = window.location.origin + (data.webhook_url || `/api/webhook/apple-pay?token=${data.webhook_token}`);
      }

      renderChart();
      refreshIcons();
    };

    const updateSalary = async () => {
      if (!salaryInput.value || salaryInput.value <= 0) {
        salaryInput.value = 50000;
      }
      const payload = { monthly_salary: salaryInput.value };
      if (settings.value.labor_health_auto_calc) {
        const preview = calculateInsuranceSummary(
          salaryInput.value,
          settings.value.health_insurance_dependents || 1,
          settings.value.pension_rate || 0.0,
          settings.value.tax_rate || 0.0
        );
        payload.labor_insurance_fee = preview.labor.fee;
        payload.health_insurance_fee = preview.health.fee;
        payload.pension_fee = preview.pension.fee;
        payload.tax_fee = preview.tax.fee;
        settings.value.labor_insurance_fee = preview.labor.fee;
        settings.value.health_insurance_fee = preview.health.fee;
        settings.value.pension_fee = preview.pension.fee;
        settings.value.tax_fee = preview.tax.fee;
      }
      await ApiService.saveSettings(payload);
      renderChart();
    };

    // 帳戶管理
    const openAccountModal = (acc = null) => {
      if (acc) {
        currentAcc.value = { ...acc };
      } else {
        currentAcc.value = { name: '', account_type: 'SAVINGS', balance: 0, account_number: '', is_dbs_default_debit: accounts.value.length === 0 };
      }
      showAccountModal.value = true;
      refreshIcons();
    };

    const saveAccount = async () => {
      if (!currentAcc.value.name) return alert('請填寫帳戶名稱');
      const res = await ApiService.saveAccount(currentAcc.value);
      if (res.ok) {
        showAccountModal.value = false;
        await fetchAccounts();
        await fetchSettings();
        await fetchTransactions();
      } else {
        alert('儲存失敗');
      }
    };

    const deleteAccount = async (id) => {
      if (!confirm('確定刪除此帳戶？')) return;
      await ApiService.deleteAccount(id);
      await fetchAccounts();
      await fetchSettings();
    };

    const setDefaultDebit = async (id) => {
      await ApiService.setDefaultDebit(id);
      await fetchAccounts();
      await fetchSettings();
    };

    // 自訂常用分類管理狀態與方法
    const quickCategories = ref([...QUICK_CATEGORIES]);
    const newCategoryInput = ref('');
    const showAddCategoryInline = ref(false);
    const isManagingCategories = ref(false);

    const fetchCategories = async () => {
      try {
        const res = await ApiService.getCategories();
        if (res && Array.isArray(res.categories) && res.categories.length > 0) {
          quickCategories.value = res.categories;
          localStorage.setItem('custom_categories', JSON.stringify(res.categories));
          return;
        }
      } catch (e) {
        console.warn('載入自訂分類失敗，改用本機快取', e);
      }
      const cached = localStorage.getItem('custom_categories');
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0) {
            quickCategories.value = parsed;
            return;
          }
        } catch (_) {}
      }
      quickCategories.value = [...QUICK_CATEGORIES];
    };

    const addCustomCategory = async (catName) => {
      const name = (catName || newCategoryInput.value || '').trim();
      if (!name) return;
      if (name.length > 20) {
        alert('分類名稱請勿超過 20 個字元');
        return;
      }
      if (!quickCategories.value.includes(name)) {
        quickCategories.value.push(name);
        localStorage.setItem('custom_categories', JSON.stringify(quickCategories.value));
        try {
          await ApiService.saveCategories(quickCategories.value);
        } catch (e) {
          console.warn('同步分類至伺服器失敗', e);
        }
      }
      currentTx.value.category = name;
      newCategoryInput.value = '';
      showAddCategoryInline.value = false;
    };

    const removeCustomCategory = async (catName) => {
      if (quickCategories.value.length <= 1) {
        alert('請至少保留一個分類項目');
        return;
      }
      if (!confirm(`確定要刪除「${catName}」分類嗎？（已記錄的歷史交易不會受影響）`)) return;
      quickCategories.value = quickCategories.value.filter(c => c !== catName);
      localStorage.setItem('custom_categories', JSON.stringify(quickCategories.value));
      if (currentTx.value.category === catName) {
        currentTx.value.category = quickCategories.value[0] || '其他';
      }
      try {
        await ApiService.saveCategories(quickCategories.value);
      } catch (e) {
        console.warn('同步分類至伺服器失敗', e);
      }
    };

    const resetCategories = async () => {
      if (!confirm('確定要恢復為系統預設分類清單嗎？')) return;
      quickCategories.value = [...QUICK_CATEGORIES];
      localStorage.setItem('custom_categories', JSON.stringify(quickCategories.value));
      try {
        await ApiService.resetCategories();
      } catch (e) {
        console.warn('重設分類至伺服器失敗', e);
      }
      if (!quickCategories.value.includes(currentTx.value.category)) {
        currentTx.value.category = quickCategories.value[0] || '飲食';
      }
    };

    // 自訂分類色彩管理狀態與方法
    const customCategoryColors = ref({});

    const getCategoryColorDisplay = (cat, idx = 0) => {
      return safeCategoryColor(cat, idx, customCategoryColors.value);
    };

    const fetchCategoryColors = async () => {
      const cached = localStorage.getItem('custom_category_colors');
      if (cached) {
        try {
          const parsed = JSON.parse(cached);
          if (parsed && typeof parsed === 'object') {
            customCategoryColors.value = parsed;
          }
        } catch (_) {}
      }
      try {
        const res = await ApiService.getCategoryColors();
        if (res && res.colors && typeof res.colors === 'object') {
          customCategoryColors.value = { ...customCategoryColors.value, ...res.colors };
          localStorage.setItem('custom_category_colors', JSON.stringify(customCategoryColors.value));
        }
      } catch (e) {
        console.warn('載入自訂分類色彩失敗', e);
      }
      renderChart();
    };

    const setCategoryColor = async (catName, newColor) => {
      const name = (catName || '').trim();
      const color = (newColor || '').trim();
      if (!name || !color) return;

      customCategoryColors.value = {
        ...customCategoryColors.value,
        [name]: color
      };
      localStorage.setItem('custom_category_colors', JSON.stringify(customCategoryColors.value));
      renderChart();

      try {
        await ApiService.saveCategoryColors(customCategoryColors.value);
      } catch (e) {
        console.warn('同步分類色彩至伺服器失敗', e);
      }
    };

    const resetCategoryColors = async () => {
      if (!confirm('確定要將所有分類色彩恢復為系統預設配色嗎？')) return;
      customCategoryColors.value = {};
      localStorage.removeItem('custom_category_colors');
      renderChart();
      try {
        await ApiService.resetCategoryColors();
      } catch (e) {
        console.warn('重設分類色彩至伺服器失敗', e);
      }
    };

    // PWA 手機主畫面安裝提示管理
    const deferredPwaPrompt = ref(null);
    const canInstallPwa = ref(false);
    const isPwaInstalled = ref(
      (typeof window !== 'undefined' && window.matchMedia('(display-mode: standalone)').matches) ||
      (typeof navigator !== 'undefined' && navigator.standalone === true)
    );

    if (typeof window !== 'undefined') {
      window.addEventListener('beforeinstallprompt', (e) => {
        e.preventDefault();
        deferredPwaPrompt.value = e;
        canInstallPwa.value = true;
      });

      window.addEventListener('appinstalled', () => {
        deferredPwaPrompt.value = null;
        canInstallPwa.value = false;
        isPwaInstalled.value = true;
        console.log('[PWA] 記帳本已成功安裝至手機主畫面！');
      });
    }

    const installPwa = async () => {
      if (deferredPwaPrompt.value) {
        deferredPwaPrompt.value.prompt();
        const { outcome } = await deferredPwaPrompt.value.userChoice;
        if (outcome === 'accepted') {
          canInstallPwa.value = false;
          deferredPwaPrompt.value = null;
        }
      } else {
        const isIos = /iphone|ipad|ipod/i.test(navigator.userAgent);
        if (isIos) {
          alert('📱 加入 iPhone / iPad 主畫面步驟：\n\n1. 點擊 Safari 底部工具列中央的「分享」圖示（方形向上箭頭）\n2. 於選單中往下滑動，選擇「加入主畫面」\n3. 點擊右上角「新增」即完成！\n\n即可在手機桌面以原生 App 全螢幕體驗使用記帳本。');
        } else {
          alert('📱 請點擊瀏覽器選單（右上角或右下角 ⋮），選擇「加到主畫面」或「安裝應用程式」即可建立手機桌面捷徑！');
        }
      }
    };

    // 記帳管理 (方案 C: 極簡記帳體驗 + 簡易算式計算機)
    const showTxAdvanced = ref(false);
    const showTxCalcKeyboard = ref(false);
    const editingTxId = ref(null);
    const txAmountFormula = ref('');

    const txEvaluatedAmount = computed(() => {
      if (!txAmountFormula.value) return null;
      return evaluateMathExpression(txAmountFormula.value);
    });

    const txHasFormula = computed(() => {
      return /[+\-*/×✕÷%]/.test(txAmountFormula.value);
    });

    const applyTxFormula = () => {
      const evaluated = txEvaluatedAmount.value;
      if (evaluated !== null && !isNaN(evaluated)) {
        currentTx.value.amount = evaluated;
        txAmountFormula.value = String(evaluated);
      }
    };

    const appendTxFormulaOp = (op) => {
      if (op === '=') {
        applyTxFormula();
        return;
      }
      if (op === 'C') {
        txAmountFormula.value = '';
        currentTx.value.amount = null;
        return;
      }
      if (!txAmountFormula.value && ['+', '-', '×', '÷', '*', '/'].includes(op)) {
        txAmountFormula.value = (currentTx.value.amount || 0) + op;
      } else {
        txAmountFormula.value += op;
      }
    };

    const openTxModal = () => {
      triggerHaptic('light');
      editingTxId.value = null;
      txAmountFormula.value = '';
      const defaultAcc = accounts.value.find(a => a.is_dbs_default_debit) || accounts.value[0];
      const defaultCat = quickCategories.value[0] || '飲食';
      currentTx.value = {
        amount: null,
        tx_type: 'EXPENSE',
        account_id: defaultAcc?.id,
        target_account_id: accounts.value.find(a => a.id !== defaultAcc?.id)?.id || null,
        category: defaultCat,
        description: '',
        date: todayStr,
        affects_balance: false
      };
      showTxAdvanced.value = false;
      showTxCalcKeyboard.value = false;
      showAddCategoryInline.value = false;
      isManagingCategories.value = false;
      showTxModal.value = true;
      refreshIcons();
    };

    const openEditTxModal = (tx) => {
      editingTxId.value = tx.id;
      txAmountFormula.value = (tx.amount !== undefined && tx.amount !== null) ? String(tx.amount) : '';
      currentTx.value = {
        amount: tx.amount,
        tx_type: tx.tx_type || 'EXPENSE',
        account_id: tx.account_id,
        target_account_id: tx.target_account_id || null,
        category: tx.category || '其它',
        description: tx.description || '',
        date: tx.date ? tx.date.substring(0, 10) : todayStr,
        affects_balance: tx.affects_balance !== false,
        related_transaction_id: tx.related_transaction_id || null
      };
      // 若有自訂日期或轉帳，自動展開進階選單以方便瀏覽修改
      showTxAdvanced.value = Boolean((tx.date && tx.date.substring(0, 10) !== todayStr) || tx.tx_type === 'TRANSFER' || tx.tx_type === 'REFUND');
      showTxCalcKeyboard.value = Boolean(txHasFormula.value);
      showAddCategoryInline.value = false;
      isManagingCategories.value = false;
      showTxModal.value = true;
      refreshIcons();
    };

    const openRefundModal = (tx) => {
      editingTxId.value = null; // 建立新的關聯退款紀錄
      const refundAmt = Math.abs(tx.amount || 0);
      txAmountFormula.value = String(refundAmt);
      currentTx.value = {
        amount: refundAmt,
        tx_type: 'REFUND',
        account_id: tx.account_id,
        target_account_id: null,
        category: tx.category || '其它',
        description: tx.description ? `[退款] ${tx.description}` : '[退款] 消費刷退',
        date: todayStr,
        affects_balance: tx.affects_balance !== false,
        related_transaction_id: tx.id
      };
      showTxAdvanced.value = true;
      showAddCategoryInline.value = false;
      isManagingCategories.value = false;
      showTxModal.value = true;
      refreshIcons();
    };

    const toggleAffectsBalance = () => {
      triggerHaptic('medium');
      currentTx.value.affects_balance = !currentTx.value.affects_balance;
      refreshIcons();
    };

    const saveTx = async () => {
      // 若金額欄位包含算式，優先進行安全求值計算
      if (txEvaluatedAmount.value !== null) {
        currentTx.value.amount = txEvaluatedAmount.value;
        txAmountFormula.value = String(txEvaluatedAmount.value);
      } else if (txAmountFormula.value) {
        const parsed = parseFloat(txAmountFormula.value);
        if (!isNaN(parsed)) currentTx.value.amount = parsed;
      }

      if (!currentTx.value.amount || !currentTx.value.account_id) return alert('請填寫金額與選擇帳戶');
      if (currentTx.value.tx_type === 'TRANSFER') {
        if (!currentTx.value.target_account_id) {
          return alert('轉帳必須選擇接收（轉入）帳戶');
        }
        if (currentTx.value.account_id === currentTx.value.target_account_id) {
          return alert('來源帳戶與目標帳戶不能相同');
        }
        currentTx.value.category = '帳戶轉帳';
        if (!currentTx.value.description || !currentTx.value.description.trim()) {
          currentTx.value.description = 'ATM 提領 / 帳戶互轉';
        }
        currentTx.value.affects_balance = true;
      } else if (!currentTx.value.description || !currentTx.value.description.trim()) {
        currentTx.value.description = currentTx.value.category || '一般消費';
      }
      // 若使用者手動輸入了新的自訂分類，自動納入常用分類清單並持久化
      const customCat = (currentTx.value.category || '').trim();
      if (customCat && !quickCategories.value.includes(customCat)) {
        quickCategories.value.push(customCat);
        localStorage.setItem('custom_categories', JSON.stringify(quickCategories.value));
        ApiService.saveCategories(quickCategories.value).catch(err => console.warn('自動儲存新分類失敗', err));
      }

      let res;
      if (editingTxId.value) {
        res = await ApiService.updateTransaction(editingTxId.value, currentTx.value);
      } else {
        res = await ApiService.createTransaction(currentTx.value);
      }

      if (res && res.ok) {
        triggerHaptic('success');
        showTxModal.value = false;
        editingTxId.value = null;
        await fetchAccounts();
        await fetchTransactions();
        fetchAnalytics();
      } else {
        const err = await res?.json().catch(() => ({}));
        alert(err?.detail || '儲存交易紀錄失敗');
      }
    };

    const deleteTx = async (txId) => {
      const targetTx = (transactions.value || []).find(t => t.id === txId);
      const confirmMsg = (targetTx && !targetTx.affects_balance)
        ? '確定刪除此筆記帳明細？（此筆為純記帳，不會更動帳戶餘額）'
        : '確定刪除此筆明細？（該帳戶之餘額將會自動同步還原）';
      if (!confirm(confirmMsg)) return;
      const res = await ApiService.deleteTransaction(txId);
      if (res.ok) {
        await fetchTransactions();
        await fetchAccounts();
        await fetchBills();
        fetchAnalytics();
      } else {
        alert('刪除失敗');
      }
    };

    // 帳單操作
    const openAddBillModal = () => {
      currentBill.value = {
        id: null,
        bank_name: '星展銀行',
        statement_month: todayStr.substring(0, 7),
        due_date: todayStr,
        total_amount: 0,
        debit_account_id: accounts.value[0]?.id || null,
        status: 'PENDING'
      };
      showEditBillModal.value = true;
      refreshIcons();
    };

    const openEditBillModal = (bill) => {
      currentBill.value = { ...bill };
      showEditBillModal.value = true;
      refreshIcons();
    };

    const saveBill = async () => {
      if (!currentBill.value.due_date) return alert('請填寫繳款截止日');
      const res = await ApiService.saveBill(currentBill.value);
      if (res.ok) {
        showEditBillModal.value = false;
        await fetchBills();
      } else {
        alert('帳單儲存失敗');
      }
    };

    const deleteBill = async (billId) => {
      if (!confirm('確定刪除此筆帳單紀錄？')) return;
      const res = await ApiService.deleteBill(billId);
      if (res.ok) {
        await fetchBills();
      } else {
        alert('刪除失敗');
      }
    };

    const payBillNow = async (billId) => {
      if (!confirm('確定立即從指定帳戶扣除此筆卡費？')) return;
      const res = await ApiService.payBillNow(billId);
      const data = await res.json();
      if (res.ok) {
        alert(data.message);
        await fetchAccounts();
        await fetchBills();
        await fetchTransactions();
      } else {
        alert(data.detail || '扣款失敗');
      }
    };

    // 月底帳單對帳核銷操作
    const openReconcileModal = async (bill) => {
      reconcileBill.value = bill;
      showReconcileModal.value = true;
      reconcileLoading.value = true;
      showSettleConfirm.value = false;
      showQuickAddModal.value = false;
      reconcileTabFilter.value = 'ALL';
      reconcileAccountFilter.value = bill.credit_account_id ? String(bill.credit_account_id) : '';
      reconcileIncludeAll.value = false;
      reconcileStartDate.value = '';
      reconcileEndDate.value = '';

      settleForm.value = {
        debit_account_id: bill.debit_account_id || (accounts.value.find(a => a.account_type === 'SAVINGS')?.id) || (accounts.value[0]?.id || null),
        credit_account_id: bill.credit_account_id || null,
        settlement_mode: 'TRANSFER'
      };

      await reloadReconcileData();
      refreshIcons();
    };

    const reloadReconcileData = async () => {
      if (!reconcileBill.value) return;
      reconcileLoading.value = true;
      try {
        const data = await ApiService.getBillReconciliation(reconcileBill.value.id, {
          credit_account_id: reconcileAccountFilter.value || undefined,
          start_date: reconcileStartDate.value || undefined,
          end_date: reconcileEndDate.value || undefined,
          include_all: reconcileIncludeAll.value
        });
        if (data) {
          reconcileData.value = data;
          if (data.statement_start_date) {
            reconcileStartDate.value = String(data.statement_start_date).substring(0, 10);
          }
          if (data.statement_end_date) {
            reconcileEndDate.value = String(data.statement_end_date).substring(0, 10);
          } else if (data.statement_date) {
            reconcileEndDate.value = String(data.statement_date).substring(0, 10);
          } else if (data.due_date) {
            reconcileEndDate.value = String(data.due_date).substring(0, 10);
          }
          if (!settleForm.value.credit_account_id && data.credit_account_id) {
            settleForm.value.credit_account_id = data.credit_account_id;
          }
          if (!reconcileAccountFilter.value && data.credit_account_id) {
            reconcileAccountFilter.value = String(data.credit_account_id);
          }

          const sel = new Set();
          (data.transactions || []).forEach(t => {
            if (t.is_reconciled || t.bill_id === reconcileBill.value.id) {
              sel.add(t.id);
            }
          });
          reconcileSelectedIds.value = sel;
        }
      } catch (err) {
        console.error('載入對帳資料失敗:', err);
      } finally {
        reconcileLoading.value = false;
        refreshIcons();
      }
    };

    const expandReconcileRange = (days = 60) => {
      const today = new Date();
      const past = new Date(today);
      past.setDate(today.getDate() - days);
      reconcileStartDate.value = past.toISOString().substring(0, 10);
      reconcileEndDate.value = today.toISOString().substring(0, 10);
      reconcileIncludeAll.value = true;
      reconcileAccountFilter.value = '';
      reloadReconcileData();
    };

    const expandReconcileToDueDate = () => {
      if (!reconcileData.value) return;
      if (reconcileData.value.due_date) {
        reconcileEndDate.value = String(reconcileData.value.due_date).substring(0, 10);
      }
      reconcileIncludeAll.value = true;
      reloadReconcileData();
    };

    const toggleReconcileTx = (txId) => {
      const sel = new Set(reconcileSelectedIds.value);
      if (sel.has(txId)) {
        sel.delete(txId);
      } else {
        sel.add(txId);
      }
      reconcileSelectedIds.value = sel;
    };

    const toggleReconcileSelectAll = () => {
      if (!reconcileData.value || !reconcileData.value.transactions) return;
      const allTxIds = reconcileData.value.transactions.map(t => t.id);
      const isAllSelected = allTxIds.length > 0 && allTxIds.every(id => reconcileSelectedIds.value.has(id));
      const sel = new Set(reconcileSelectedIds.value);
      if (isAllSelected) {
        allTxIds.forEach(id => sel.delete(id));
      } else {
        allTxIds.forEach(id => sel.add(id));
      }
      reconcileSelectedIds.value = sel;
    };

    const saveReconcileProgress = async () => {
      if (!reconcileBill.value || !reconcileData.value) return;
      isSavingReconcile.value = true;
      try {
        const checkedIds = Array.from(reconcileSelectedIds.value);
        const allIds = (reconcileData.value.transactions || []).map(t => t.id);
        const uncheckedIds = allIds.filter(id => !reconcileSelectedIds.value.has(id));

        if (checkedIds.length > 0) {
          await ApiService.checkBillTransactions(reconcileBill.value.id, checkedIds, true);
        }
        if (uncheckedIds.length > 0) {
          await ApiService.checkBillTransactions(reconcileBill.value.id, uncheckedIds, false);
        }
        alert('已成功儲存對帳進度！');
        await reloadReconcileData();
        await fetchTransactions();
      } catch (err) {
        alert('儲存進度失敗: ' + err.message);
      } finally {
        isSavingReconcile.value = false;
      }
    };

    const openQuickAddModal = () => {
      const todayStr = new Date().toISOString().substring(0, 10);
      quickAddForm.value = {
        date: reconcileEndDate.value || todayStr,
        category: '日常採買',
        description: '',
        amount: Math.max(0, currentReconcileDiff.value) || 0,
        tx_type: 'EXPENSE',
        credit_account_id: settleForm.value.credit_account_id || (reconcileAccountFilter.value ? Number(reconcileAccountFilter.value) : null)
      };
      showQuickAddModal.value = true;
      refreshIcons();
    };

    const submitQuickAddTx = async () => {
      if (!quickAddForm.value.amount || quickAddForm.value.amount <= 0) return alert('請填寫有效金額');
      if (!quickAddForm.value.description) return alert('請填寫店家或消費說明');
      try {
        const res = await ApiService.quickAddBillTx(reconcileBill.value.id, quickAddForm.value);
        if (res.status === 'success') {
          showQuickAddModal.value = false;
          await reloadReconcileData();
          await fetchAccounts();
          await fetchTransactions();
        } else {
          alert('補登失敗: ' + (res.detail || '未知錯誤'));
        }
      } catch (err) {
        alert('補登失敗: ' + err.message);
      }
    };

    const submitSettleAndPay = async () => {
      if (!settleForm.value.debit_account_id) return alert('請選擇扣款帳戶');
      const diff = currentReconcileDiff.value;
      let confirmMsg = `確定立即扣款 NT$ ${formatMoney(reconcileBill.value.total_amount)} 並完成此期帳單對帳核銷？`;
      if (Math.abs(diff) > 0.01) {
        confirmMsg = `⚠️ 提醒：目前對帳差額尚有 NT$ ${formatMoney(diff)}，未完全吻合！\n\n您確定仍要強制核銷並扣繳此期帳單嗎？`;
      }
      if (!confirm(confirmMsg)) return;

      isSettlingReconcile.value = true;
      try {
        const payload = {
          debit_account_id: settleForm.value.debit_account_id,
          credit_account_id: settleForm.value.credit_account_id,
          reconciled_transaction_ids: Array.from(reconcileSelectedIds.value),
          settlement_mode: settleForm.value.settlement_mode
        };
        const res = await ApiService.settleAndClearBill(reconcileBill.value.id, payload);
        if (res.status === 'success') {
          alert(res.message);
          showReconcileModal.value = false;
          await fetchBills();
          await fetchAccounts();
          await fetchTransactions();
        } else {
          alert('結算失敗: ' + (res.detail || '未知錯誤'));
        }
      } catch (err) {
        alert('結算失敗: ' + err.message);
      } finally {
        isSettlingReconcile.value = false;
      }
    };

    // 檔案選取監聽
    const onFilesSelected = (e) => {
      const files = e?.target?.files || documentInput.value?.files;
      selectedFilesCount.value = files ? files.length : 0;
    };

    const openUploadModal = () => {
      showUploadModal.value = true;
      nextTick(() => refreshIcons());
    };

    const openQuickActionSheet = () => {
      triggerHaptic('light');
      showQuickActionSheet.value = true;
      nextTick(() => refreshIcons());
    };

    // AI 智慧單據辨識上傳（支援多選、批次排隊處理）
    const submitParseDocument = async () => {
      if (!settings.value?.has_gemini_api_key) {
        alert('⚠️ 尚未設定 Gemini API Key！\n\n系統單據辨識已全面改由純 AI 智能驅動，請先至【設定】填入免費申請的 Gemini API Key。');
        showUploadModal.value = false;
        openSettingsModal();
        setSettingsTab('account');
        return;
      }

      const files = documentInput.value?.files;
      if (!files || files.length === 0) return alert('請先選擇 PDF 或圖片檔案');

      uploading.value = true;
      const defaultAccId = accounts.value.find(a => a.is_dbs_default_debit)?.id || accounts.value[0]?.id || null;

      // 若僅選取 1 個檔案，走單筆預覽確認流程
      if (files.length === 1) {
        const file = files[0];
        batchProgress.value = { current: 1, total: 1, currentFileName: file.name };
        const formData = new FormData();
        formData.append('file', file);
        if (uploadPwd.value) formData.append('password', uploadPwd.value);

        try {
          const res = await ApiService.parseDocument(formData);
          const data = await res.json();
          if (res.ok && data.success) {
            parsedData.value = {
              document_type: data.document_type || 'EXPENSE_RECEIPT',
              bank_or_company: data.bank_or_company || '消費支出',
              statement_month: data.statement_month || todayStr.substring(0, 7),
              total_amount: data.total_amount || 0,
              due_date: data.due_date || data.statement_date || todayStr,
              category: data.category || '其他',
              description: data.description || (data.bank_or_company ? `${data.bank_or_company} 消費` : '日常消費'),
              debit_account_id: defaultAccId,
              confidence_summary: data.confidence_summary || '',
              record_salary_tx: true,
              salary_account_id: defaultAccId,
              pdf_filename: file.name,
              currency: data.currency || 'TWD',
              original_amount: data.original_amount !== undefined ? data.original_amount : (data.total_amount || 0),
              exchange_rate: data.exchange_rate || 1.0
            };
            showUploadModal.value = false;
            showParseResultModal.value = true;
            refreshIcons();
          } else {
            alert(`辨識失敗: ${data.detail || data.error || '無法辨識內容'}`);
          }
        } catch (e) {
          alert('辨識過程發生錯誤: ' + e);
        } finally {
          uploading.value = false;
          refreshIcons();
        }
        return;
      }

      // 多筆檔案：自動排隊逐一向 Gemini API 辨識
      batchParsedList.value = [];
      const totalFiles = files.length;

      for (let i = 0; i < totalFiles; i++) {
        const file = files[i];
        batchProgress.value = {
          current: i + 1,
          total: totalFiles,
          currentFileName: file.name
        };

        const formData = new FormData();
        formData.append('file', file);
        if (uploadPwd.value) formData.append('password', uploadPwd.value);

        try {
          const res = await ApiService.parseDocument(formData);
          const data = await res.json();
          if (res.ok && data.success) {
            batchParsedList.value.push({
              id: Date.now() + Math.random(),
              selected: true,
              filename: file.name,
              document_type: data.document_type || 'EXPENSE_RECEIPT',
              bank_or_company: data.bank_or_company || '消費支出',
              statement_month: data.statement_month || todayStr.substring(0, 7),
              date: data.due_date || data.statement_date || todayStr,
              category: data.category || '其他',
              description: data.description || (data.bank_or_company ? `${data.bank_or_company} 消費` : '日常消費'),
              total_amount: data.total_amount || 0,
              original_amount: data.original_amount !== undefined ? data.original_amount : (data.total_amount || 0),
              currency: data.currency || 'TWD',
              exchange_rate: data.exchange_rate || 1.0,
              account_id: defaultAccId,
              minimum_amount: data.minimum_amount || 0,
              notes: data.notes || data.confidence_summary || '',
              error: null
            });
          } else {
            batchParsedList.value.push({
              id: Date.now() + Math.random(),
              selected: false,
              filename: file.name,
              document_type: 'EXPENSE_RECEIPT',
              bank_or_company: '未知商家',
              statement_month: todayStr.substring(0, 7),
              date: todayStr,
              category: '其他',
              description: file.name,
              total_amount: 0,
              original_amount: 0,
              currency: 'TWD',
              exchange_rate: 1.0,
              account_id: defaultAccId,
              minimum_amount: 0,
              notes: '',
              error: data.detail || data.error || '辨識失敗'
            });
          }
        } catch (err) {
          batchParsedList.value.push({
            id: Date.now() + Math.random(),
            selected: false,
            filename: file.name,
            document_type: 'EXPENSE_RECEIPT',
            bank_or_company: '未知商家',
            statement_month: todayStr.substring(0, 7),
            date: todayStr,
            category: '其他',
            description: file.name,
            total_amount: 0,
            original_amount: 0,
            currency: 'TWD',
            exchange_rate: 1.0,
            account_id: defaultAccId,
            minimum_amount: 0,
            notes: '',
            error: '連線或處理失敗: ' + err
          });
        }
      }

      uploading.value = false;
      showUploadModal.value = false;
      showBatchResultModal.value = true;
      refreshIcons();
    };

    // 批次結果輔助操作
    const toggleBatchSelectAll = (checked) => {
      batchParsedList.value.forEach(item => {
        if (!item.error) {
          item.selected = checked;
        }
      });
    };

    const removeBatchItem = (index) => {
      batchParsedList.value.splice(index, 1);
      if (batchParsedList.value.length === 0) {
        showBatchResultModal.value = false;
      }
    };

    const selectedBatchCount = computed(() => {
      return batchParsedList.value.filter(item => item.selected).length;
    });

    const totalSelectedBatchAmount = computed(() => {
      return batchParsedList.value
        .filter(item => item.selected)
        .reduce((sum, item) => sum + (Number(item.total_amount) || 0), 0);
    });

    // 批次確認寫入後端資料庫
    const confirmBatchSave = async () => {
      const itemsToSave = batchParsedList.value.filter(item => item.selected);
      if (itemsToSave.length === 0) {
        return alert('請至少勾選一筆要儲存的單據');
      }

      isSavingBatch.value = true;
      try {
        const payload = {
          items: itemsToSave.map(item => ({
            document_type: item.document_type,
            bank_or_company: item.bank_or_company,
            statement_month: item.statement_month,
            date: item.date,
            category: item.category || '其他',
            description: item.description,
            total_amount: Number(item.total_amount) || 0,
            original_amount: Number(item.original_amount) || Number(item.total_amount) || 0,
            currency: item.currency || 'TWD',
            exchange_rate: Number(item.exchange_rate) || 1.0,
            account_id: item.account_id,
            minimum_amount: Number(item.minimum_amount) || 0,
            notes: item.notes
          }))
        };

        const res = await ApiService.batchSave(payload);
        if (res.saved_count > 0) {
          let msg = `🎉 批次存入完成！成功儲存 ${res.saved_count} 筆單據`;
          if (res.failed_count > 0) {
            msg += `，有 ${res.failed_count} 筆失敗`;
          }
          alert(msg);
          showBatchResultModal.value = false;
          batchParsedList.value = [];
          await fetchAccounts();
          await fetchTransactions();
          await fetchBills();
          await fetchSettings();
        } else {
          alert(`批次儲存未成功: ${res.results?.[0]?.message || '請檢查明細'}`);
        }
      } catch (err) {
        alert('批次儲存過程發生錯誤: ' + err);
      } finally {
        isSavingBatch.value = false;
        refreshIcons();
      }
    };

    // 單筆單據確認寫入
    const confirmApplyParsedData = async () => {
      if (parsedData.value.document_type === 'SALARY_SLIP') {
        const res = await ApiService.applySalary({
          salary_amount: parsedData.value.total_amount,
          statement_month: parsedData.value.statement_month,
          company_name: parsedData.value.bank_or_company,
          record_transaction: parsedData.value.record_salary_tx,
          account_id: parsedData.value.salary_account_id
        });
        const data = await res.json();
        if (res.ok) {
          alert(data.message);
          showParseResultModal.value = false;
          await fetchSettings();
          await fetchAccounts();
          await fetchTransactions();
        } else {
          alert(data.detail || '套用失敗');
        }
      } else if (parsedData.value.document_type === 'CREDIT_CARD_BILL') {
        const res = await ApiService.saveBill({
          bank_name: parsedData.value.bank_or_company,
          statement_month: parsedData.value.statement_month,
          due_date: parsedData.value.due_date,
          total_amount: parsedData.value.total_amount,
          pdf_filename: parsedData.value.pdf_filename,
          debit_account_id: parsedData.value.debit_account_id
        });
        if (res.ok) {
          alert('🎉 信用卡帳單已成功存入！');
          showParseResultModal.value = false;
          await fetchBills();
        } else {
          alert('儲存帳單失敗');
        }
      } else {
        // EXPENSE_RECEIPT 或其他日常消費
        const res = await ApiService.batchSave({
          items: [{
            document_type: 'EXPENSE_RECEIPT',
            bank_or_company: parsedData.value.bank_or_company,
            statement_month: parsedData.value.statement_month,
            date: parsedData.value.due_date,
            category: parsedData.value.category || '其他',
            description: parsedData.value.description,
            total_amount: parsedData.value.total_amount,
            original_amount: parsedData.value.original_amount,
            currency: parsedData.value.currency,
            exchange_rate: parsedData.value.exchange_rate,
            account_id: parsedData.value.debit_account_id,
            notes: parsedData.value.confidence_summary
          }]
        });
        if (res.saved_count > 0) {
          alert('🎉 收據支出明細已成功記錄！');
          showParseResultModal.value = false;
          await fetchAccounts();
          await fetchTransactions();
        } else {
          alert(`記錄失敗: ${res.results?.[0]?.message || '請確認帳戶餘額'}`);
        }
      }
    };

    // Gmail 同步與自動扣款檢驗
    const syncGmail = async () => {
      syncing.value = true;
      try {
        const data = await ApiService.syncGmail();
        if (data.status === 'success') {
          if (data.imported_count > 0) {
            alert(`同步完成！成功抓取 ${data.imported_count} 筆新帳單`);
          } else {
            alert('信箱同步完成：收件匣中暫無未匯入的新信用卡帳單');
          }
          await fetchBills();
        } else if (data.status === 'skipped') {
          alert(`同步提示: ${data.message}`);
        } else {
          alert(`同步提示: ${data.message || '無新帳單'}`);
        }
      } catch (e) {
        alert('同步發生錯誤: ' + (e.message || e));
      } finally {
        syncing.value = false;
        refreshIcons();
      }
    };

    const triggerDebitCheck = async () => {
      const data = await ApiService.triggerAutoDebit();
      alert(`扣款檢驗完成！已自動完成 ${data.paid_count} 筆扣款`);
      await fetchAccounts();
      await fetchBills();
      await fetchTransactions();
    };

    // ==========================================
    // AI 智慧財務顧問 (CFP 買房/購車/支出分析)
    // ==========================================

    const cleanAdvisorLatex = (raw) => {
      if (!raw) return '';
      let text = raw.replace(/\$\$/g, '');
      text = text.replace(/\\\$/g, '$').replace(/\\%/g, '%');
      for (let i = 0; i < 3; i++) {
        text = text.replace(/\\text\{([^{}]+)\}/g, '$1');
        text = text.replace(/\\mathbf\{([^{}]+)\}/g, '**$1**');
        text = text.replace(/\\mathit\{([^{}]+)\}/g, '*$1*');
      }
      text = text.replace(/\\frac\{([^{}]+)\}\{([^{}]+)\}/g, '($1 ÷ $2)');
      text = text.replace(/\\times/g, '×')
                 .replace(/\\approx/g, '≈')
                 .replace(/\\leq?/g, '≤')
                 .replace(/\\geq?/g, '≥')
                 .replace(/\\cdot/g, '·')
                 .replace(/\\div/g, '÷')
                 .replace(/\\pm/g, '±')
                 .replace(/\\sim/g, '約')
                 .replace(/\\infty/g, '無限');
      text = text.replace(/\\([a-zA-Z]+)/g, '');
      return text;
    };

    const formatAdvisorMarkdown = (md) => {
      if (!md) return '';
      // 先行清理可能殘留的 LaTeX 符號
      md = cleanAdvisorLatex(md);

      // HTML 跳脫防 XSS
      let html = md
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');

      // 標題樣式
      html = html.replace(/^### (.*$)/gim, '<h4 class="font-bold text-slate-800 dark:text-slate-100 text-sm mt-3 mb-1.5 flex items-center"><span class="w-1.5 h-3.5 bg-indigo-600 dark:bg-indigo-400 rounded-full mr-1.5 inline-block flex-shrink-0"></span>$1</h4>');
      html = html.replace(/^## (.*$)/gim, '<h3 class="font-extrabold text-slate-900 dark:text-white text-base mt-4 mb-2 flex items-center"><span class="w-2 h-4 bg-purple-600 rounded-full mr-2 inline-block flex-shrink-0"></span>$1</h3>');
      html = html.replace(/^# (.*$)/gim, '<h2 class="font-extrabold text-slate-900 dark:text-white text-lg mt-4 mb-2">$1</h2>');

      // 粗體與斜體
      html = html.replace(/\*\*(.*?)\*\*/g, '<strong class="font-bold text-indigo-700 dark:text-indigo-300">$1</strong>');
      html = html.replace(/\*(.*?)\*/g, '<em class="text-slate-700 dark:text-slate-300">$1</em>');

      // 水平分隔線
      html = html.replace(/^---$/gim, '<hr class="my-3 border-slate-200 dark:border-slate-700" />');

      // 逐行處理清單與段落
      const lines = html.split('\n');
      const result = [];
      let inUl = false;
      let inOl = false;

      for (let line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
          if (!inUl) {
            if (inOl) { result.push('</ol>'); inOl = false; }
            result.push('<ul class="my-1.5 space-y-1 pl-1">');
            inUl = true;
          }
          result.push(`<li class="text-xs leading-relaxed text-slate-700 dark:text-slate-200 list-disc ml-3.5">${trimmed.substring(2)}</li>`);
        } else if (/^\d+\.\s+/.test(trimmed)) {
          if (!inOl) {
            if (inUl) { result.push('</ul>'); inUl = false; }
            result.push('<ol class="my-1.5 space-y-1 pl-1">');
            inOl = true;
          }
          const content = trimmed.replace(/^\d+\.\s+/, '');
          result.push(`<li class="text-xs leading-relaxed text-slate-700 dark:text-slate-200 list-decimal ml-3.5">${content}</li>`);
        } else {
          if (inUl) { result.push('</ul>'); inUl = false; }
          if (inOl) { result.push('</ol>'); inOl = false; }
          if (trimmed === '') {
            result.push('<div class="h-2"></div>');
          } else if (!trimmed.startsWith('<h') && !trimmed.startsWith('<hr')) {
            result.push(`<p class="text-xs leading-relaxed text-slate-700 dark:text-slate-200 my-1">${trimmed}</p>`);
          } else {
            result.push(line);
          }
        }
      }
      if (inUl) result.push('</ul>');
      if (inOl) result.push('</ol>');

      return result.join('\n');
    };

    const scrollAdvisorChatToBottom = () => {
      nextTick(() => {
        const container = document.getElementById('advisor-chat-messages');
        if (container) {
          container.scrollTop = container.scrollHeight;
        }
      });
    };

    const loadAdvisorSnapshot = async () => {
      try {
        const snap = await ApiService.getAdvisorSnapshot();
        if (snap) {
          advisorSnapshot.value = snap;
        }
      } catch (e) {
        console.warn('載入財務快照失敗:', e);
      }
    };

    const openAdvisorModal = (presetQuestion = null) => {
      triggerHaptic('light');
      // 確保關閉所有手機抽屜與浮動選單，避免層級干擾
      showQuickActionSheet.value = false;
      mobileMenuOpen.value = false;

      showAdvisorModal.value = true;
      loadAdvisorSnapshot();

      if (advisorChat.value.length === 0) {
        const isCourage = (currentTheme && currentTheme.value === 'courage');
        const welcomeText = isCourage
          ? '🖥️ **[閣樓老電腦 The Attic Computer v1.0.4]**\n\n「嗶嗶... 愚蠢的狗！你又帶著財務難題跑上無名小鎮閣樓啦？\n\n別慌！本電腦已即時連線你的**真實帳戶存款、實領收入、股票投資與信用卡分期**，為你進行專業精準的買房、買車與財務防護試算！\n\n點選下方快捷情境，或直接輸入你的疑問，本電腦馬上為你解答！」'
          : '👋 您好！我是您的 **AI 智慧理財顧問**。\n\n我會依據您在記帳系統中的**真實收支、各帳戶存款餘額、股票投資、固定常態扣款與分期明細**進行全方位量化試算，為您量身打造貼近真實財務狀況的買房、買車、收支診斷與預備金建議。\n\n您可以直接點選下方的常見問題情境範例，或在下方輸入框輸入您的財務問題！';

        advisorChat.value.push({
          id: 'welcome',
          role: 'assistant',
          content: welcomeText,
          formattedHtml: formatAdvisorMarkdown(welcomeText),
          timestamp: new Date()
        });
      }

      if (presetQuestion) {
        advisorQuestion.value = presetQuestion;
      }

      nextTick(() => {
        refreshIcons();
        scrollAdvisorChatToBottom();
      });
    };

    const askAdvisorQuestion = async (presetText = null) => {
      if (presetText) {
        advisorQuestion.value = presetText;
      }
      const q = (advisorQuestion.value || '').trim();
      if (!q) return;

      if (!settings.value?.has_gemini_api_key) {
        alert('⚠️ 尚未設定 Gemini API Key！\n\nAI 財務顧問需透過您的個人 Gemini API Key 進行連線分析。請先至【設定】填入免費申請的 Gemini API Key。');
        showAdvisorModal.value = false;
        openSettingsModal();
        setSettingsTab('account');
        return;
      }

      triggerHaptic('light');

      // 使用者提問泡泡
      const userMsg = {
        id: Date.now(),
        role: 'user',
        content: q,
        formattedHtml: q.replace(/\n/g, '<br>'),
        timestamp: new Date()
      };
      advisorChat.value.push(userMsg);
      advisorQuestion.value = '';
      advisorLoading.value = true;
      scrollAdvisorChatToBottom();

      // 取近期對話紀錄作為上下文
      const history = advisorChat.value
        .filter(m => m.id !== 'welcome' && !m.isError)
        .slice(-6)
        .map(m => ({ role: m.role, content: m.content }));

      const isCourage = currentTheme.value === 'courage';

      try {
        const res = await ApiService.askAdvisor(q, history, isCourage);
        if (res && res.snapshot) {
          advisorSnapshot.value = res.snapshot;
        }
        advisorChat.value.push({
          id: Date.now() + 1,
          role: 'assistant',
          content: res.advice,
          formattedHtml: formatAdvisorMarkdown(res.advice),
          timestamp: new Date()
        });
      } catch (err) {
        advisorChat.value.push({
          id: Date.now() + 1,
          role: 'assistant',
          content: '⚠️ 諮詢失敗：' + (err.message || '無法取得 AI 顧問回應，請檢查網路或 Gemini API Key 設定。'),
          formattedHtml: '<div class="text-rose-600 dark:text-rose-400 font-semibold text-xs">⚠️ 諮詢失敗：' + (err.message || '無法取得 AI 顧問回應') + '</div>',
          isError: true,
          timestamp: new Date()
        });
      } finally {
        advisorLoading.value = false;
        refreshIcons();
        scrollAdvisorChatToBottom();
      }
    };

    const copyAdvisorResponse = (msg) => {
      if (!msg || !msg.content) return;
      navigator.clipboard.writeText(msg.content);
      advisorCopiedId.value = msg.id;
      triggerHaptic('light');
      setTimeout(() => {
        if (advisorCopiedId.value === msg.id) {
          advisorCopiedId.value = null;
        }
      }, 2500);
    };

    const clearAdvisorChat = () => {
      advisorChat.value = [];
      const welcomeText = currentTheme.value === 'courage'
        ? '🖥️ **[閣樓老電腦 The Attic Computer]**\n\n「嗶... 對話記憶已清除。愚蠢的狗，有新的財務疑問就趕緊輸入吧！」'
        : '👋 對話已清空。您可以直接點選下方的常見問題範例，或輸入新的理財疑問！';
      advisorChat.value.push({
        id: 'welcome',
        role: 'assistant',
        content: welcomeText,
        formattedHtml: formatAdvisorMarkdown(welcomeText),
        timestamp: new Date()
      });
      refreshIcons();
    };

    // 股票與投資資產管理
    const fetchStocks = async () => {
      try {
        const res = await ApiService.getStocks();
        if (res.ok) {
          stockPortfolio.value = await res.json();
          refreshIcons();
        }
      } catch (e) {
        console.error('Fetch stocks failed:', e);
      }
    };

    const openAddStockModal = () => {
      currentStock.value = {
        id: null,
        symbol: '',
        name: '',
        shares: null,
        cost_price: null,
        currency: '',
        notes: ''
      };
      showStockModal.value = true;
      refreshIcons();
    };

    const openEditStockModal = (s) => {
      currentStock.value = { ...s };
      showStockModal.value = true;
      refreshIcons();
    };

    const saveStock = async () => {
      if (!currentStock.value.symbol || !currentStock.value.shares || !currentStock.value.cost_price) {
        return alert('請填寫股票代號、持有股數與買入成本均價');
      }
      savingStock.value = true;
      try {
        const res = await ApiService.saveStock(currentStock.value);
        if (res.ok) {
          showStockModal.value = false;
          await fetchStocks();
        } else {
          const err = await res.json();
          alert(err.detail || '儲存持股失敗');
        }
      } catch (e) {
        alert('操作失敗: ' + e);
      } finally {
        savingStock.value = false;
        refreshIcons();
      }
    };

    const deleteStock = async (stockId) => {
      if (!confirm('確定刪除此檔持股紀錄？')) return;
      const res = await ApiService.deleteStock(stockId);
      if (res.ok) {
        await fetchStocks();
      } else {
        alert('刪除失敗');
      }
    };

    const refreshStockQuotes = async () => {
      refreshingStocks.value = true;
      try {
        const data = await ApiService.refreshStockQuotes();
        await fetchStocks();
        alert(data.message || '股價更新成功！');
      } catch (e) {
        alert('更新股價發生錯誤: ' + e);
      } finally {
        refreshingStocks.value = false;
        refreshIcons();
      }
    };

    // 每月固定花費管理
    const fetchRecurringExpenses = async () => {
      try {
        const res = await ApiService.getRecurringExpenses();
        if (res.ok) {
          recurringExpenses.value = await res.json();
          refreshIcons();
          renderChart();
        }
      } catch (e) {
        console.error('Fetch recurring expenses failed:', e);
      }
    };

    // 固定花費金額簡易算式計算機狀態
    const recurringAmountFormula = ref('');

    const recurringEvaluatedAmount = computed(() => {
      if (!recurringAmountFormula.value) return null;
      return evaluateMathExpression(recurringAmountFormula.value);
    });

    const recurringHasFormula = computed(() => {
      return /[+\-*/×✕÷%]/.test(recurringAmountFormula.value);
    });

    const applyRecurringFormula = () => {
      const evaluated = recurringEvaluatedAmount.value;
      if (evaluated !== null && !isNaN(evaluated)) {
        currentRecurring.value.amount = evaluated;
        recurringAmountFormula.value = String(evaluated);
      }
    };

    const appendRecurringFormulaOp = (op) => {
      if (op === '=') {
        applyRecurringFormula();
        return;
      }
      if (op === 'C') {
        recurringAmountFormula.value = '';
        currentRecurring.value.amount = null;
        return;
      }
      if (!recurringAmountFormula.value && ['+', '-', '×', '÷', '*', '/'].includes(op)) {
        recurringAmountFormula.value = (currentRecurring.value.amount || 0) + op;
      } else {
        recurringAmountFormula.value += op;
      }
    };

    const openAddRecurringModal = () => {
      recurringAmountFormula.value = '';
      currentRecurring.value = {
        id: null,
        name: '',
        amount: null,
        category: '保險',
        frequency: 'MONTHLY',
        due_month: new Date().getMonth() + 1,
        due_day: null,
        account_id: accounts.value[0]?.id || null,
        auto_debit: false,
        is_active: true,
        notes: ''
      };
      showRecurringModal.value = true;
      refreshIcons();
    };

    const openEditRecurringModal = (item) => {
      recurringAmountFormula.value = (item.amount !== undefined && item.amount !== null) ? String(item.amount) : '';
      currentRecurring.value = {
        ...item,
        account_id: item.account_id || accounts.value[0]?.id || null,
        auto_debit: !!item.auto_debit,
        frequency: item.frequency || 'MONTHLY',
        due_month: item.due_month || (new Date().getMonth() + 1)
      };
      showRecurringModal.value = true;
      refreshIcons();
    };

    const saveRecurring = async () => {
      // 若金額欄位包含算式，優先進行安全求值
      if (recurringEvaluatedAmount.value !== null) {
        currentRecurring.value.amount = recurringEvaluatedAmount.value;
        recurringAmountFormula.value = String(recurringEvaluatedAmount.value);
      } else if (recurringAmountFormula.value) {
        const parsed = parseFloat(recurringAmountFormula.value);
        if (!isNaN(parsed)) currentRecurring.value.amount = parsed;
      }

      if (!currentRecurring.value.name || !currentRecurring.value.amount) {
        return alert('請填寫固定花費項目名稱與金額');
      }
      savingRecurring.value = true;
      try {
        const res = await ApiService.saveRecurring(currentRecurring.value);
        if (res.ok) {
          showRecurringModal.value = false;
          await Promise.all([
            fetchRecurringExpenses(),
            fetchAccounts(),
            fetchTransactions(),
            fetchAnalytics()
          ]);
        } else {
          const err = await res.json();
          alert(err.detail || '儲存失敗');
        }
      } catch (e) {
        alert('操作失敗: ' + e);
      } finally {
        savingRecurring.value = false;
        refreshIcons();
      }
    };

    const deleteRecurring = async (id) => {
      if (!confirm('確定刪除此筆固定開銷項目？')) return;
      const res = await ApiService.deleteRecurring(id);
      if (res.ok) {
        await fetchRecurringExpenses();
      } else {
        alert('刪除失敗');
      }
    };

    const chargeRecurring = async (item) => {
      if (!confirm(`確定立即為【${item.name}】扣款記帳 NT$ ${formatMoney(item.amount)} 嗎？`)) return;
      try {
        const res = await ApiService.chargeRecurring(item.id);
        if (res && res.status === 'success') {
          alert(res.message);
          await Promise.all([
            fetchRecurringExpenses(),
            fetchAccounts(),
            fetchTransactions(),
            fetchAnalytics()
          ]);
        } else {
          alert((res && res.detail) || (res && res.message) || '扣款失敗');
        }
      } catch (e) {
        alert('扣款操作失敗: ' + e);
      } finally {
        refreshIcons();
      }
    };

    // 信用卡分期付款管理
    const computedInstallmentPreview = computed(() => {
      const total = Number(currentInstallment.value.total_amount) || 0;
      const periods = Number(currentInstallment.value.total_periods) || 1;
      if (total <= 0 || periods <= 0) return { monthly: 0, first: 0 };
      const monthly = Math.floor(total / periods);
      const remainder = total % periods;
      const first = monthly + remainder;
      return { monthly, first };
    });

    const fetchInstallments = async (status = installmentFilterStatus.value) => {
      try {
        const queryStatus = status === 'ALL' ? '' : status;
        const data = await ApiService.getInstallments(queryStatus);
        installments.value = Array.isArray(data) ? data : [];
      } catch (err) {
        console.error('載入分期付款清單失敗:', err);
      } finally {
        refreshIcons();
      }
    };

    const fetchInstallmentSummary = async () => {
      try {
        const data = await ApiService.getInstallmentSummary(12);
        installmentSummary.value = data;
      } catch (err) {
        console.error('載入分期彙總資訊失敗:', err);
      }
    };

    const filterInstallments = async (status) => {
      installmentFilterStatus.value = status;
      await fetchInstallments(status);
    };

    const openAddInstallmentModal = () => {
      currentInstallment.value = {
        id: null,
        name: '',
        total_amount: null,
        total_periods: 3,
        current_period: 0,
        monthly_amount: null,
        first_amount: null,
        interest_rate: 0,
        monthly_fee: 0,
        category: '購物',
        account_id: accounts.value.length > 0 ? accounts.value[0].id : null,
        start_date: todayStr,
        billing_day: new Date().getDate(),
        status: 'ACTIVE',
        notes: '',
        auto_record: false,
        record_first_period: false
      };
      showInstallmentModal.value = true;
      refreshIcons();
    };

    const openEditInstallmentModal = (plan) => {
      currentInstallment.value = {
        id: plan.id,
        name: plan.name,
        total_amount: plan.total_amount,
        total_periods: plan.total_periods,
        current_period: plan.current_period,
        monthly_amount: plan.monthly_amount,
        first_amount: plan.first_amount,
        interest_rate: plan.interest_rate || 0,
        monthly_fee: plan.monthly_fee || 0,
        category: plan.category || '購物',
        account_id: plan.account_id,
        start_date: plan.start_date || todayStr,
        billing_day: plan.billing_day || 1,
        status: plan.status || 'ACTIVE',
        notes: plan.notes || '',
        auto_record: !!plan.auto_record,
        record_first_period: false
      };
      showInstallmentModal.value = true;
      refreshIcons();
    };

    const saveInstallmentPlan = async () => {
      if (!currentInstallment.value.name || !currentInstallment.value.name.trim()) {
        alert('請填寫分期計畫名稱');
        return;
      }
      const totalAmt = Number(currentInstallment.value.total_amount);
      if (isNaN(totalAmt) || totalAmt <= 0) {
        alert('請填寫正確的總分期金額（需大於 0）');
        return;
      }
      const periods = Number(currentInstallment.value.total_periods);
      if (isNaN(periods) || periods < 1) {
        alert('總分期期數至少須為 1 期');
        return;
      }

      savingInstallment.value = true;
      try {
        const payload = {
          name: currentInstallment.value.name.trim(),
          total_amount: totalAmt,
          total_periods: periods,
          current_period: Number(currentInstallment.value.current_period) || 0,
          interest_rate: Number(currentInstallment.value.interest_rate) || 0,
          monthly_fee: Number(currentInstallment.value.monthly_fee) || 0,
          category: currentInstallment.value.category || '購物',
          account_id: currentInstallment.value.account_id ? Number(currentInstallment.value.account_id) : null,
          start_date: currentInstallment.value.start_date || todayStr,
          billing_day: Number(currentInstallment.value.billing_day) || 1,
          status: currentInstallment.value.status || 'ACTIVE',
          notes: currentInstallment.value.notes || '',
          auto_record: !!currentInstallment.value.auto_record
        };

        if (!currentInstallment.value.id) {
          payload.record_first_period = !!currentInstallment.value.record_first_period;
        }

        const res = await ApiService.saveInstallment({
          id: currentInstallment.value.id,
          ...payload
        });

        if (res && res.id) {
          showInstallmentModal.value = false;
          await Promise.all([
            fetchInstallments(),
            fetchInstallmentSummary(),
            fetchTransactions(),
            fetchAccounts(),
            fetchAnalytics()
          ]);
        } else {
          alert((res && (res.detail || res.message)) || '儲存失敗');
        }
      } catch (err) {
        alert('儲存分期計畫出錯: ' + err.message);
      } finally {
        savingInstallment.value = false;
        refreshIcons();
      }
    };

    const deleteInstallmentPlan = async (plan) => {
      const confirmMsg = `確定刪除分期計畫【${plan.name}】嗎？\n\n點擊「確定」僅刪除分期計畫（保留已產生的流水帳紀錄）。`;
      if (!confirm(confirmMsg)) return;

      try {
        const res = await ApiService.deleteInstallment(plan.id, false);
        if (res && res.status === 'success') {
          if (showInstallmentDetailModal.value && selectedPlanDetail.value?.id === plan.id) {
            showInstallmentDetailModal.value = false;
          }
          await Promise.all([
            fetchInstallments(),
            fetchInstallmentSummary(),
            fetchTransactions(),
            fetchAccounts()
          ]);
        } else {
          alert((res && res.detail) || '刪除失敗');
        }
      } catch (err) {
        alert('刪除分期計畫出錯: ' + err.message);
      } finally {
        refreshIcons();
      }
    };

    const openInstallmentDetailModal = async (plan) => {
      showInstallmentDetailModal.value = true;
      loadingPlanDetail.value = true;
      selectedPlanDetail.value = null;
      try {
        const detail = await ApiService.getInstallmentDetail(plan.id);
        selectedPlanDetail.value = detail;
      } catch (err) {
        alert('載入分期攤提日程失敗: ' + err.message);
      } finally {
        loadingPlanDetail.value = false;
        refreshIcons();
      }
    };

    const chargeNextInstallmentPeriod = async (plan, period = null) => {
      const targetP = period || (plan.current_period + 1);
      const isFirst = targetP === 1;
      const amt = isFirst ? plan.first_amount : plan.monthly_amount;
      const confirmMsg = `確定要為【${plan.name}】扣繳第 ${targetP} 期款項 (NT$ ${formatMoney(amt)}) 嗎？\n\n系統將自動建立一筆支出交易並扣減對應帳戶餘額。`;
      if (!confirm(confirmMsg)) return;

      chargingInstallment.value = true;
      try {
        const res = await ApiService.chargeNextInstallmentPeriod(plan.id, period);
        if (res && res.status === 'success') {
          alert(res.message);
          await Promise.all([
            fetchInstallments(),
            fetchInstallmentSummary(),
            fetchTransactions(),
            fetchAccounts(),
            fetchAnalytics()
          ]);
          if (showInstallmentDetailModal.value && selectedPlanDetail.value?.id === plan.id) {
            await openInstallmentDetailModal(plan);
          }
        } else {
          alert((res && (res.detail || res.message)) || '扣繳失敗');
        }
      } catch (err) {
        alert('扣繳出錯: ' + err.message);
      } finally {
        chargingInstallment.value = false;
        refreshIcons();
      }
    };

    const settleInstallmentInFull = async (plan) => {
      const remainingAmt = plan.remaining_amount || 0;
      const confirmMsg = `確定要為【${plan.name}】提前全額結清剩餘分期嗎？\n\n剩餘待結清金額：NT$ ${formatMoney(remainingAmt)}\n系統將產生一筆全額結清支出交易，並將本分期計畫標記為已結清。`;
      if (!confirm(confirmMsg)) return;

      chargingInstallment.value = true;
      try {
        const res = await ApiService.settleInstallmentInFull(plan.id);
        if (res && res.status === 'success') {
          alert(res.message);
          await Promise.all([
            fetchInstallments(),
            fetchInstallmentSummary(),
            fetchTransactions(),
            fetchAccounts(),
            fetchAnalytics()
          ]);
          if (showInstallmentDetailModal.value && selectedPlanDetail.value?.id === plan.id) {
            await openInstallmentDetailModal(plan);
          }
        } else {
          alert((res && (res.detail || res.message)) || '結清失敗');
        }
      } catch (err) {
        alert('提前結清出錯: ' + err.message);
      } finally {
        chargingInstallment.value = false;
        refreshIcons();
      }
    };

    // 系統設定
    const openSettingsModal = () => {
      imapTestResult.value = null;
      webhookTestResult.value = null;
      if (settings.value && settings.value.webhook_token) {
        webhookToken.value = settings.value.webhook_token;
        webhookUrl.value = window.location.origin + (settings.value.webhook_url || `/api/webhook/apple-pay?token=${settings.value.webhook_token}`);
      }
      fetchWebhookToken();
      profileForm.value = {
        display_name: currentUser.value?.display_name || currentUser.value?.username || '',
        current_password: '',
        new_password: ''
      };
      settingsForm.value.monthly_salary = settings.value.monthly_salary || 50000;
      settingsForm.value.deduct_labor_health = Boolean(settings.value.deduct_labor_health);
      settingsForm.value.health_insurance_dependents = Number(settings.value.health_insurance_dependents) || 1;
      settingsForm.value.pension_rate = Number(settings.value.pension_rate) || 0.0;
      settingsForm.value.tax_rate = Number(settings.value.tax_rate) !== undefined ? Number(settings.value.tax_rate) : 0.05;
      settingsForm.value.show_deductions_in_chart = settings.value.show_deductions_in_chart !== false;
      settingsForm.value.labor_health_auto_calc = settings.value.labor_health_auto_calc !== false;
      settingsForm.value.labor_insurance_fee = Number(settings.value.labor_insurance_fee) || 0;
      settingsForm.value.health_insurance_fee = Number(settings.value.health_insurance_fee) || 0;
      settingsForm.value.pension_fee = Number(settings.value.pension_fee) || 0;
      settingsForm.value.tax_fee = Number(settings.value.tax_fee) || 0;
      if (settingsForm.value.labor_health_auto_calc) {
        onInsuranceSettingChange();
      }
      settingsForm.value.gemini_api_key = settings.value.gemini_api_key || '';
      settingsForm.value.id_card_password = settings.value.id_card_password || '';
      settingsForm.value.dbs_pdf_password = settings.value.dbs_pdf_password || '';
      settingsForm.value.imap_email = settings.value.imap_email || '';
      settingsForm.value.imap_app_password = settings.value.imap_app_password || '';
      settingsForm.value.imap_server = settings.value.imap_server || 'imap.gmail.com';
      settingsForm.value.google_client_id = settings.value.google_client_id || '';
      if (settings.value.google_redirect_uri) {
        settingsForm.value.google_redirect_uri = settings.value.google_redirect_uri;
      }
      settingsForm.value.auto_debit_bills = Boolean(settings.value.auto_debit_bills);
      settingsForm.value.salary_account_id = settings.value.salary_account_id || (accounts.value.find(a => a.account_type === 'SAVINGS')?.id || null);
      settingsForm.value.salary_pay_day = Number(settings.value.salary_pay_day) || 5;
      settingsForm.value.auto_salary_income = Boolean(settings.value.auto_salary_income);
      settingsTab.value = 'salary';
      showSettingsModal.value = true;
      nextTick(() => refreshIcons());
    };

    const setSettingsTab = (tab) => {
      settingsTab.value = tab;
      nextTick(() => refreshIcons());
    };

    const saveSettings = async () => {
      if (settingsForm.value.labor_health_auto_calc) {
        const preview = settingsInsurancePreview.value;
        settingsForm.value.labor_insurance_fee = preview.labor.fee;
        settingsForm.value.health_insurance_fee = preview.health.fee;
        settingsForm.value.pension_fee = preview.pension.fee;
        settingsForm.value.tax_fee = preview.tax.fee;
      }
      const res = await ApiService.saveSettings(settingsForm.value);
      if (res.ok) {
        alert('設定儲存成功！');
        showSettingsModal.value = false;
        await fetchSettings();
        await fetchTransactions();
        await fetchAccounts();
      }
    };

    const testImapConnection = async () => {
      testingImap.value = true;
      imapTestResult.value = null;
      try {
        const res = await ApiService.testImap({
          imap_email: settingsForm.value.imap_email,
          imap_app_password: settingsForm.value.imap_app_password,
          imap_server: settingsForm.value.imap_server
        });
        const data = await res.json();
        if (res.ok) {
          imapTestResult.value = { success: true, message: data.message };
        } else {
          imapTestResult.value = { success: false, message: data.detail || '連線測試失敗' };
        }
      } catch (e) {
        imapTestResult.value = { success: false, message: '連線發生錯誤，請檢查網路或設定' };
      } finally {
        testingImap.value = false;
        refreshIcons();
      }
    };

    const updateUserProfile = async () => {
      try {
        const res = await ApiService.updateProfile(profileForm.value);
        const data = await res.json();
        if (res.ok) {
          currentUser.value = data;
          AuthStorage.setUser(data);
          profileForm.value.current_password = '';
          profileForm.value.new_password = '';
          alert('個人資料與密碼已更新！');
        } else {
          alert(data.detail || '更新失敗');
        }
      } catch (e) {
        alert('更新發生錯誤');
      }
    };

    const connectGoogle = async () => {
      await saveSettings();
      try {
        const data = await ApiService.getGoogleAuthUrl(settingsForm.value.google_redirect_uri);
        if (data.auth_url) {
          window.location.href = data.auth_url;
        } else {
          alert(data.detail || '取得授權網址失敗，請先確認 Google Client ID 設定');
        }
      } catch (e) {
        alert('請先填寫正確的 Google Client ID 與 Client Secret');
      }
    };

    const fetchWebhookToken = async () => {
      try {
        const data = await ApiService.getWebhookToken();
        if (data && data.webhook_token) {
          webhookToken.value = data.webhook_token;
          webhookUrl.value = window.location.origin + data.webhook_url;
        }
      } catch (e) {
        console.warn('載入 Webhook Token 失敗:', e);
      }
    };

    const regenerateWebhook = async () => {
      if (!confirm('確定要重新生成 Webhook 金鑰嗎？\n生成後舊金鑰將立即失效，需同步更新 iPhone 捷徑中的網址。')) {
        return;
      }
      try {
        const data = await ApiService.regenerateWebhookToken();
        if (data && data.webhook_token) {
          webhookToken.value = data.webhook_token;
          webhookUrl.value = window.location.origin + data.webhook_url;
          alert('Webhook 金鑰已重新生成！請記得更新 iPhone 捷徑中的網址。');
        }
      } catch (e) {
        alert('重新生成金鑰失敗，請稍後再試');
      }
    };

    const copyWebhookUrl = async () => {
      if (!webhookUrl.value) {
        if (settings.value && settings.value.webhook_token) {
          webhookUrl.value = window.location.origin + (settings.value.webhook_url || `/api/webhook/apple-pay?token=${settings.value.webhook_token}`);
        } else {
          await fetchWebhookToken();
        }
      }
      if (!webhookUrl.value) {
        alert('尚未取得 Webhook 網址，請點擊右上方「重新生成金鑰」試試！');
        return;
      }
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          await navigator.clipboard.writeText(webhookUrl.value);
        } else {
          const textarea = document.createElement('textarea');
          textarea.value = webhookUrl.value;
          document.body.appendChild(textarea);
          textarea.select();
          document.execCommand('copy');
          document.body.removeChild(textarea);
        }
        webhookCopySuccess.value = true;
        setTimeout(() => {
          webhookCopySuccess.value = false;
        }, 2500);
      } catch (e) {
        alert('複製失敗，請手動選取網址複製');
      }
    };

    const runWebhookTest = async () => {
      testingWebhook.value = true;
      webhookTestResult.value = null;
      try {
        const res = await ApiService.testWebhookTransaction({
          amount: 65,
          merchant: "星巴克咖啡 (測試交易)",
          category: "飲食",
          note: "Apple Pay 捷徑測試"
        });
        webhookTestResult.value = {
          success: true,
          message: `測試成功！已自動建立 NT$ ${res.amount} 支出，記入【${res.account_name}】，餘額更新為 NT$ ${Number(res.account_balance).toLocaleString()}`
        };
        await fetchTransactions();
        await fetchAccounts();
      } catch (err) {
        webhookTestResult.value = {
          success: false,
          message: err.message || '測試記帳失敗，請確認伺服器日誌'
        };
      } finally {
        testingWebhook.value = false;
        refreshIcons();
      }
    };

    const loadAllUserData = async () => {
      await Promise.all([
        fetchAccounts(),
        fetchBills(),
        fetchTransactions(),
        fetchStocks(),
        fetchRecurringExpenses(),
        fetchInstallments(),
        fetchInstallmentSummary(),
        fetchSettings(),
        fetchCategories(),
        fetchCategoryColors(),
        fetchWebhookToken()
      ]);
      refreshIcons();
    };

    const submitAuth = async () => {
      authError.value = '';
      const uname = (authForm.value.username || '').trim();
      const pwd = authForm.value.password || '';
      if (!uname || !pwd) {
        authError.value = '請輸入帳號與密碼';
        return;
      }

      authLoading.value = true;
      try {
        let res;
        if (authMode.value === 'register') {
          res = await ApiService.register(uname, pwd, authForm.value.display_name);
        } else {
          res = await ApiService.login(uname, pwd);
        }
        const data = await res.json();
        if (!res.ok) {
          authError.value = data.detail || '驗證失敗，請檢查帳號密碼';
          return;
        }
        AuthStorage.setToken(data.access_token);
        AuthStorage.setUser(data.user);
        currentUser.value = data.user;
        isAuthenticated.value = true;
        authForm.value = { username: '', password: '', display_name: '' };
        await loadAllUserData();
      } catch (e) {
        authError.value = '伺服器連線失敗，請稍後再試';
      } finally {
        authLoading.value = false;
        refreshIcons();
      }
    };

    const logout = () => {
      AuthStorage.clear();
      isAuthenticated.value = false;
      currentUser.value = null;
      showSettingsModal.value = false;
      accounts.value = [];
      bills.value = [];
      transactions.value = [];
      stockPortfolio.value = {
        total_market_value_twd: 0,
        total_cost_twd: 0,
        total_unrealized_pnl_twd: 0,
        total_return_rate: 0,
        usd_to_twd_rate: 32.0,
        holdings: []
      };
      recurringExpenses.value = {
        total_monthly_amount: 0,
        charged_count: 0,
        pending_count: 0,
        items: []
      };
      refreshIcons();
    };

    AuthStorage.onUnauthorized(() => {
      logout();
    });

    onMounted(async () => {
      // 載入公開資安配置（如是否開放註冊）
      ApiService.getAuthConfig().then(cfg => {
        if (cfg && typeof cfg.allow_registration === 'boolean') {
          allowRegistration.value = cfg.allow_registration;
        }
      }).catch(() => {});

      loadDashboardLayout();
      const hash = window.location.hash.replace('#', '');
      const validTabs = ['dashboard', 'transactions', 'recurring', 'bills', 'stocks', 'accounts', 'assets', 'installments', 'trends'];
      if (validTabs.includes(hash)) {
        switchTab(hash);
      }
      window.addEventListener('hashchange', () => {
        const h = window.location.hash.replace('#', '');
        if (validTabs.includes(h)) {
          switchTab(h);
        }
      });

      fetchCategories();
      fetchCategoryColors();
      if (AuthStorage.getToken()) {
        try {
          const meRes = await ApiService.getMe();
          if (meRes.ok) {
            const meData = await meRes.json();
            currentUser.value = meData;
            AuthStorage.setUser(meData);
            isAuthenticated.value = true;
            await loadAllUserData();
            if (currentTab.value === 'trends') {
              fetchAnalytics();
            }
          } else {
            logout();
          }
        } catch {
          logout();
        }
      } else {
        refreshIcons();
      }

      const urlParams = new URLSearchParams(window.location.search);
      if (urlParams.get('auth') === 'success' && isAuthenticated.value) {
        alert('🎉 Google 帳號授權成功！');
        window.history.replaceState({}, document.title, window.location.pathname);
        await fetchSettings();
        await fetchTransactions();
        await fetchAccounts();
      }

      // 📱 手機多工切回 / 解鎖螢幕 / 視窗獲得焦點時，自動靜默更新最新流水帳與餘額 (Apple Pay 刷完切回立即可見)
      let lastAutoRefreshTime = 0;
      const autoRefreshOnActive = async () => {
        if (!isAuthenticated.value) return;
        const now = Date.now();
        if (now - lastAutoRefreshTime < 2500) return; // 避免 2.5 秒內重複觸發
        lastAutoRefreshTime = now;
        try {
          await Promise.all([
            fetchTransactions(),
            fetchAccounts()
          ]);
          refreshIcons();
        } catch (e) {
          console.debug('[AutoRefresh] 靜默同步略過:', e);
        }
      };

      document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
          autoRefreshOnActive();
        }
      });

      window.addEventListener('focus', () => {
        autoRefreshOnActive();
      });

      // 前景每 20 秒輕量靜默檢查一次 (若手機一直停在 App 畫面中，刷卡完數秒內自動出現)
      setInterval(() => {
        if (document.visibilityState === 'visible' && isAuthenticated.value) {
          autoRefreshOnActive();
        }
      }, 20000);
    });

    return {
      isAuthenticated, currentUser, authMode, allowRegistration, authLoading, authError, authForm,
      submitAuth, logout, testingImap, imapTestResult, testImapConnection,
      profileForm, updateUserProfile,
      accounts, bills, transactions, settings, salaryInput, currentMonth, selectedMonth,
      syncing, uploading, showAccountModal, showTxModal, showUploadModal, showQuickActionSheet, openQuickActionSheet, showParseResultModal,
      showBatchResultModal, isSavingBatch, selectedFilesCount, batchProgress, batchParsedList,
      onFilesSelected, toggleBatchSelectAll, removeBatchItem, selectedBatchCount, totalSelectedBatchAmount, confirmBatchSave,
      showEditBillModal, showSettingsModal, settingsTab, setSettingsTab, uploadPwd, documentInput, currentAcc, currentTx,
      currentBill, parsedData, settingsForm,
      showAdvisorModal, advisorLoading, advisorQuestion, advisorChat, advisorSnapshot, advisorCopiedId,
      openAdvisorModal, loadAdvisorSnapshot, askAdvisorQuestion, copyAdvisorResponse, clearAdvisorChat,
      showReconcileModal, reconcileLoading, reconcileBill, reconcileData, reconcileAccountFilter,
      reconcileStartDate, reconcileEndDate, reconcileIncludeAll, reconcileTabFilter, reconcileSelectedIds,
      isSavingReconcile, isSettlingReconcile, showQuickAddModal, quickAddForm, showSettleConfirm, settleForm,
      filteredReconcileTxList, currentReconcileCheckedAmount, currentReconcileDiff, isCurrentReconcileBalanced,
      openReconcileModal, reloadReconcileData, toggleReconcileTx, toggleReconcileSelectAll, saveReconcileProgress,
      openQuickAddModal, submitQuickAddTx, submitSettleAndPay, expandReconcileRange, expandReconcileToDueDate,
      quickCategories, newCategoryInput, showAddCategoryInline, isManagingCategories,
      addCustomCategory, removeCustomCategory, resetCategories,
      customCategoryColors, getCategoryColorDisplay, setCategoryColor, resetCategoryColors,
      stockPortfolio, showStockModal, refreshingStocks, savingStock, currentStock,
      recurringExpenses, showRecurringModal, savingRecurring, currentRecurring,
      installments, installmentSummary, installmentFilterStatus, showInstallmentModal, showInstallmentDetailModal,
      savingInstallment, chargingInstallment, currentInstallment, selectedPlanDetail, loadingPlanDetail,
      computedInstallmentPreview, fetchInstallments, fetchInstallmentSummary, filterInstallments,
      openAddInstallmentModal, openEditInstallmentModal, saveInstallmentPlan, deleteInstallmentPlan,
      openInstallmentDetailModal, chargeNextInstallmentPeriod, settleInstallmentInFull,
      canInstallPwa, isPwaInstalled, installPwa,
      webhookToken, webhookUrl, webhookCopySuccess, webhookTutorialOpen, testingWebhook, webhookTestResult,
      fetchWebhookToken, regenerateWebhook, copyWebhookUrl, runWebhookTest,
      txAmountFormula, txEvaluatedAmount, txHasFormula, applyTxFormula, appendTxFormulaOp,
      recurringAmountFormula, recurringEvaluatedAmount, recurringHasFormula, applyRecurringFormula, appendRecurringFormulaOp,
      totalSavings, totalNetWorth, pendingBillAmount, nextDueBill, monthlyExpensesList, monthlyTotalExpense, monthlyLivingExpense,
      expenseRatio, remainingSalary, freeBudget, isDeductionsInChart, chartBaseSalary,
      effectiveSalary, totalInsuranceDeduction, settingsInsurancePreview, onInsuranceSettingChange, resetToAutoInsuranceFees,
      formatMoney, formatStockPrice, formatStockShares, formatStockTotal, getAccountName, isDueSoon,
      openAccountModal, saveAccount, deleteAccount, setDefaultDebit,
      openTxModal, openEditTxModal, openRefundModal, editingTxId, saveTx, deleteTx, toggleAffectsBalance, refreshIcons, openAddBillModal, openEditBillModal, saveBill, deleteBill,
      openAddStockModal, openEditStockModal, saveStock, deleteStock, refreshStockQuotes,
      openAddRecurringModal, openEditRecurringModal, saveRecurring, deleteRecurring, chargeRecurring,
      openUploadModal, submitParseDocument, confirmApplyParsedData,
      syncGmail, triggerDebitCheck, payBillNow,
      openSettingsModal, saveSettings, connectGoogle, updateSalary, renderChart,
      chartViewMode, setChartViewMode, monthlyRecordedIncome, monthlyIncomesList,
      currentTab, mobileMenuOpen, currentTabTitle, switchTab, txSubTab, assetSubTab, showTxAdvanced, showTxCalcKeyboard,
      txSearch, txTypeFilter, txYearFilter, txMonthFilter, availableTxYears, setTxCurrentMonth, prevTxMonth, nextTxMonth, clearTxDateFilter, filteredTransactions, groupedTransactionsByDate, txStats, recentTransactions,
      triggerHaptic,
      hideAssets, toggleHideAssets,
      isDarkMode, toggleDarkMode,
      currentTheme, setTheme, toggleTheme,
      analyticsRange, analyticsChartMode, analyticsData, loadingAnalytics,
      fetchAnalytics, setAnalyticsRange, setAnalyticsChartMode, jumpToTransactionsMonth,
      isEditingLayout, dashboardBlockOrder, kpiCardsOrder, draggedBlockIndex, dragOverBlockIndex,
      getBlockTitle, toggleEditLayout, resetDashboardLayout, moveBlockUp, moveBlockDown,
      moveKpiCardLeft, moveKpiCardRight, onBlockDragStart, onBlockDragOver, onBlockDrop, onBlockDragEnd
    };
  }
}).mount('#app');


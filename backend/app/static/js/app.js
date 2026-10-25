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
} from './formatters.js?v=2.5.0';
import { ApiService, AuthStorage } from './api.js?v=2.5.0';
import { renderExpenseDoughnutChart, renderMonthlyTrendChart } from './chart.js?v=2.5.0';
import {
  calculateLaborInsurance,
  calculateHealthInsurance,
  calculateInsuranceSummary
} from './insurance.js?v=2.5.0';

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

const { createApp, ref, computed, onMounted, nextTick } = window.Vue;

createApp({
  setup() {
    // 認證與多使用者狀態
    const isAuthenticated = ref(Boolean(AuthStorage.getToken()));
    const currentUser = ref(AuthStorage.getUser());
    const authMode = ref('login'); // 'login' | 'register'
    const authLoading = ref(false);
    const authError = ref('');
    const authForm = ref({
      username: '',
      password: '',
      display_name: ''
    });
    const testingImap = ref(false);
    const imapTestResult = ref(null);
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

    const toggleDarkMode = () => {
      isDarkMode.value = !isDarkMode.value;
      if (isDarkMode.value) {
        document.documentElement.classList.add('dark');
        localStorage.setItem('theme', 'dark');
      } else {
        document.documentElement.classList.remove('dark');
        localStorage.setItem('theme', 'light');
      }
      refreshIcons();
      renderChart();
      if (typeof renderTrendChart === 'function') {
        renderTrendChart();
      }
    };

    const currentTabTitle = computed(() => {
      switch (currentTab.value) {
        case 'dashboard': return '總覽儀表板';
        case 'transactions':
          return txSubTab.value === 'recurring' ? '固定開銷規劃' : '收支記帳流水帳';
        case 'assets':
          if (assetSubTab.value === 'bills') return '信用卡帳單總覽';
          if (assetSubTab.value === 'stocks') return '美股證券投資';
          return '各帳戶存款資產';
        case 'trends': return '收支與存款趨勢報表';
        default: return '總覽儀表板';
      }
    });

    const getAccountName = (accId) => {
      const acc = accounts.value.find(a => a.id === accId);
      return acc ? acc.name : '';
    };

    // 流水帳專屬搜尋與篩選
    const txSearch = ref('');
    const txTypeFilter = ref('ALL');
    const txMonthFilter = ref('');

    const filteredTransactions = computed(() => {
      return (transactions.value || []).filter(tx => {
        if (txTypeFilter.value !== 'ALL' && tx.tx_type !== txTypeFilter.value) {
          return false;
        }
        if (txMonthFilter.value) {
          const txMonth = (tx.date || '').substring(0, 7);
          if (txMonth !== txMonthFilter.value) {
            return false;
          }
        }
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

    const txStats = computed(() => {
      let exp = 0;
      let inc = 0;
      filteredTransactions.value.forEach(t => {
        if (t.tx_type === 'EXPENSE') exp += (t.amount || 0);
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
    const showParseResultModal = ref(false);
    const showEditBillModal = ref(false);
    const showSettingsModal = ref(false);

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
      labor_health_auto_calc: true
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
      txMonthFilter.value = monthStr;
      switchTab('transactions');
    };

    const switchTab = (tab, subTab = null) => {
      if (tab === 'transactions' || tab === 'recurring') {
        currentTab.value = 'transactions';
        txSubTab.value = subTab || (tab === 'recurring' ? 'recurring' : 'list');
        window.location.hash = txSubTab.value === 'recurring' ? 'recurring' : 'transactions';
      } else if (tab === 'assets' || tab === 'accounts' || tab === 'bills' || tab === 'stocks') {
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
      settingsForm.value.labor_insurance_fee = Number(data.labor_insurance_fee) || 0;
      settingsForm.value.health_insurance_fee = Number(data.health_insurance_fee) || 0;
      settingsForm.value.pension_fee = Number(data.pension_fee) || 0;
      settingsForm.value.tax_fee = Number(data.tax_fee) || 0;

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
        affects_balance: tx.affects_balance !== false
      };
      // 若有填寫備註、自訂日期或轉帳，自動展開進階選單以方便瀏覽修改
      showTxAdvanced.value = Boolean(tx.description || (tx.date && tx.date.substring(0, 10) !== todayStr) || tx.tx_type === 'TRANSFER');
      showAddCategoryInline.value = false;
      isManagingCategories.value = false;
      showTxModal.value = true;
      refreshIcons();
    };

    const toggleAffectsBalance = () => {
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

    // 檔案選取監聽
    const onFilesSelected = (e) => {
      const files = e?.target?.files || documentInput.value?.files;
      selectedFilesCount.value = files ? files.length : 0;
    };

    // AI 智慧單據辨識上傳（支援多選、批次排隊處理）
    const submitParseDocument = async () => {
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
          await fetchRecurringExpenses();
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

    // 系統設定
    const openSettingsModal = () => {
      imapTestResult.value = null;
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
      showSettingsModal.value = true;
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

    const loadAllUserData = async () => {
      await Promise.all([
        fetchAccounts(),
        fetchBills(),
        fetchTransactions(),
        fetchStocks(),
        fetchRecurringExpenses(),
        fetchSettings(),
        fetchCategories(),
        fetchCategoryColors()
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
      const hash = window.location.hash.replace('#', '');
      const validTabs = ['dashboard', 'transactions', 'recurring', 'bills', 'stocks', 'accounts', 'assets', 'trends'];
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
      }
    });

    return {
      isAuthenticated, currentUser, authMode, authLoading, authError, authForm,
      submitAuth, logout, testingImap, imapTestResult, testImapConnection,
      profileForm, updateUserProfile,
      accounts, bills, transactions, settings, salaryInput, currentMonth, selectedMonth,
      syncing, uploading, showAccountModal, showTxModal, showUploadModal, showParseResultModal,
      showBatchResultModal, isSavingBatch, selectedFilesCount, batchProgress, batchParsedList,
      onFilesSelected, toggleBatchSelectAll, removeBatchItem, selectedBatchCount, totalSelectedBatchAmount, confirmBatchSave,
      showEditBillModal, showSettingsModal, uploadPwd, documentInput, currentAcc, currentTx,
      currentBill, parsedData, settingsForm,
      quickCategories, newCategoryInput, showAddCategoryInline, isManagingCategories,
      addCustomCategory, removeCustomCategory, resetCategories,
      customCategoryColors, getCategoryColorDisplay, setCategoryColor, resetCategoryColors,
      stockPortfolio, showStockModal, refreshingStocks, savingStock, currentStock,
      recurringExpenses, showRecurringModal, savingRecurring, currentRecurring,
      canInstallPwa, isPwaInstalled, installPwa,
      txAmountFormula, txEvaluatedAmount, txHasFormula, applyTxFormula, appendTxFormulaOp,
      recurringAmountFormula, recurringEvaluatedAmount, recurringHasFormula, applyRecurringFormula, appendRecurringFormulaOp,
      totalSavings, totalNetWorth, pendingBillAmount, nextDueBill, monthlyExpensesList, monthlyTotalExpense, monthlyLivingExpense,
      expenseRatio, remainingSalary, freeBudget, isDeductionsInChart, chartBaseSalary,
      effectiveSalary, totalInsuranceDeduction, settingsInsurancePreview, onInsuranceSettingChange, resetToAutoInsuranceFees,
      formatMoney, formatStockPrice, formatStockShares, formatStockTotal, getAccountName, isDueSoon,
      openAccountModal, saveAccount, deleteAccount, setDefaultDebit,
      openTxModal, openEditTxModal, editingTxId, saveTx, deleteTx, toggleAffectsBalance, refreshIcons, openAddBillModal, openEditBillModal, saveBill, deleteBill,
      openAddStockModal, openEditStockModal, saveStock, deleteStock, refreshStockQuotes,
      openAddRecurringModal, openEditRecurringModal, saveRecurring, deleteRecurring,
      submitParseDocument, confirmApplyParsedData,
      syncGmail, triggerDebitCheck, payBillNow,
      openSettingsModal, saveSettings, connectGoogle, updateSalary, renderChart,
      chartViewMode, setChartViewMode, monthlyRecordedIncome, monthlyIncomesList,
      currentTab, mobileMenuOpen, currentTabTitle, switchTab, txSubTab, assetSubTab, showTxAdvanced,
      txSearch, txTypeFilter, txMonthFilter, filteredTransactions, txStats, recentTransactions,
      hideAssets, toggleHideAssets,
      isDarkMode, toggleDarkMode,
      analyticsRange, analyticsChartMode, analyticsData, loadingAnalytics,
      fetchAnalytics, setAnalyticsRange, setAnalyticsChartMode, jumpToTransactionsMonth
    };
  }
}).mount('#app');


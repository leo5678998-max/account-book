/**
 * 數值與日期格式化工具模組 (Pure Functions & Constants)
 */

export const QUICK_CATEGORIES = [
  '飲食', '房租水電', '交通', '日常採買', '娛樂休閒', '保險醫療', '信用卡費', '投資', '薪資收入', '其他'
];

export const CHART_PALETTE = [
  '#6366F1', '#EC4899', '#F59E0B', '#0EA5E9', '#3B82F6',
  '#8B5CF6', '#14B8A6', '#F97316', '#64748B', '#06B6D4'
];

/**
 * 核心分類語意配色映射表
 * 確保「投資」具有醒目的尊爵紫羅蘭色 (#8B5CF6)，與「結餘儲蓄」的翡翠綠 (#10B981) 形成強烈鮮明對比
 */
export const CATEGORY_COLORS = {
  '投資': '#8B5CF6',       // 尊爵紫羅蘭 (專屬投資理財，與結餘儲蓄徹底區隔)
  '飲食': '#F59E0B',       // 暖橙黃 (餐飲美食)
  '居住': '#3B82F6',       // 穩健經典藍 (房租管理)
  '房租水電': '#3B82F6',   // 穩健經典藍
  '交通': '#06B6D4',       // 青藍 (通勤交通)
  '電信網路': '#0284C7',   // 天空藍 (通訊網路)
  '娛樂': '#EC4899',       // 活力莓果粉 (休閒娛樂)
  '娛樂休閒': '#EC4899',   // 活力莓果粉
  '日常採買': '#F97316',   // 珊瑚橘 (日常購物)
  '日常購物': '#F97316',   // 珊瑚橘
  '保險': '#14B8A6',       // 蒂芬妮綠 (保險醫療)
  '保險醫療': '#14B8A6',
  '保險費': '#14B8A6',
  '稅務': '#E11D48',       // 沉穩深紅 (政府稅賦)
  '孝親': '#D946EF',       // 溫馨品粉 (孝親費用)
  '貸款': '#64748B',       // 岩灰藍 (貸款分期)
  '信用卡費': '#6366F1',   // 經典靛藍 (卡費支出)
  '薪資收入': '#10B981',   // 翡翠綠 (正向收入入帳)
  '其他': '#94A3B8'        // 柔和淺灰 (其它雜支)
};

/**
 * 依分類名稱取得專屬配色，包含模糊關鍵字辨識與安全備援輪替色
 */
export const getCategoryColor = (category, index = 0) => {
  if (!category) return CHART_PALETTE[index % CHART_PALETTE.length];
  const catTrim = String(category).trim();
  if (CATEGORY_COLORS[catTrim]) {
    return CATEGORY_COLORS[catTrim];
  }
  // 關鍵字比對：投資/理財/基金/ETF/股票皆強制套用專屬紫色，避免與結餘儲蓄撞色
  if (catTrim.includes('投資') || catTrim.includes('理財') || catTrim.includes('基金') || catTrim.includes('ETF') || catTrim.includes('股票')) {
    return '#8B5CF6';
  }
  return CHART_PALETTE[index % CHART_PALETTE.length];
};

export const formatMoney = (val) => {
  if (val === undefined || val === null || isNaN(val)) return '0';
  return Math.round(val).toLocaleString('en-US');
};

// 股票均價與現價：固定保留 2 位小數 (如 87.83, 653.40, 2,274.24)
export const formatStockPrice = (val) => {
  if (val === undefined || val === null || isNaN(val)) return '0.00';
  const num = Number(val);
  return num.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  });
};

// 股數格式化：整數顯示整數 (如 1,000)，零股/碎股則完整保留至多 6 位小數 (如 0.95509)
export const formatStockShares = (val) => {
  if (val === undefined || val === null || isNaN(val)) return '0';
  const num = Number(val);
  return num.toLocaleString('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6
  });
};

// 市值與損益：美股固定 2 位小數，台股若有小數保留 2 位，整數則顯示整數
export const formatStockTotal = (val, currency = 'TWD') => {
  if (val === undefined || val === null || isNaN(val)) return '0';
  const num = Number(val);
  if (currency === 'USD') {
    return num.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    });
  }
  return Number.isInteger(num)
    ? num.toLocaleString('en-US')
    : num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

export const isDueSoon = (dueDateStr) => {
  if (!dueDateStr) return false;
  const due = new Date(dueDateStr);
  const now = new Date();
  const diffDays = (due - now) / (1000 * 60 * 60 * 24);
  return diffDays >= 0 && diffDays <= 5;
};


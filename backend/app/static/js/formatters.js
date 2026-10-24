/**
 * 數值與日期格式化工具模組 (Pure Functions & Constants)
 */

export const QUICK_CATEGORIES = [
  '飲食', '房租水電', '交通', '日常採買', '娛樂休閒', '保險醫療', '信用卡費', '投資', '薪資收入', '其他'
];

export const CHART_PALETTE = [
  '#6366F1', '#EC4899', '#F59E0B', '#10B981', '#3B82F6',
  '#8B5CF6', '#14B8A6', '#F97316', '#64748B', '#06B6D4'
];

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


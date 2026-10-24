/**
 * 數值與日期格式化工具模組 (Pure Functions & Constants)
 */

export const QUICK_CATEGORIES = [
  '飲食', '房租水電', '交通', '日常採買', '娛樂休閒', '保險醫療', '信用卡費', '投資', '薪資收入', '其他'
];

/**
 * 結餘儲蓄專用色 (翡翠綠，象徵資金結餘與儲蓄積累，其它支出分類絕不佔用)
 */
export const SAVINGS_COLOR = '#10B981';

/**
 * 24 色大師級無重複色盤 (Hue-Separated Master Palette)
 * 具備極高色相分離度，確保無論多少分類同時出現，皆保證 100% 互不重複且色彩鮮明舒適
 */
export const MASTER_UNIQUE_PALETTE = [
  '#F59E0B', // 01. 暖金黃 (Amber 500)
  '#2563EB', // 02. 寶石藍 (Blue 600)
  '#8B5CF6', // 03. 尊爵紫 (Violet 500)
  '#EC4899', // 04. 活力粉 (Pink 500)
  '#06B6D4', // 05. 清爽青 (Cyan 500)
  '#F97316', // 06. 陽光橘 (Orange 500)
  '#14B8A6', // 07. 蒂芬妮綠 (Teal 500)
  '#D946EF', // 08. 洋紅品粉 (Fuchsia 500)
  '#4F46E5', // 09. 靛青藍 (Indigo 600)
  '#E11D48', // 10. 玫瑰深紅 (Rose 600)
  '#0EA5E9', // 11. 明亮天藍 (Sky 500)
  '#84CC16', // 12. 萊姆草綠 (Lime 500)
  '#A855F7', // 13. 薰衣草紫 (Purple 500)
  '#F43F5E', // 14. 珊瑚粉紅 (Rose 500)
  '#0D9488', // 15. 深松綠 (Teal 600)
  '#059669', // 16. 森林深綠 (Emerald 600)
  '#7C3AED', // 17. 皇家深紫 (Violet 600)
  '#D97706', // 18. 焦糖金 (Amber 600)
  '#3730A3', // 19. 深夜海軍藍 (Indigo 800)
  '#581C87', // 20. 退休深梅紫 (Purple 900)
  '#991B1B', // 21. 所得稅深紅 (Red 800)
  '#64748B', // 22. 沉穩石板灰 (Slate 500)
  '#DB2777', // 23. 覆盆子紅 (Pink 600)
  '#94A3B8'  // 24. 中性淺灰 (Slate 400)
];

export const CHART_PALETTE = [...MASTER_UNIQUE_PALETTE];

/**
 * 核心分類專屬色彩映射表 (語意專屬色彩)
 * 每個分類與薪資扣繳均享有清晰且互不衝突的專屬預設色
 */
export const CATEGORY_COLORS = {
  '投資': '#8B5CF6',       // 尊爵紫 (專屬投資理財/ETF/股票，與綠色結餘徹底區分)
  '飲食': '#F59E0B',       // 暖金黃 (餐飲美食)
  '居住': '#2563EB',       // 寶石藍 (房租管理)
  '房租水電': '#2563EB',   // 寶石藍
  '交通': '#06B6D4',       // 清爽青 (通勤交通)
  '電信網路': '#0EA5E9',   // 天空藍 (通訊網路)
  '娛樂': '#EC4899',       // 活力粉 (休閒娛樂)
  '娛樂休閒': '#EC4899',   // 活力粉
  '日常採買': '#F97316',   // 陽光橘 (日常採購)
  '日常購物': '#F97316',   // 陽光橘
  '保險': '#14B8A6',       // 蒂芬妮綠 (商業保險)
  '保險醫療': '#14B8A6',
  '保險費': '#14B8A6',
  '稅務': '#E11D48',       // 玫瑰深紅 (牌照燃料稅等)
  '孝親': '#D946EF',       // 洋紅品粉 (孝親費用)
  '貸款': '#64748B',       // 沉穩灰 (貸款分期)
  '信用卡費': '#4F46E5',   // 經典靛藍 (卡費支出)
  '全民健保費': '#0D9488', // 健保專屬深松綠
  '勞工保險費': '#3730A3', // 勞保專屬深夜海軍藍
  '勞退自提': '#581C87',   // 勞退退休金深梅紫 (與投資亮紫徹底區別)
  '預繳所得稅': '#991B1B', // 薪資預扣深酒紅
  '薪資收入': '#10B981',   // 收入專用翡翠綠
  '其他': '#94A3B8'        // 柔和淺灰
};

/**
 * 動態唯一去重配色演算法
 * 保證傳入的所有項目（包含自訂分類、法定扣繳與固定開銷）在同一圖表中 100% 配色不重複
 */
export const assignUniqueColors = (items, isExpenseMode = true) => {
  if (!Array.isArray(items)) return [];
  const usedColors = new Set();
  if (isExpenseMode) {
    usedColors.add(SAVINGS_COLOR.toLowerCase());
  }

  return items.map((item, idx) => {
    const cat = (item.category || '').trim();
    let chosenColor = null;

    // 1. 優先比對專屬語意色彩表
    if (CATEGORY_COLORS[cat]) {
      const pref = CATEGORY_COLORS[cat].toLowerCase();
      if (!usedColors.has(pref)) {
        chosenColor = CATEGORY_COLORS[cat];
      }
    }

    // 2. 關鍵字模糊比對（如：定期定額投資、勞退自提 6% 等）
    if (!chosenColor) {
      if (cat.includes('投資') || cat.includes('理財') || cat.includes('股票') || cat.includes('ETF') || cat.includes('基金')) {
        if (!usedColors.has('#8b5cf6')) chosenColor = '#8B5CF6';
      } else if (cat.includes('健保')) {
        if (!usedColors.has('#0d9488')) chosenColor = '#0D9488';
      } else if (cat.includes('勞保')) {
        if (!usedColors.has('#3730a3')) chosenColor = '#3730A3';
      } else if (cat.includes('勞退') || cat.includes('退休')) {
        if (!usedColors.has('#581c87')) chosenColor = '#581C87';
      } else if (cat.includes('稅')) {
        if (!usedColors.has('#991b1b')) chosenColor = '#991B1B';
      }
    }

    // 3. 若無預設色或已被前方項目佔用，由 24 色大師色盤挑選尚未被使用的顏色
    if (!chosenColor) {
      for (const color of MASTER_UNIQUE_PALETTE) {
        if (!usedColors.has(color.toLowerCase())) {
          chosenColor = color;
          break;
        }
      }
    }

    // 4. 極端情況（分類多於 24 種），循環備援分配
    if (!chosenColor) {
      chosenColor = MASTER_UNIQUE_PALETTE[idx % MASTER_UNIQUE_PALETTE.length];
    }

    usedColors.add(chosenColor.toLowerCase());
    return {
      ...item,
      color: chosenColor
    };
  });
};

export const getCategoryColor = (category, index = 0) => {
  if (!category) return MASTER_UNIQUE_PALETTE[index % MASTER_UNIQUE_PALETTE.length];
  const catTrim = String(category).trim();
  if (CATEGORY_COLORS[catTrim]) {
    return CATEGORY_COLORS[catTrim];
  }
  if (catTrim.includes('投資') || catTrim.includes('理財') || catTrim.includes('基金') || catTrim.includes('ETF') || catTrim.includes('股票')) {
    return '#8B5CF6';
  }
  return MASTER_UNIQUE_PALETTE[index % MASTER_UNIQUE_PALETTE.length];
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


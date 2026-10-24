/**
 * Chart.js 圓餅圖渲染封裝模組 (Isolating Charting Library Details)
 */

import { SAVINGS_COLOR } from './formatters.js?v=2.4.4';

let chartInstance = null;

export const renderExpenseDoughnutChart = ({
  canvasId = 'expenseChart',
  salary,
  totalExp,
  expensesList = [],
  incomesList = [],
  mode = 'expense'
}) => {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !window.Chart) return;

  const labels = [];
  const data = [];
  const bgColors = [];

  if (mode === 'income') {
    incomesList.forEach(item => {
      const ratioStr = Number(item.ratioOfTotal || item.ratioOfSalary || 0).toFixed(1);
      labels.push(`${item.category} (${ratioStr}%)`);
      data.push(item.amount);
      bgColors.push(item.color);
    });
    if (data.length === 0) {
      labels.push('無收入紀錄');
      data.push(1);
      bgColors.push('#E2E8F0');
    }
  } else {
    const effectiveSalary = salary || 50000;
    const leftover = Math.max(0, effectiveSalary - totalExp);

    expensesList.forEach(item => {
      const ratioStr = Number(item.ratioOfSalary || 0).toFixed(1);
      labels.push(`${item.category} (${ratioStr}%)`);
      data.push(item.amount);
      bgColors.push(item.color);
    });

    if (leftover > 0) {
      const leftoverRatio = effectiveSalary > 0 ? ((leftover / effectiveSalary) * 100).toFixed(1) : '0.0';
      labels.push(`結餘儲蓄 (${leftoverRatio}%)`);
      data.push(leftover);
      bgColors.push(SAVINGS_COLOR || '#10B981');
    } else if (data.length === 0) {
      labels.push('無支出紀錄');
      data.push(1);
      bgColors.push('#E2E8F0');
    }
  }

  const isDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');

  if (chartInstance) {
    chartInstance.destroy();
  }

  chartInstance = new window.Chart(ctx, {
    type: 'doughnut',
    data: {
      labels,
      datasets: [{
        data,
        backgroundColor: bgColors,
        borderWidth: 2,
        borderColor: isDark ? '#1e293b' : '#ffffff',
        hoverOffset: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      cutout: '72%',
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (context) {
              return ` NT$ ${Math.round(context.parsed).toLocaleString('en-US')}`;
            }
          }
        }
      }
    }
  });
};

let trendChartInstance = null;

export const renderMonthlyTrendChart = ({
  canvasId = 'monthlyTrendChart',
  monthsData = [],
  chartMode = 'savings' // 'savings' (月末總存款) | 'net' (當月淨結餘)
}) => {
  const ctx = document.getElementById(canvasId);
  if (!ctx || !window.Chart) return;

  const labels = monthsData.map(d => d.label || d.month);
  const incomeData = monthsData.map(d => d.income);
  const expenseData = monthsData.map(d => d.expense);
  const lineData = chartMode === 'savings'
    ? monthsData.map(d => d.end_balance)
    : monthsData.map(d => d.net);
  const lineLabel = chartMode === 'savings' ? '月末預估存款' : '當月淨結餘';

  const isDark = typeof document !== 'undefined' && document.documentElement.classList.contains('dark');
  const textColor = isDark ? '#94a3b8' : '#64748b';
  const gridColor = isDark ? 'rgba(255, 255, 255, 0.08)' : '#F1F5F9';

  if (trendChartInstance) {
    trendChartInstance.destroy();
  }

  trendChartInstance = new window.Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          type: 'line',
          label: lineLabel,
          data: lineData,
          borderColor: '#6366F1', // Indigo 500
          backgroundColor: 'rgba(99, 102, 241, 0.1)',
          borderWidth: 3,
          pointBackgroundColor: '#6366F1',
          pointBorderColor: isDark ? '#1e293b' : '#ffffff',
          pointBorderWidth: 2,
          pointRadius: 5,
          pointHoverRadius: 7,
          tension: 0.35,
          fill: false,
          yAxisID: chartMode === 'savings' ? 'ySavings' : 'y'
        },
        {
          type: 'bar',
          label: '當月總收入',
          data: incomeData,
          backgroundColor: '#10B981', // Emerald 500
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 36,
          yAxisID: 'y'
        },
        {
          type: 'bar',
          label: '當月總開銷',
          data: expenseData,
          backgroundColor: '#F43F5E', // Rose 500
          borderRadius: 6,
          borderSkipped: false,
          maxBarThickness: 36,
          yAxisID: 'y'
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: {
        mode: 'index',
        intersect: false
      },
      plugins: {
        legend: {
          display: true,
          position: 'top',
          labels: {
            boxWidth: 12,
            boxHeight: 12,
            usePointStyle: true,
            color: textColor,
            font: {
              size: 11,
              weight: 'bold'
            }
          }
        },
        tooltip: {
          padding: 12,
          callbacks: {
            label: function (context) {
              const val = Math.round(context.parsed.y).toLocaleString('en-US');
              return ` ${context.dataset.label}: NT$ ${val}`;
            }
          }
        }
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: textColor }
        },
        y: {
          type: 'linear',
          display: true,
          position: 'left',
          grid: { color: gridColor },
          ticks: {
            color: textColor,
            callback: function (val) {
              if (Math.abs(val) >= 10000) {
                return (val / 10000).toFixed(1) + '萬';
              }
              return val;
            }
          }
        },
        ...(chartMode === 'savings' ? {
          ySavings: {
            type: 'linear',
            display: true,
            position: 'right',
            grid: { drawOnChartArea: false },
            ticks: {
              color: textColor,
              callback: function (val) {
                if (Math.abs(val) >= 10000) {
                  return (val / 10000).toFixed(1) + '萬';
                }
                return val;
              }
            }
          }
        } : {})
      }
    }
  });
};


/**
 * 台灣勞工保險與全民健康保險試算模組 (Taiwan Labor & Health Insurance Module)
 * 依據勞動部勞工保險局與衛生福利部中央健康保險署標準計算公式：
 * - 勞保費：普通事故 (11% × 20%) + 就業保險 (1% × 20%)，分別四捨五入後加總；最高投保薪資 45,800 元。
 * - 健保費：費率 5.17%，受雇勞工負擔 30%，眷屬口數上限為 3 口（計費口數最高 4 口）。
 */

export const LABOR_INSURANCE_BRACKETS = [
  27470, 27600, 28800, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
  42000, 43900, 45800
];

export const HEALTH_INSURANCE_BRACKETS = [
  27470, 27600, 28800, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
  42000, 43900, 45800, 48200, 50600, 53000, 55400, 57800, 60800, 63800,
  66800, 69800, 72800, 76500, 80200, 83900, 87600, 92100, 96600, 101100,
  105600, 110100, 115500, 120900, 126300, 131700, 137100, 142500, 147900, 150000,
  156600, 163200, 169800, 176400, 183000, 190500, 198000, 205500, 213000, 219500
];

// 勞工退休金月提繳工資分級表 (上限 150,000 元)
export const PENSION_BRACKETS = [
  1500, 3000, 4500, 6000, 7500, 8700, 9900, 11100, 12540, 13500, 15840, 16500, 17280, 17880, 19047, 20008, 21009, 22000, 23100, 24000, 25200, 26400,
  27470, 27600, 28800, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
  42000, 43900, 45800, 48200, 50600, 53000, 55400, 57800, 60800, 63800,
  66800, 69800, 72800, 76500, 80200, 83900, 87600, 92100, 96600, 101100,
  105600, 110100, 115500, 120900, 126300, 131700, 137100, 142500, 147900, 150000
];

export const LABOR_ORDINARY_RATE = 0.11;
export const LABOR_EMPLOYMENT_RATE = 0.01;
export const LABOR_EMPLOYEE_SHARE = 0.20;

export const HEALTH_RATE = 0.0517;
export const HEALTH_EMPLOYEE_SHARE = 0.30;

export const matchBracket = (salary, brackets) => {
  const numSalary = Number(salary) || 0;
  if (numSalary <= brackets[0]) {
    return brackets[0];
  }
  for (let i = 0; i < brackets.length; i++) {
    if (numSalary <= brackets[i]) {
      return brackets[i];
    }
  }
  return brackets[brackets.length - 1];
};

export const calculateLaborInsurance = (salary) => {
  const bracket = matchBracket(salary, LABOR_INSURANCE_BRACKETS);
  const ordinaryFee = Math.round(bracket * LABOR_ORDINARY_RATE * LABOR_EMPLOYEE_SHARE);
  const employmentFee = Math.round(bracket * LABOR_EMPLOYMENT_RATE * LABOR_EMPLOYEE_SHARE);
  const fee = ordinaryFee + employmentFee;

  return {
    bracket,
    ordinaryFee,
    employmentFee,
    fee
  };
};

export const calculateHealthInsurance = (salary, dependentsCount = 1) => {
  const count = Math.max(1, parseInt(dependentsCount, 10) || 1);
  const billingDependents = Math.min(count, 4); // 健保法第18條：眷屬超過3口以3口計，本人+眷屬最高4口
  const bracket = matchBracket(salary, HEALTH_INSURANCE_BRACKETS);
  const feePerPerson = Math.round(bracket * HEALTH_RATE * HEALTH_EMPLOYEE_SHARE);
  const fee = feePerPerson * billingDependents;

  return {
    bracket,
    dependentsCount: count,
    billingDependents,
    feePerPerson,
    fee
  };
};

export const calculatePension = (salary, rate = 0.06) => {
  const validRate = Math.max(0, Math.min(0.06, Number(rate) || 0));
  const bracket = matchBracket(salary, PENSION_BRACKETS);
  const fee = Math.round(bracket * validRate);

  return {
    bracket,
    rate: validRate,
    ratePercentage: Math.round(validRate * 100),
    fee
  };
};

export const calculateIncomeTax = (salary, pensionFee = 0, rate = 0.05) => {
  const validRate = Math.max(0, Math.min(0.30, Number(rate) || 0));
  const pensionDeduction = Math.max(0, Number(pensionFee) || 0);
  const taxableSalary = Math.max(0, Number(salary || 0) - pensionDeduction);
  const fee = Math.round(taxableSalary * validRate);

  return {
    rate: validRate,
    ratePercentage: Math.round(validRate * 100),
    taxableSalary,
    pensionDeduction,
    fee
  };
};

export const calculateInsuranceSummary = (salary, dependentsCount = 1, pensionRate = 0.0, taxRate = 0.0) => {
  const grossSalary = Math.max(0, Number(salary) || 0);
  const labor = calculateLaborInsurance(grossSalary);
  const health = calculateHealthInsurance(grossSalary, dependentsCount);
  const pension = calculatePension(grossSalary, pensionRate);
  const tax = calculateIncomeTax(grossSalary, pension.fee, taxRate);
  const totalDeduction = labor.fee + health.fee + pension.fee + tax.fee;
  const netSalary = Math.max(0, grossSalary - totalDeduction);

  return {
    grossSalary,
    labor,
    health,
    pension,
    tax,
    totalDeduction,
    netSalary
  };
};


"""
台灣勞工保險與全民健康保險試算服務 (Taiwan Labor & Health Insurance Service)
遵循最新法規分級表與個人負擔比例公式：
- 勞保費：普通事故 11% + 就業保險 1% = 12%，勞工負擔 20%，上限級距 45,800 元。
- 健保費：費率 5.17%，受雇勞工負擔 30%，眷屬口數上限為 3 口（計費口數最多 4 口）。
"""

from typing import Dict, Any

# 勞工保險投保薪資分級表 (上限 45,800 元)
LABOR_INSURANCE_BRACKETS = [
    27470, 27600, 28800, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
    42000, 43900, 45800
]

# 全民健康保險投保金額分級表 (共 50 級，上限 219,500 元)
HEALTH_INSURANCE_BRACKETS = [
    27470, 27600, 28800, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
    42000, 43900, 45800, 48200, 50600, 53000, 55400, 57800, 60800, 63800,
    66800, 69800, 72800, 76500, 80200, 83900, 87600, 92100, 96600, 101100,
    105600, 110100, 115500, 120900, 126300, 131700, 137100, 142500, 147900, 150000,
    156600, 163200, 169800, 176400, 183000, 190500, 198000, 205500, 213000, 219500
]

# 勞工退休金月提繳工資分級表 (上限 150,000 元)
PENSION_BRACKETS = [
    1500, 3000, 4500, 6000, 7500, 8700, 9900, 11100, 12540, 13500, 15840, 16500, 17280, 17880, 19047, 20008, 21009, 22000, 23100, 24000, 25200, 26400,
    27470, 27600, 28800, 30300, 31800, 33300, 34800, 36300, 38200, 40100,
    42000, 43900, 45800, 48200, 50600, 53000, 55400, 57800, 60800, 63800,
    66800, 69800, 72800, 76500, 80200, 83900, 87600, 92100, 96600, 101100,
    105600, 110100, 115500, 120900, 126300, 131700, 137100, 142500, 147900, 150000
]

LABOR_ORDINARY_RATE = 0.11       # 普通事故費率 11%
LABOR_EMPLOYMENT_RATE = 0.01     # 就業保險費率 1%
LABOR_EMPLOYEE_SHARE = 0.20      # 勞工個人負擔 20%

HEALTH_RATE = 0.0517             # 健保法定費率 5.17%
HEALTH_EMPLOYEE_SHARE = 0.30     # 受雇者個人負擔 30%


def match_bracket(salary: float, brackets: list[int]) -> int:
    """找出大於等於薪資的最小級距；若超過最高級距則取最高級距"""
    if salary <= brackets[0]:
        return brackets[0]
    for b in brackets:
        if salary <= b:
            return b
    return brackets[-1]


def calculate_labor_insurance(salary: float) -> Dict[str, Any]:
    """
    計算勞工保險自付額
    依照勞動部勞工保險局官方公式：
    普通事故與就業保險分別計算後四捨五入再加總：
    - 普通事故自付額 = round(投保薪資 × 11% × 20%)
    - 就業保險自付額 = round(投保薪資 × 1% × 20%)
    - 勞保合計自付額 = 普通事故自付額 + 就業保險自付額 (例如 45,800 元級距為 1,008 + 92 = 1,100 元)
    """
    bracket = match_bracket(salary, LABOR_INSURANCE_BRACKETS)
    ordinary_fee = round(bracket * LABOR_ORDINARY_RATE * LABOR_EMPLOYEE_SHARE)
    employment_fee = round(bracket * LABOR_EMPLOYMENT_RATE * LABOR_EMPLOYEE_SHARE)
    fee = ordinary_fee + employment_fee

    return {
        "bracket": bracket,
        "ordinary_rate": LABOR_ORDINARY_RATE,
        "employment_rate": LABOR_EMPLOYMENT_RATE,
        "employee_share": LABOR_EMPLOYEE_SHARE,
        "ordinary_fee": ordinary_fee,
        "employment_fee": employment_fee,
        "fee": fee
    }


def calculate_health_insurance(salary: float, dependents_count: int = 1) -> Dict[str, Any]:
    """
    計算全民健康保險自付額
    公式：
    - 每口保費 = 投保金額 × 5.17% × 30% (四捨五入)
    - 計費口數 = min(投保人數, 4) (依健保法第18條，眷屬超過3口以3口計，含本人最高計4口)
    - 總健保自付額 = 每口保費 × 計費口數
    """
    count = max(1, int(dependents_count))
    billing_dependents = min(count, 4)
    bracket = match_bracket(salary, HEALTH_INSURANCE_BRACKETS)
    fee_per_person = round(bracket * HEALTH_RATE * HEALTH_EMPLOYEE_SHARE)
    total_fee = fee_per_person * billing_dependents

    return {
        "bracket": bracket,
        "rate": HEALTH_RATE,
        "employee_share": HEALTH_EMPLOYEE_SHARE,
        "dependents_count": count,
        "billing_dependents": billing_dependents,
        "fee_per_person": fee_per_person,
        "fee": total_fee
    }


def calculate_pension(salary: float, rate: float = 0.06) -> Dict[str, Any]:
    """
    計算勞工退休金個人自願提繳金額 (0% ~ 6%)
    依據勞工退休金月提繳工資分級表 (上限 150,000 元)
    公式：round(月提繳工資級距 × 自提比率)
    """
    valid_rate = max(0.0, min(0.06, float(rate)))
    bracket = match_bracket(salary, PENSION_BRACKETS)
    fee = round(bracket * valid_rate)

    return {
        "bracket": bracket,
        "rate": valid_rate,
        "rate_percentage": round(valid_rate * 100),
        "fee": fee
    }


def calculate_income_tax(salary: float, pension_fee: float = 0.0, rate: float = 0.05) -> Dict[str, Any]:
    """
    計算每月薪資預繳/扣繳所得稅金額 (例如 5%)
    依《勞工退休金條例》第14條第3項：勞工自願提繳之退休金，不計入提繳年度薪資所得課稅。
    公式：
      應稅基數 (Taxable Salary) = max(0, 每月全薪 - 勞退自提金額)
      預繳所得稅額 (Income Tax) = round(應稅基數 × 扣繳率)
    """
    valid_rate = max(0.0, min(0.30, float(rate)))
    pension_deduction = max(0.0, float(pension_fee))
    taxable_salary = max(0.0, float(salary) - pension_deduction)
    fee = round(taxable_salary * valid_rate)

    return {
        "rate": valid_rate,
        "rate_percentage": round(valid_rate * 100),
        "taxable_salary": taxable_salary,
        "pension_deduction": pension_deduction,
        "fee": fee
    }


def calculate_insurance_summary(
    salary: float,
    dependents_count: int = 1,
    pension_rate: float = 0.0,
    tax_rate: float = 0.0
) -> Dict[str, Any]:
    """計算勞保、健保、勞退自提、預繳所得稅扣除總額與實領月薪"""
    gross_salary = max(0.0, float(salary))
    labor = calculate_labor_insurance(gross_salary)
    health = calculate_health_insurance(gross_salary, dependents_count)
    pension = calculate_pension(gross_salary, pension_rate)
    tax = calculate_income_tax(gross_salary, pension["fee"], tax_rate)
    total_deduction = labor["fee"] + health["fee"] + pension["fee"] + tax["fee"]
    net_salary = max(0.0, gross_salary - total_deduction)

    return {
        "gross_salary": gross_salary,
        "labor_insurance": labor,
        "health_insurance": health,
        "labor_pension": pension,
        "income_tax": tax,
        "total_deduction": total_deduction,
        "net_salary": net_salary
    }

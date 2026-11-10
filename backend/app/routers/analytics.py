from datetime import date, datetime
from dateutil.relativedelta import relativedelta
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, Transaction, Account, RecurringExpense
from ..services.accounting_service import get_setting
from ..services.auth_service import get_current_user
from ..services.insurance_service import calculate_insurance_summary

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/monthly-trends")
def get_monthly_trends(
    months: int = 6,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
) -> Dict[str, Any]:
    """
    計算指定月數內（如近 6、12、24 個月）每個月的：
    1. 總收入、總開銷與當月淨存入 (結餘)
    2. 開銷較上月增減幅度 (MoM)
    3. 月末存款總水位走向 (倒推驗證法)
    4. 儲蓄率與開銷前三大類別
    """
    if months not in (6, 12, 24):
        months = 6

    today = date.today()
    # 產生 months + 1 個月份，最前面一個月份用於計算第一個月的 MoM
    month_keys = []
    for i in range(months, -1, -1):
        dt = today - relativedelta(months=i)
        month_keys.append(dt.strftime("%Y-%m"))

    uid = current_user.id

    # 取得使用者目前所有資產帳戶的總餘額
    user_accounts = db.query(Account).filter(Account.user_id == uid).all()
    current_balance = sum(float(a.balance or 0.0) for a in user_accounts)

    # 讀取使用者設定的基準薪資與法定扣繳設定
    start_month = get_setting(db, "BOOKKEEPING_START_MONTH", "2026-11", user_id=uid)
    salary_str = get_setting(db, "MONTHLY_SALARY", "", user_id=uid)
    base_salary = float(salary_str) if salary_str else 0.0

    deduct_labor_health_str = get_setting(db, "DEDUCT_LABOR_HEALTH", "false", user_id=uid)
    deduct_labor_health = deduct_labor_health_str.lower() in ("true", "1")

    show_chart_str = get_setting(db, "SHOW_DEDUCTIONS_IN_CHART", "true", user_id=uid)
    show_deductions_in_chart = show_chart_str.lower() in ("true", "1")

    dependents_str = get_setting(db, "HEALTH_INSURANCE_DEPENDENTS", "1", user_id=uid)
    dependents = int(dependents_str) if dependents_str and dependents_str.isdigit() else 1

    auto_calc_str = get_setting(db, "LABOR_HEALTH_AUTO_CALC", "true", user_id=uid)
    auto_calc = auto_calc_str.lower() in ("true", "1")

    pension_rate_str = get_setting(db, "PENSION_RATE", "0.0", user_id=uid)
    try:
        pension_rate = float(pension_rate_str)
    except (ValueError, TypeError):
        pension_rate = 0.0

    tax_rate_str = get_setting(db, "TAX_RATE", "0.0", user_id=uid)
    try:
        tax_rate = float(tax_rate_str)
    except (ValueError, TypeError):
        tax_rate = 0.0

    labor_fee_str = get_setting(db, "LABOR_INSURANCE_FEE", "", user_id=uid) or None
    health_fee_str = get_setting(db, "HEALTH_INSURANCE_FEE", "", user_id=uid) or None
    pension_fee_str = get_setting(db, "PENSION_FEE", "", user_id=uid) or None
    tax_fee_str = get_setting(db, "TAX_FEE", "", user_id=uid) or None

    if deduct_labor_health:
        if auto_calc or labor_fee_str is None or health_fee_str is None or pension_fee_str is None or tax_fee_str is None:
            calc = calculate_insurance_summary(base_salary, dependents, pension_rate, tax_rate)
            labor_fee = float(calc["labor_insurance"]["fee"])
            health_fee = float(calc["health_insurance"]["fee"])
            pension_fee = float(calc["labor_pension"]["fee"])
            tax_fee = float(calc["income_tax"]["fee"])
        else:
            labor_fee = float(labor_fee_str)
            health_fee = float(health_fee_str)
            pension_fee = float(pension_fee_str)
            tax_fee = float(tax_fee_str)
    else:
        labor_fee = health_fee = pension_fee = tax_fee = 0.0

    # 依系統扣繳配置決定基準收入與扣繳費用項目
    if deduct_labor_health:
        if show_deductions_in_chart:
            monthly_base_income = base_salary
            statutory_deductions = {
                "全民健保費": health_fee,
                "勞工保險費": labor_fee,
                "勞退自提": pension_fee,
                "預繳所得稅": tax_fee
            }
        else:
            monthly_base_income = max(0.0, base_salary - labor_fee - health_fee - pension_fee - tax_fee)
            statutory_deductions = {}
    else:
        monthly_base_income = base_salary
        statutory_deductions = {}

    # 讀取使用者啟用中的每日常態/固定開銷項目
    recurring_items = db.query(RecurringExpense).filter(
        RecurringExpense.user_id == uid,
        RecurringExpense.is_active == True
    ).all()

    # 撈取該使用者的流水帳交易
    txs = db.query(Transaction).filter(
        Transaction.user_id == uid
    ).all()

    # 初始化各月份統計
    monthly_stats = {
        m: {
            "income": 0.0,
            "expense": 0.0,
            "categories": {}
        }
        for m in month_keys
    }

    # 判定手動流水帳中是否已記錄該月份的薪資（避免重複加計基準月薪）
    SALARY_KEYWORDS = ("薪資收入", "固定月薪", "薪資", "薪水", "salary")
    manual_salary_months = set()

    for tx in txs:
        if not tx.date:
            continue
        m_str = tx.date.strftime("%Y-%m")
        if start_month and m_str < start_month:
            continue
        if m_str in monthly_stats:
            amt = float(tx.amount or 0.0)
            if tx.tx_type == "INCOME":
                monthly_stats[m_str]["income"] += amt
                cat = tx.category or ""
                desc = tx.description or ""
                if cat in SALARY_KEYWORDS or any(kw in desc.lower() for kw in ("薪資", "固定月薪", "薪水")):
                    manual_salary_months.add(m_str)
            elif tx.tx_type == "EXPENSE":
                monthly_stats[m_str]["expense"] += amt
                cat = tx.category or "其他"
                monthly_stats[m_str]["categories"][cat] = (
                    monthly_stats[m_str]["categories"].get(cat, 0.0) + amt
                )
            elif tx.tx_type == "REFUND":
                # 退款 (負支出)：直接扣減當月總支出與該分類的支出統計
                refund_val = -abs(amt)
                monthly_stats[m_str]["expense"] += refund_val
                cat = tx.category or "其他"
                monthly_stats[m_str]["categories"][cat] = (
                    monthly_stats[m_str]["categories"].get(cat, 0.0) + refund_val
                )

    # 整合基準月薪、法定扣繳與固定常態開銷至各月份
    for m in month_keys:
        # 若早於正式記帳起始月份，不自動回填基準月薪或常態扣繳，歷史月份維持空白/為0
        if start_month and m < start_month:
            continue

        # 若該月尚未手動記入薪資流水帳且有設定基準月薪，納入當月總收入
        if m not in manual_salary_months and monthly_base_income > 0:
            monthly_stats[m]["income"] += monthly_base_income

        # 納入薪資法定扣繳項目（若開啟於圖表顯示扣繳）
        for cat_name, fee_amt in statutory_deductions.items():
            if fee_amt > 0:
                monthly_stats[m]["expense"] += fee_amt
                monthly_stats[m]["categories"][cat_name] = (
                    monthly_stats[m]["categories"].get(cat_name, 0.0) + fee_amt
                )

        # 若該月份已手動或自動記入實領薪資（淨額入帳），且開啟圖表扣繳切片，將扣繳加回該月總收入池以平衡支出扣除，避免二度扣減結餘
        if m in manual_salary_months and show_deductions_in_chart and statutory_deductions:
            tot_ded = sum(statutory_deductions.values())
            if monthly_stats[m]["income"] <= (base_salary - tot_ded + 10.0):
                monthly_stats[m]["income"] += tot_ded

        # 納入啟用中的常態固定開銷（月平攤額，若該月流水帳未有同名扣款）
        for item in recurring_items:
            amt = round(item.amount / 12, 2) if item.frequency == "YEARLY" else float(item.amount or 0.0)
            already_charged = any(
                t.date and t.date.strftime("%Y-%m") == m and item.name in (t.description or "")
                for t in txs
            )
            if not already_charged:
                cat = item.category or "其他"
                monthly_stats[m]["expense"] += amt
                monthly_stats[m]["categories"][cat] = (
                    monthly_stats[m]["categories"].get(cat, 0.0) + amt
                )

    # 目標分析月份列表 (排除多抓的前一個月，若有指定起始月份則過濾起始月份之前的月份)
    target_months = [m for m in month_keys[1:] if not start_month or m >= start_month]
    if not target_months and month_keys:
        target_months = [month_keys[-1]]

    # 逆推月末存款走勢：每個月滿足 end_balance[i] = end_balance[i-1] + net[i]
    month_nets = {
        m: monthly_stats[m]["income"] - monthly_stats[m]["expense"]
        for m in target_months
    }

    end_balances = {}
    running_balance = current_balance
    for m in reversed(target_months):
        end_balances[m] = running_balance
        running_balance = running_balance - month_nets[m]

    months_data = []
    for idx, m in enumerate(target_months):
        stat = monthly_stats[m]
        inc = round(stat["income"], 2)
        exp = round(stat["expense"], 2)
        net = round(inc - exp, 2)
        savings_rate = round((net / inc * 100), 1) if inc > 0 else 0.0

        # 與前一個月份對比 (安全依據月度時間遞減 1 個月比對)
        try:
            m_date = datetime.strptime(m, "%Y-%m").date()
            prev_m = (m_date - relativedelta(months=1)).strftime("%Y-%m")
        except Exception:
            prev_m = month_keys[idx] if idx < len(month_keys) else ""

        prev_stat = monthly_stats.get(prev_m, {"income": 0.0, "expense": 0.0, "categories": {}})
        prev_exp = prev_stat["expense"]
        prev_net = prev_stat["income"] - prev_stat["expense"]

        exp_mom_diff = round(exp - prev_exp, 2)
        exp_mom_pct = (
            round((exp_mom_diff / prev_exp * 100), 1) if prev_exp > 0 else 0.0
        )
        net_mom_diff = round(net - prev_net, 2)

        # 整理當月前三大開銷類別
        sorted_cats = sorted(
            stat["categories"].items(), key=lambda x: x[1], reverse=True
        )
        top_cats = []
        for c_name, c_amt in sorted_cats[:3]:
            pct = round((c_amt / exp * 100), 1) if exp > 0 else 0.0
            top_cats.append({
                "category": c_name,
                "amount": round(c_amt, 2),
                "pct": pct
            })

        parts = m.split("-")
        label = f"{int(parts[1])}月" if len(parts) == 2 else m
        full_label = f"{parts[0]}年{int(parts[1])}月" if len(parts) == 2 else m

        months_data.append({
            "month": m,
            "label": label,
            "full_label": full_label,
            "income": inc,
            "expense": exp,
            "net": net,
            "savings_rate": savings_rate,
            "end_balance": round(end_balances[m], 2),
            "expense_mom_diff": exp_mom_diff,
            "expense_mom_pct": exp_mom_pct,
            "net_mom_diff": net_mom_diff,
            "top_categories": top_cats
        })

    # 期間整體核心指標
    current_m_data = months_data[-1] if months_data else None
    total_period_income = sum(d["income"] for d in months_data)
    total_period_expense = sum(d["expense"] for d in months_data)
    total_period_net = sum(d["net"] for d in months_data)
    active_count = len(target_months) if target_months else 1
    avg_expense = (
        round(total_period_expense / active_count, 2) if months_data else 0.0
    )
    avg_income = (
        round(total_period_income / active_count, 2) if months_data else 0.0
    )

    start_balance = running_balance
    period_growth_pct = (
        round((total_period_net / start_balance * 100), 1)
        if start_balance > 0
        else 0.0
    )

    summary = {
        "current_month": current_m_data["month"] if current_m_data else "",
        "current_month_expense": (
            current_m_data["expense"] if current_m_data else 0.0
        ),
        "current_month_income": (
            current_m_data["income"] if current_m_data else 0.0
        ),
        "current_month_net": current_m_data["net"] if current_m_data else 0.0,
        "current_month_savings_rate": (
            current_m_data["savings_rate"] if current_m_data else 0.0
        ),
        "expense_mom_diff": (
            current_m_data["expense_mom_diff"] if current_m_data else 0.0
        ),
        "expense_mom_pct": (
            current_m_data["expense_mom_pct"] if current_m_data else 0.0
        ),
        "net_mom_diff": current_m_data["net_mom_diff"] if current_m_data else 0.0,
        "total_period_income": round(total_period_income, 2),
        "total_period_expense": round(total_period_expense, 2),
        "total_period_net": round(total_period_net, 2),
        "avg_monthly_expense": avg_expense,
        "avg_monthly_income": avg_income,
        "start_balance": round(start_balance, 2),
        "end_balance": round(current_balance, 2),
        "period_growth_amount": round(total_period_net, 2),
        "period_growth_pct": period_growth_pct
    }

    return {
        "range_months": months,
        "current_balance": round(current_balance, 2),
        "summary": summary,
        "months_data": months_data
    }


from datetime import date
from dateutil.relativedelta import relativedelta
from typing import Dict, Any
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Transaction, Account
from ..services.auth_service import get_current_user

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

    # 取得使用者目前所有資產帳戶的總餘額
    user_accounts = db.query(Account).filter(Account.user_id == current_user.id).all()
    current_balance = sum(float(a.balance or 0.0) for a in user_accounts)

    # 撈取該使用者的流水帳交易
    txs = db.query(Transaction).filter(
        Transaction.user_id == current_user.id
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

    for tx in txs:
        if not tx.date:
            continue
        m_str = tx.date.strftime("%Y-%m")
        if m_str in monthly_stats:
            amt = float(tx.amount or 0.0)
            if tx.tx_type == "INCOME":
                monthly_stats[m_str]["income"] += amt
            elif tx.tx_type == "EXPENSE":
                monthly_stats[m_str]["expense"] += amt
                cat = tx.category or "其他"
                monthly_stats[m_str]["categories"][cat] = (
                    monthly_stats[m_str]["categories"].get(cat, 0.0) + amt
                )

    # 目標分析月份列表 (排除多抓的前一個月)
    target_months = month_keys[1:]

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

        # 與前一個月份對比 (idx 在 month_keys 中對應前一個月份)
        prev_m = month_keys[idx]
        prev_stat = monthly_stats[prev_m]
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
    avg_expense = (
        round(total_period_expense / len(months_data), 2) if months_data else 0.0
    )
    avg_income = (
        round(total_period_income / len(months_data), 2) if months_data else 0.0
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


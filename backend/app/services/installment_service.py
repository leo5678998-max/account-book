import calendar
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
from typing import Optional, List, Dict, Any, Tuple
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import InstallmentPlan, Transaction, Account
from ..schemas import (
    InstallmentPlanCreate,
    InstallmentPlanUpdate,
    InstallmentPeriodItem,
)

# 領域常數
INSTALLMENT_STATUS_ACTIVE = "ACTIVE"
INSTALLMENT_STATUS_COMPLETED = "COMPLETED"
INSTALLMENT_STATUS_CANCELLED = "CANCELLED"
CATEGORY_DEFAULT = "其他"
TX_TYPE_EXPENSE = "EXPENSE"


def calculate_installment_amounts(total_amount: float, total_periods: int) -> Tuple[float, float]:
    """
    純數值運算：計算信用卡分期每期本金與首期微調吸收零頭。
    例如 10,000 元分 3 期：
    每期本金 = 3,333.33，首期本金 = 3,333.34，加總剛好 10,000 元整。
    """
    if total_periods <= 0:
        return total_amount, total_amount

    total = round(float(total_amount), 2)
    # 平均每期 (四捨五入至兩位小數)
    monthly = round(total / total_periods, 2)
    # 首期吸收差額，確保各期相加嚴格等於總金額
    first_amount = round(total - (monthly * (total_periods - 1)), 2)
    return monthly, first_amount


def compute_installment_period_date(start_date: date, period_index: int, billing_day: Optional[int] = None) -> date:
    """計算第 N 期分期之應繳入帳日期 (period_index 為 1-based)"""
    # 依月份依序遞增
    target_dt = start_date + relativedelta(months=period_index - 1)
    target_year = target_dt.year
    target_month = target_dt.month

    # 若有指定每月扣款日，依該月份天數自動校正 (例如 2 月無 31 號時取 28 或 29)
    if billing_day and 1 <= billing_day <= 31:
        max_days = calendar.monthrange(target_year, target_month)[1]
        day = min(billing_day, max_days)
        return date(target_year, target_month, day)

    return target_dt


def generate_amortization_schedule(
    plan: InstallmentPlan,
    transactions: Optional[List[Transaction]] = None
) -> List[InstallmentPeriodItem]:
    """產生分期攤提明細表 (每期本金、利息/手續費、入帳年月、狀態與對應交易)"""
    schedule: List[InstallmentPeriodItem] = []
    tx_by_period = {}
    if transactions:
        for tx in transactions:
            if tx.installment_period:
                tx_by_period[tx.installment_period] = tx.id

    first_amt = plan.first_amount if plan.first_amount is not None else plan.monthly_amount
    monthly_amt = plan.monthly_amount
    monthly_fee = float(plan.monthly_fee or 0.0)

    # 若有年利率，計算每期利息 = (剩餘本金或平均本金 * 年利率 / 12)
    # 台灣信用卡分期多為固定手續費或零利率
    annual_rate = float(plan.interest_rate or 0.0) / 100.0

    for p in range(1, plan.total_periods + 1):
        period_date = compute_installment_period_date(plan.start_date, p, plan.billing_day)
        p_amount = first_amt if p == 1 else monthly_amt

        # 利息或手續費
        interest = round(monthly_fee + (p_amount * annual_rate / 12.0), 2)
        total_due = round(p_amount + interest, 2)

        is_paid = (p <= plan.current_period)
        tx_id = tx_by_period.get(p)

        schedule.append(InstallmentPeriodItem(
            period=p,
            due_date=period_date,
            amount=p_amount,
            interest=interest,
            total_due=total_due,
            status="PAID" if is_paid else "PENDING",
            transaction_id=tx_id
        ))

    return schedule


def _calculate_plan_metrics(plan: InstallmentPlan) -> Dict[str, Any]:
    """計算單一分期計畫的進度、剩餘未還金額與下一期資訊"""
    first_amt = plan.first_amount if plan.first_amount is not None else plan.monthly_amount
    monthly_amt = plan.monthly_amount
    curr_period = min(plan.current_period or 0, plan.total_periods)

    # 計算已還本金
    if curr_period <= 0:
        paid_amount = 0.0
    elif curr_period == 1:
        paid_amount = first_amt
    else:
        paid_amount = first_amt + (monthly_amt * (curr_period - 1))

    paid_amount = round(paid_amount, 2)
    remaining_amount = max(0.0, round(float(plan.total_amount) - paid_amount, 2))
    progress_percent = round((curr_period / plan.total_periods) * 100.0, 1) if plan.total_periods > 0 else 100.0

    # 下一期資訊
    next_due_date = None
    next_amount = None
    if curr_period < plan.total_periods and plan.status == INSTALLMENT_STATUS_ACTIVE:
        next_period = curr_period + 1
        next_due_date = compute_installment_period_date(plan.start_date, next_period, plan.billing_day)
        next_principal = first_amt if next_period == 1 else monthly_amt
        next_amount = round(next_principal + float(plan.monthly_fee or 0.0), 2)

    return {
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "progress_percent": progress_percent,
        "progress_percentage": progress_percent,
        "next_due_date": next_due_date,
        "next_amount": next_amount
    }


def get_installment_plans_list(
    db: Session,
    user_id: int,
    status_filter: Optional[str] = None
) -> List[Dict[str, Any]]:
    """取得使用者的所有分期付款清單"""
    query = db.query(InstallmentPlan).filter(InstallmentPlan.user_id == user_id)
    if status_filter:
        query = query.filter(InstallmentPlan.status == status_filter.upper())

    plans = query.order_by(
        # 進行中放前面，結清與終止放後面
        InstallmentPlan.status.asc(),
        InstallmentPlan.id.desc()
    ).all()

    acc_map = {a.id: a.name for a in db.query(Account).filter(Account.user_id == user_id).all()}

    results = []
    for plan in plans:
        metrics = _calculate_plan_metrics(plan)
        results.append({
            "id": plan.id,
            "name": plan.name,
            "total_amount": plan.total_amount,
            "total_periods": plan.total_periods,
            "current_period": plan.current_period,
            "monthly_amount": plan.monthly_amount,
            "first_amount": plan.first_amount,
            "interest_rate": plan.interest_rate,
            "monthly_fee": plan.monthly_fee,
            "category": plan.category,
            "account_id": plan.account_id,
            "account_name": acc_map.get(plan.account_id, "尚未指定帳戶"),
            "start_date": plan.start_date,
            "billing_day": plan.billing_day,
            "status": plan.status,
            "notes": plan.notes,
            "auto_record": plan.auto_record,
            "paid_amount": metrics["paid_amount"],
            "remaining_amount": metrics["remaining_amount"],
            "progress_percent": metrics["progress_percent"],
            "progress_percentage": metrics["progress_percentage"],
            "next_due_date": metrics["next_due_date"],
            "next_amount": metrics["next_amount"],
            "created_at": plan.created_at,
            "updated_at": plan.updated_at
        })
    return results


def get_installment_plan_detail(db: Session, plan_id: int, user_id: int) -> Dict[str, Any]:
    """取得單一分期計畫詳情（含完整分期攤提日程表）"""
    plan = db.query(InstallmentPlan).filter(
        InstallmentPlan.id == plan_id,
        InstallmentPlan.user_id == user_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="找不到指定分期計畫")

    txs = db.query(Transaction).filter(
        Transaction.installment_plan_id == plan.id,
        Transaction.user_id == user_id
    ).order_by(Transaction.installment_period.asc()).all()

    schedule = generate_amortization_schedule(plan, txs)
    metrics = _calculate_plan_metrics(plan)
    acc = db.query(Account).filter(Account.id == plan.account_id, Account.user_id == user_id).first() if plan.account_id else None

    return {
        "id": plan.id,
        "name": plan.name,
        "total_amount": plan.total_amount,
        "total_periods": plan.total_periods,
        "current_period": plan.current_period,
        "monthly_amount": plan.monthly_amount,
        "first_amount": plan.first_amount,
        "interest_rate": plan.interest_rate,
        "monthly_fee": plan.monthly_fee,
        "category": plan.category,
        "account_id": plan.account_id,
        "account_name": acc.name if acc else "尚未指定帳戶",
        "start_date": plan.start_date,
        "billing_day": plan.billing_day,
        "status": plan.status,
        "notes": plan.notes,
        "auto_record": plan.auto_record,
        "paid_amount": metrics["paid_amount"],
        "remaining_amount": metrics["remaining_amount"],
        "progress_percent": metrics["progress_percent"],
        "progress_percentage": metrics["progress_percentage"],
        "next_due_date": metrics["next_due_date"],
        "next_amount": metrics["next_amount"],
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
        "schedule": schedule,
        "periods": schedule
    }


def create_installment_plan(
    db: Session,
    user_id: int,
    plan_in: InstallmentPlanCreate
) -> Dict[str, Any]:
    """建立新的信用卡分期計畫"""
    if plan_in.total_amount <= 0:
        raise HTTPException(status_code=400, detail="分期總金額必須大於 0")
    if plan_in.total_periods <= 0:
        raise HTTPException(status_code=400, detail="分期期數必須大於 0")

    monthly_amt, first_amt = calculate_installment_amounts(plan_in.total_amount, plan_in.total_periods)
    billing_d = plan_in.billing_day or plan_in.start_date.day

    plan = InstallmentPlan(
        user_id=user_id,
        name=plan_in.name,
        total_amount=plan_in.total_amount,
        total_periods=plan_in.total_periods,
        current_period=0,
        monthly_amount=monthly_amt,
        first_amount=first_amt,
        interest_rate=plan_in.interest_rate,
        monthly_fee=plan_in.monthly_fee,
        category=plan_in.category or CATEGORY_DEFAULT,
        account_id=plan_in.account_id,
        start_date=plan_in.start_date,
        billing_day=billing_d,
        status=INSTALLMENT_STATUS_ACTIVE,
        notes=plan_in.notes,
        auto_record=plan_in.auto_record
    )
    db.add(plan)
    db.flush()

    # 若使用者選擇建立時直接記錄第 1 期支出
    if plan_in.record_first_period:
        charge_installment_period(db, plan.id, user_id, target_period=1)

    db.commit()
    db.refresh(plan)
    return get_installment_plan_detail(db, plan.id, user_id)


def update_installment_plan(
    db: Session,
    plan_id: int,
    user_id: int,
    plan_in: InstallmentPlanUpdate
) -> Dict[str, Any]:
    """更新分期計畫"""
    plan = db.query(InstallmentPlan).filter(
        InstallmentPlan.id == plan_id,
        InstallmentPlan.user_id == user_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="找不到指定分期計畫")

    update_data = plan_in.model_dump(exclude_unset=True) if hasattr(plan_in, "model_dump") else plan_in.dict(exclude_unset=True)

    # 若有更新總金額或總期數，重新計算每期與首期本金
    new_total = update_data.get("total_amount", plan.total_amount)
    new_periods = update_data.get("total_periods", plan.total_periods)
    if "total_amount" in update_data or "total_periods" in update_data:
        m_amt, f_amt = calculate_installment_amounts(new_total, new_periods)
        plan.monthly_amount = m_amt
        plan.first_amount = f_amt

    for field, val in update_data.items():
        setattr(plan, field, val)

    # 若已達總期數，自動標記結清
    if plan.current_period >= plan.total_periods:
        plan.status = INSTALLMENT_STATUS_COMPLETED

    db.commit()
    db.refresh(plan)
    return get_installment_plan_detail(db, plan.id, user_id)


def delete_installment_plan(
    db: Session,
    plan_id: int,
    user_id: int,
    delete_transactions: bool = False
) -> Dict[str, Any]:
    """刪除分期計畫 (可選擇是否連同已產生的流水帳一併刪除)"""
    plan = db.query(InstallmentPlan).filter(
        InstallmentPlan.id == plan_id,
        InstallmentPlan.user_id == user_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="找不到指定分期計畫")

    if delete_transactions:
        # 連同流水帳刪除並還原帳戶餘額
        txs = db.query(Transaction).filter(
            Transaction.installment_plan_id == plan.id,
            Transaction.user_id == user_id
        ).all()
        for tx in txs:
            if tx.account_id:
                acc = db.query(Account).filter(Account.id == tx.account_id, Account.user_id == user_id).first()
                if acc:
                    acc.balance += tx.amount
            db.delete(tx)
    else:
        # 保留既有流水帳，僅移除分期計畫關聯
        db.query(Transaction).filter(
            Transaction.installment_plan_id == plan.id,
            Transaction.user_id == user_id
        ).update({"installment_plan_id": None}, synchronize_session=False)

    db.delete(plan)
    db.commit()
    return {"status": "success", "message": f"已刪除分期計畫【{plan.name}】"}


def charge_installment_period(
    db: Session,
    plan_id: int,
    user_id: int,
    target_period: Optional[int] = None
) -> Dict[str, Any]:
    """為分期計畫記帳扣繳下一期（或指定期數）"""
    plan = db.query(InstallmentPlan).filter(
        InstallmentPlan.id == plan_id,
        InstallmentPlan.user_id == user_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="找不到指定分期計畫")

    period_to_charge = target_period or (plan.current_period + 1)
    if period_to_charge > plan.total_periods:
        raise HTTPException(status_code=400, detail="此分期計畫已全數繳清")

    # 檢查該期是否已記帳過，避免重複入帳
    existing_tx = db.query(Transaction).filter(
        Transaction.installment_plan_id == plan.id,
        Transaction.installment_period == period_to_charge,
        Transaction.user_id == user_id
    ).first()
    if existing_tx:
        raise HTTPException(status_code=400, detail=f"第 {period_to_charge} 期已完成記帳，請勿重複扣繳")

    first_amt = plan.first_amount if plan.first_amount is not None else plan.monthly_amount
    p_principal = first_amt if period_to_charge == 1 else plan.monthly_amount
    total_due = round(p_principal + float(plan.monthly_fee or 0.0), 2)
    p_date = compute_installment_period_date(plan.start_date, period_to_charge, plan.billing_day)

    # 扣除帳戶餘額 (若指定帳戶存在)
    acc = None
    if plan.account_id:
        acc = db.query(Account).filter(Account.id == plan.account_id, Account.user_id == user_id).first()
        if acc:
            acc.balance -= total_due

    now_time = datetime.utcnow().time()
    charge_dt = datetime.combine(p_date, now_time)

    tx = Transaction(
        user_id=user_id,
        date=charge_dt,
        amount=total_due,
        tx_type=TX_TYPE_EXPENSE,
        account_id=acc.id if acc else (db.query(Account).filter(Account.user_id == user_id).first().id),
        category=plan.category or CATEGORY_DEFAULT,
        description=f"{plan.name} (第 {period_to_charge}/{plan.total_periods} 期)",
        installment_plan_id=plan.id,
        installment_period=period_to_charge,
        is_reconciled=False
    )
    db.add(tx)
    db.flush()

    # 更新進度
    plan.current_period = max(plan.current_period or 0, period_to_charge)
    if plan.current_period >= plan.total_periods:
        plan.status = INSTALLMENT_STATUS_COMPLETED

    db.commit()
    return {
        "status": "success",
        "message": f"已成功入帳【{plan.name}】第 {period_to_charge}/{plan.total_periods} 期 (NT$ {total_due:,.0f})",
        "transaction_id": tx.id,
        "current_period": plan.current_period,
        "is_completed": plan.status == INSTALLMENT_STATUS_COMPLETED
    }


def settle_installment_in_full(
    db: Session,
    plan_id: int,
    user_id: int,
    account_id: Optional[int] = None
) -> Dict[str, Any]:
    """提前全額結清剩餘分期款項"""
    plan = db.query(InstallmentPlan).filter(
        InstallmentPlan.id == plan_id,
        InstallmentPlan.user_id == user_id
    ).first()
    if not plan:
        raise HTTPException(status_code=404, detail="找不到指定分期計畫")

    if plan.current_period >= plan.total_periods:
        raise HTTPException(status_code=400, detail="此分期計畫已全數繳清")

    metrics = _calculate_plan_metrics(plan)
    remaining_balance = metrics["remaining_amount"]
    remaining_periods = plan.total_periods - plan.current_period

    if remaining_balance <= 0:
        plan.status = INSTALLMENT_STATUS_COMPLETED
        db.commit()
        return {"status": "success", "message": "此分期無剩餘待繳款項，已標記為結清"}

    target_acc_id = account_id or plan.account_id
    acc = None
    if target_acc_id:
        acc = db.query(Account).filter(Account.id == target_acc_id, Account.user_id == user_id).first()
        if acc:
            acc.balance -= remaining_balance

    now = datetime.utcnow()
    tx = Transaction(
        user_id=user_id,
        date=now,
        amount=remaining_balance,
        tx_type=TX_TYPE_EXPENSE,
        account_id=acc.id if acc else (db.query(Account).filter(Account.user_id == user_id).first().id),
        category=plan.category or CATEGORY_DEFAULT,
        description=f"{plan.name} 提前全額結清 (剩餘 {remaining_periods} 期)",
        installment_plan_id=plan.id,
        installment_period=plan.total_periods,
        is_reconciled=False
    )
    db.add(tx)

    plan.current_period = plan.total_periods
    plan.status = INSTALLMENT_STATUS_COMPLETED

    db.commit()
    return {
        "status": "success",
        "message": f"已成功全額結清【{plan.name}】剩餘 {remaining_periods} 期，扣款 NT$ {remaining_balance:,.0f}",
        "transaction_id": tx.id
    }


def get_installment_summary(
    db: Session,
    user_id: int,
    forecast_months: int = 12
) -> Dict[str, Any]:
    """
    分期付款總覽統計：
    1. 進行中計畫筆數
    2. 剩餘未結清債務總額
    3. 當月應繳分期總負擔
    4. 未來 6~12 個月分期現金流預測 (按月呈現每期負擔)
    """
    plans = db.query(InstallmentPlan).filter(InstallmentPlan.user_id == user_id).all()
    active_plans = [p for p in plans if p.status == INSTALLMENT_STATUS_ACTIVE]

    total_debt_remaining = 0.0
    for p in active_plans:
        metrics = _calculate_plan_metrics(p)
        total_debt_remaining += metrics["remaining_amount"]

    total_debt_remaining = round(total_debt_remaining, 2)

    # 產生未來各月份的現金流預測
    today = date.today()
    forecast = []
    current_month_str = today.strftime("%Y-%m")
    current_month_due = 0.0

    for m_offset in range(forecast_months):
        target_m_dt = today + relativedelta(months=m_offset)
        m_str = target_m_dt.strftime("%Y-%m")
        m_year = target_m_dt.year
        m_month = target_m_dt.month

        m_total = 0.0
        details = []

        for p in active_plans:
            first_amt = p.first_amount if p.first_amount is not None else p.monthly_amount
            for period_num in range(p.current_period + 1, p.total_periods + 1):
                p_due = compute_installment_period_date(p.start_date, period_num, p.billing_day)
                if p_due.year == m_year and p_due.month == m_month:
                    p_amt = first_amt if period_num == 1 else p.monthly_amount
                    total_p_due = round(p_amt + float(p.monthly_fee or 0.0), 2)
                    m_total += total_p_due
                    details.append({
                        "plan_id": p.id,
                        "plan_name": p.name,
                        "period": period_num,
                        "total_periods": p.total_periods,
                        "amount": total_p_due
                    })

        m_total = round(m_total, 2)
        if m_str == current_month_str:
            current_month_due = m_total

        forecast.append({
            "month": m_str,
            "year_month": m_str,
            "total_amount": m_total,
            "total_due": m_total,
            "plans_count": len(details),
            "plan_count": len(details),
            "details": details
        })

    return {
        "total_plans_count": len(plans),
        "active_plans_count": len(active_plans),
        "total_debt_remaining": total_debt_remaining,
        "total_remaining_balance": total_debt_remaining,
        "current_month_due": current_month_due,
        "forecast": forecast,
        "monthly_forecast": forecast
    }

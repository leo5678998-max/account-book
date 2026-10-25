from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session

from ..models import RecurringExpense, Account, Transaction
from ..schemas import RecurringExpenseResponse, RecurringExpenseSummary


def build_recurring_response(item: RecurringExpense, current_month_int: Optional[int] = None) -> RecurringExpenseResponse:
    """計算單筆固定開銷之月平攤金額與本月是否到期"""
    if current_month_int is None:
        current_month_int = datetime.utcnow().month

    freq = item.frequency or "MONTHLY"
    if freq == "YEARLY":
        amortized = round(item.amount / 12, 2)
        is_due_this_month = (item.due_month == current_month_int) if item.due_month else False
    else:
        amortized = item.amount
        is_due_this_month = True

    return RecurringExpenseResponse(
        id=item.id,
        name=item.name,
        amount=item.amount,
        category=item.category,
        frequency=freq,
        due_month=item.due_month,
        due_day=item.due_day,
        account_id=item.account_id,
        auto_debit=bool(item.auto_debit),
        is_active=item.is_active,
        notes=item.notes,
        monthly_amortized_amount=amortized,
        is_due_this_month=is_due_this_month,
        last_charged_month=item.last_charged_month,
        created_at=item.created_at or datetime.utcnow(),
        updated_at=item.updated_at or item.created_at or datetime.utcnow()
    )


def execute_auto_recurring_debits(db: Session, user_id: Optional[int] = None) -> int:
    """
    自動檢查並執行所有已到扣款日且開啟 auto_debit 的固定開銷扣款
    回傳已成功執行的扣款筆數
    """
    now = datetime.now()
    current_month_str = now.strftime("%Y-%m")
    current_month_int = now.month
    today_day = now.day

    query = db.query(RecurringExpense).filter(
        RecurringExpense.is_active == True,
        RecurringExpense.auto_debit == True,
        RecurringExpense.account_id != None,
        (RecurringExpense.last_charged_month != current_month_str) | (RecurringExpense.last_charged_month == None)
    )
    if user_id is not None:
        query = query.filter(RecurringExpense.user_id == user_id)

    candidates = query.all()
    executed_count = 0

    for item in candidates:
        # 1. 若為年繳，需比對是否為當前月份
        if item.frequency == "YEARLY":
            if item.due_month and item.due_month != current_month_int:
                continue

        # 2. 比對扣款日 (若有設定 due_day，需今天 >= due_day；若無設定則自當月 1 號起自動扣款)
        if item.due_day and today_day < item.due_day:
            continue

        # 3. 執行扣款記帳
        try:
            charge_single_recurring(db, item, current_month_str, user_id=item.user_id, is_auto=True)
            executed_count += 1
            print(f"[AutoDebit] 已成功自動扣款固定開銷: {item.name} NT$ {item.amount} (user_id={item.user_id})")
        except Exception as e:
            print(f"[AutoDebit] 固定開銷 {item.name} (id={item.id}) 自動扣款失敗: {e}")

    if executed_count > 0:
        db.commit()

    return executed_count


def get_recurring_summary(db: Session, user_id: int = 1) -> RecurringExpenseSummary:
    """彙整指定使用者的所有固定開銷項目、月平攤總額與年繳總額，並自動巡檢執行到期之自動扣款"""
    # 每次讀取清單時先執行自動扣款巡檢，確保存款與記帳狀態最新
    try:
        execute_auto_recurring_debits(db, user_id=user_id)
    except Exception as e:
        print(f"[AutoDebit] 讀取固定開銷時執行自動扣款巡檢發生警告: {e}")

    items = db.query(RecurringExpense).filter(
        RecurringExpense.user_id == user_id
    ).order_by(
        RecurringExpense.due_month.asc().nullslast(),
        RecurringExpense.due_day.asc().nullslast(),
        RecurringExpense.id.asc()
    ).all()
    current_month_int = datetime.utcnow().month

    total_monthly_amortized = 0.0
    total_yearly_amount = 0.0
    monthly_count = 0
    yearly_count = 0
    response_items = []

    for item in items:
        res_item = build_recurring_response(item, current_month_int)
        if item.is_active:
            total_monthly_amortized += res_item.monthly_amortized_amount
            if res_item.frequency == "YEARLY":
                yearly_count += 1
                total_yearly_amount += item.amount
            else:
                monthly_count += 1
        response_items.append(res_item)

    return RecurringExpenseSummary(
        total_monthly_amount=round(total_monthly_amortized, 2),
        total_yearly_amount=round(total_yearly_amount, 2),
        monthly_count=monthly_count,
        yearly_count=yearly_count,
        items=response_items
    )


def charge_single_recurring(
    db: Session,
    item: RecurringExpense,
    current_month_str: str,
    user_id: int = 1,
    is_auto: bool = False
) -> None:
    """對單筆固定開銷執行實際帳戶扣款並產生流水帳"""
    uid = user_id or item.user_id or 1
    acc = None
    if item.account_id:
        acc = db.query(Account).filter(
            Account.id == item.account_id,
            Account.user_id == uid
        ).first()
        if acc:
            acc.balance -= item.amount

    period_desc = "年繳" if item.frequency == "YEARLY" else "固定開銷"
    mode_label = "自動扣款" if is_auto else "扣款"
    tx = Transaction(
        user_id=uid,
        date=datetime.now(),
        amount=item.amount,
        tx_type="EXPENSE",
        account_id=acc.id if acc else None,
        category=item.category,
        description=f"{period_desc}{mode_label}: {item.name} ({current_month_str})"
    )
    db.add(tx)
    item.last_charged_month = current_month_str


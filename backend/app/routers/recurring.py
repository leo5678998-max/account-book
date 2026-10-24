from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, RecurringExpense
from ..schemas import (
    RecurringExpenseCreate,
    RecurringExpenseUpdate,
    RecurringExpenseResponse,
    RecurringExpenseSummary
)
from ..services.auth_service import get_current_user
from ..services.recurring_service import (
    build_recurring_response,
    get_recurring_summary,
    charge_single_recurring
)

router = APIRouter(prefix="/api/recurring-expenses", tags=["RecurringExpenses"])


@router.get("", response_model=RecurringExpenseSummary)
def get_recurring_expenses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得當前使用者所有固定開銷紀錄 (純紀錄與月平攤試算)"""
    return get_recurring_summary(db, user_id=current_user.id)


@router.post("", response_model=RecurringExpenseResponse)
def create_recurring_expense(
    req: RecurringExpenseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """新增固定花費項目 (支援月繳與年繳)"""
    item = RecurringExpense(
        user_id=current_user.id,
        name=req.name,
        amount=req.amount,
        category=req.category,
        frequency=req.frequency or "MONTHLY",
        due_month=req.due_month,
        due_day=req.due_day,
        account_id=req.account_id,
        is_active=req.is_active,
        notes=req.notes
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return build_recurring_response(item)


@router.put("/{expense_id}", response_model=RecurringExpenseResponse)
def update_recurring_expense(
    expense_id: int,
    req: RecurringExpenseUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """修改固定花費項目 (支援月繳與年繳)"""
    item = db.query(RecurringExpense).filter(
        RecurringExpense.id == expense_id,
        RecurringExpense.user_id == current_user.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="找不到此固定花費項目")

    if req.name is not None:
        item.name = req.name
    if req.amount is not None:
        item.amount = req.amount
    if req.category is not None:
        item.category = req.category
    if req.frequency is not None:
        item.frequency = req.frequency
    if req.due_month is not None:
        item.due_month = req.due_month
    if req.due_day is not None:
        item.due_day = req.due_day
    if req.account_id is not None:
        item.account_id = req.account_id
    if req.is_active is not None:
        item.is_active = req.is_active
    if req.notes is not None:
        item.notes = req.notes

    item.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(item)
    return build_recurring_response(item)


@router.delete("/{expense_id}")
def delete_recurring_expense(
    expense_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """刪除固定花費項目"""
    item = db.query(RecurringExpense).filter(
        RecurringExpense.id == expense_id,
        RecurringExpense.user_id == current_user.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="找不到此固定花費項目")
    db.delete(item)
    db.commit()
    return {"status": "success", "message": f"已刪除 {item.name}"}


@router.post("/{expense_id}/charge")
def charge_recurring_expense(
    expense_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """單筆一鍵扣款：從指定帳戶扣除金額並生成支出交易紀錄"""
    item = db.query(RecurringExpense).filter(
        RecurringExpense.id == expense_id,
        RecurringExpense.user_id == current_user.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="找不到此固定花費項目")

    current_month_str = datetime.utcnow().strftime("%Y-%m")
    charge_single_recurring(db, item, current_month_str, user_id=current_user.id)
    db.commit()
    return {"status": "success", "message": f"已完成【{item.name}】扣款記帳 NT$ {item.amount:,.0f}"}


@router.post("/charge-all")
def charge_all_recurring_expenses(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """一鍵扣款本月到期且尚未扣款的所有啟用中固定花費 (月繳 + 本月到期的年繳)"""
    now = datetime.utcnow()
    current_month_int = now.month
    current_month_str = now.strftime("%Y-%m")

    items = db.query(RecurringExpense).filter(
        RecurringExpense.user_id == current_user.id,
        RecurringExpense.is_active == True,
        (RecurringExpense.last_charged_month != current_month_str) | (RecurringExpense.last_charged_month == None)
    ).all()

    due_items = [
        i for i in items
        if (i.frequency != "YEARLY" or i.due_month == current_month_int)
    ]

    if not due_items:
        return {"status": "info", "message": "本月所有到期的固定花費均已扣款完畢，無需扣款。"}

    total_charged = 0.0
    for item in due_items:
        charge_single_recurring(db, item, current_month_str, user_id=current_user.id)
        total_charged += item.amount

    db.commit()
    return {"status": "success", "message": f"已成功扣除 {len(due_items)} 筆本月到期固定花費，總計 NT$ {total_charged:,.0f}"}

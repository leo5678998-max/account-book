from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User
from ..schemas import (
    InstallmentPlanCreate,
    InstallmentPlanUpdate,
    InstallmentPlanResponse,
    InstallmentSummaryResponse,
)
from ..services.auth_service import get_current_user
from ..services.installment_service import (
    get_installment_plans_list,
    get_installment_plan_detail,
    create_installment_plan,
    update_installment_plan,
    delete_installment_plan,
    charge_installment_period,
    settle_installment_in_full,
    get_installment_summary,
)

router = APIRouter(prefix="/api/installments", tags=["Credit Card Installments"])


@router.get("", response_model=List[InstallmentPlanResponse])
def list_installment_plans(
    status: Optional[str] = Query(None, description="依狀態篩選: ACTIVE, COMPLETED, CANCELLED"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得當前使用者的所有信用卡分期計畫清單"""
    return get_installment_plans_list(db, user_id=current_user.id, status_filter=status)


@router.get("/summary", response_model=InstallmentSummaryResponse)
def get_installments_summary_metrics(
    forecast_months: int = Query(12, ge=1, le=24, description="未來現金流預測月數"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得分期統計數據與未來每月現金流負擔預測"""
    return get_installment_summary(db, user_id=current_user.id, forecast_months=forecast_months)


@router.get("/{plan_id}", response_model=InstallmentPlanResponse)
def get_single_installment_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得單一分期計畫詳情（含完整分期攤提日程表）"""
    return get_installment_plan_detail(db, plan_id=plan_id, user_id=current_user.id)


@router.post("", response_model=InstallmentPlanResponse)
def create_new_installment_plan(
    plan_in: InstallmentPlanCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """新增信用卡分期計畫"""
    return create_installment_plan(db, user_id=current_user.id, plan_in=plan_in)


@router.put("/{plan_id}", response_model=InstallmentPlanResponse)
def update_existing_installment_plan(
    plan_id: int,
    plan_in: InstallmentPlanUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """編輯信用卡分期計畫"""
    return update_installment_plan(db, plan_id=plan_id, user_id=current_user.id, plan_in=plan_in)


@router.delete("/{plan_id}")
def delete_plan(
    plan_id: int,
    delete_transactions: bool = Query(False, description="是否連同已產生的流水帳一併刪除並還原餘額"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """刪除分期計畫"""
    return delete_installment_plan(
        db,
        plan_id=plan_id,
        user_id=current_user.id,
        delete_transactions=delete_transactions
    )


@router.post("/{plan_id}/charge-next")
def charge_next_period(
    plan_id: int,
    period: Optional[int] = Query(None, description="指定扣款期數（預設扣繳下一期）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """為分期計畫記帳扣繳下一期（產生實際支出流水帳）"""
    return charge_installment_period(
        db,
        plan_id=plan_id,
        user_id=current_user.id,
        target_period=period
    )


@router.post("/{plan_id}/settle-in-full")
def settle_full_plan(
    plan_id: int,
    account_id: Optional[int] = Query(None, description="結清扣款帳戶（預設為分期計畫關聯帳戶）"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """提前全額結清剩餘分期款項"""
    return settle_installment_in_full(
        db,
        plan_id=plan_id,
        user_id=current_user.id,
        account_id=account_id
    )

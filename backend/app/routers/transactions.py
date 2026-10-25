from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, Transaction
from ..schemas import TransactionCreate, TransactionUpdate, TransactionResponse
from ..services.accounting_service import record_transaction, modify_transaction, remove_transaction
from ..services.auth_service import get_current_user

router = APIRouter(prefix="/api/transactions", tags=["Transactions"])


@router.get("", response_model=List[TransactionResponse])
def get_transactions(
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Transaction).filter(
        Transaction.user_id == current_user.id
    ).order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit).all()


@router.post("", response_model=TransactionResponse)
def create_transaction(
    tx_in: TransactionCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return record_transaction(db, tx_in, user_id=current_user.id)


@router.put("/{tx_id}", response_model=TransactionResponse)
def update_transaction(
    tx_id: int,
    tx_in: TransactionUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """編輯交易紀錄並自動更新帳戶餘額"""
    return modify_transaction(db, tx_id, tx_in, user_id=current_user.id)


@router.delete("/{tx_id}")
def delete_transaction(
    tx_id: int,
    rollback_balance: bool = True,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """刪除指定流水帳，並自動還原該帳戶之餘額"""
    remove_transaction(db, tx_id, rollback_balance=rollback_balance, user_id=current_user.id)
    return {"status": "success", "message": "交易明細已刪除，帳戶餘額已同步還原"}

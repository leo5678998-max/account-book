from typing import List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, Account
from ..schemas import AccountCreate, AccountUpdate, AccountResponse
from ..services.auth_service import get_current_user

router = APIRouter(prefix="/api/accounts", tags=["Accounts"])


@router.get("", response_model=List[AccountResponse])
def get_accounts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Account).filter(
        Account.user_id == current_user.id
    ).order_by(Account.id.asc()).all()


@router.post("", response_model=AccountResponse)
def create_account(
    account_in: AccountCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    if account_in.is_dbs_default_debit:
        db.query(Account).filter(
            Account.user_id == current_user.id
        ).update({Account.is_dbs_default_debit: False})

    account = Account(**account_in.dict(), user_id=current_user.id)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


@router.put("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: int,
    account_in: AccountUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    acc = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="找不到該帳戶")

    update_data = account_in.dict(exclude_unset=True)
    if update_data.get("is_dbs_default_debit"):
        db.query(Account).filter(
            Account.user_id == current_user.id
        ).update({Account.is_dbs_default_debit: False})

    for field, val in update_data.items():
        setattr(acc, field, val)

    db.commit()
    db.refresh(acc)
    return acc


@router.delete("/{account_id}")
def delete_account(
    account_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    acc = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == current_user.id
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="找不到該帳戶")
    db.delete(acc)
    db.commit()
    return {"status": "success", "message": "帳戶已刪除"}

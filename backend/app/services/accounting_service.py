from datetime import datetime
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Account, Transaction, Bill, SystemSetting
from ..schemas import TransactionCreate, SalaryApplyRequest


def get_setting(db: Session, key: str, default: str = "", user_id: int = 1) -> str:
    """從資料庫讀取指定使用者的系統設定值，若無則回傳預設值 (user_id=1 相容舊版無前綴 key)"""
    scoped_key = f"u{user_id}:{key}"
    item = db.query(SystemSetting).filter(SystemSetting.key == scoped_key).first()
    if item and item.value is not None and item.value != "":
        return item.value

    if user_id == 1:
        legacy_item = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if legacy_item and legacy_item.value is not None and legacy_item.value != "":
            return legacy_item.value

    return default


def save_setting(db: Session, key: str, value: str, user_id: int = 1) -> None:
    """新增或更新指定使用者的系統設定值"""
    scoped_key = f"u{user_id}:{key}"
    item = db.query(SystemSetting).filter(SystemSetting.key == scoped_key).first()
    if not item:
        item = SystemSetting(key=scoped_key, value=value, user_id=user_id)
        db.add(item)
    else:
        item.value = value
        item.user_id = user_id

    if user_id == 1:
        legacy_item = db.query(SystemSetting).filter(SystemSetting.key == key).first()
        if legacy_item:
            legacy_item.value = value
            legacy_item.user_id = 1


def get_default_debit_account(db: Session, user_id: int = 1) -> Optional[Account]:
    """取得指定使用者的預設信用卡扣款帳戶"""
    return db.query(Account).filter(
        Account.user_id == user_id,
        Account.is_dbs_default_debit == True
    ).first()


def record_transaction(db: Session, tx_in: TransactionCreate, user_id: int = 1) -> Transaction:
    """新增交易紀錄並同步更新對應帳戶餘額"""
    source_acc = db.query(Account).filter(
        Account.id == tx_in.account_id,
        Account.user_id == user_id
    ).first()
    if not source_acc:
        raise HTTPException(status_code=404, detail="來源帳戶不存在")

    if getattr(tx_in, "affects_balance", True):
        if tx_in.tx_type == "EXPENSE":
            source_acc.balance -= tx_in.amount
        elif tx_in.tx_type == "INCOME":
            source_acc.balance += tx_in.amount
        elif tx_in.tx_type == "TRANSFER":
            if not tx_in.target_account_id:
                raise HTTPException(status_code=400, detail="轉帳必須指定目標帳戶")
            target_acc = db.query(Account).filter(
                Account.id == tx_in.target_account_id,
                Account.user_id == user_id
            ).first()
            if not target_acc:
                raise HTTPException(status_code=404, detail="轉帳目標帳戶不存在")
            source_acc.balance -= tx_in.amount
            target_acc.balance += tx_in.amount

    tx_data = tx_in.dict()
    if not tx_data.get("date"):
        tx_data["date"] = datetime.utcnow()

    tx = Transaction(**tx_data, user_id=user_id)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def remove_transaction(db: Session, tx_id: int, rollback_balance: bool = True, user_id: int = 1) -> None:
    """刪除指定流水帳，並自動還原帳戶餘額與關聯帳單狀態"""
    tx = db.query(Transaction).filter(
        Transaction.id == tx_id,
        Transaction.user_id == user_id
    ).first()
    if not tx:
        raise HTTPException(status_code=404, detail="找不到該筆交易明細")

    if rollback_balance and getattr(tx, "affects_balance", True):
        source_acc = db.query(Account).filter(
            Account.id == tx.account_id,
            Account.user_id == user_id
        ).first()
        if source_acc:
            if tx.tx_type == "EXPENSE":
                source_acc.balance += tx.amount
            elif tx.tx_type == "INCOME":
                source_acc.balance -= tx.amount
            elif tx.tx_type == "TRANSFER":
                source_acc.balance += tx.amount
                if tx.target_account_id:
                    target_acc = db.query(Account).filter(
                        Account.id == tx.target_account_id,
                        Account.user_id == user_id
                    ).first()
                    if target_acc:
                        target_acc.balance -= tx.amount

    if tx.bill_id:
        bill = db.query(Bill).filter(
            Bill.id == tx.bill_id,
            Bill.user_id == user_id
        ).first()
        if bill:
            bill.status = "PENDING"
            bill.paid_date = None
            bill.paid_transaction_id = None

    db.delete(tx)
    db.commit()


def execute_bill_payment(
    db: Session,
    bill: Bill,
    account_id: Optional[int] = None,
    is_auto: bool = False,
    user_id: Optional[int] = None
) -> Account:
    """執行單筆信用卡帳單扣款，產生支出流水帳並標記為 PAID"""
    uid = user_id or bill.user_id or 1
    debit_id = account_id or bill.debit_account_id
    if not debit_id:
        default_acc = get_default_debit_account(db, user_id=uid)
        if default_acc:
            debit_id = default_acc.id

    if not debit_id:
        raise HTTPException(status_code=400, detail="請指定扣款帳戶")

    acc = db.query(Account).filter(
        Account.id == debit_id,
        Account.user_id == uid
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail="扣款帳戶不存在")

    now = datetime.now() if is_auto else datetime.utcnow()
    mode_label = "自動扣款" if is_auto else "手動扣款"

    acc.balance -= bill.total_amount
    tx = Transaction(
        user_id=uid,
        date=now,
        amount=bill.total_amount,
        tx_type="EXPENSE",
        account_id=acc.id,
        category="信用卡費",
        description=f"{bill.bank_name} 信用卡{mode_label} ({bill.statement_month} 帳單)",
        bill_id=bill.id
    )
    db.add(tx)
    db.flush()

    bill.status = "PAID"
    bill.paid_date = now
    bill.paid_transaction_id = tx.id
    bill.debit_account_id = acc.id
    db.commit()
    return acc


def apply_salary_income(db: Session, req: SalaryApplyRequest, user_id: int = 1) -> Optional[int]:
    """更新每月月薪設定，並可選自動記錄一筆薪資入帳"""
    save_setting(db, "MONTHLY_SALARY", str(req.salary_amount), user_id=user_id)

    tx_id = None
    if req.record_transaction and req.account_id:
        acc = db.query(Account).filter(
            Account.id == req.account_id,
            Account.user_id == user_id
        ).first()
        if acc:
            acc.balance += req.salary_amount
            tx = Transaction(
                user_id=user_id,
                date=datetime.utcnow(),
                amount=req.salary_amount,
                tx_type="INCOME",
                account_id=acc.id,
                category="薪資收入",
                description=f"{req.company_name or '公司'} {req.statement_month or ''} 薪資入帳"
            )
            db.add(tx)
            db.flush()
            tx_id = tx.id

    db.commit()
    return tx_id

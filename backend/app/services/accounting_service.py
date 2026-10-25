from datetime import datetime
from typing import Optional
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import Account, Transaction, Bill, SystemSetting
from ..schemas import TransactionCreate, TransactionUpdate, SalaryApplyRequest

# ==============================================================================
# 領域常數定義 (Domain Constants) - 消除魔法字串 (Magic Strings)
# ==============================================================================
TX_TYPE_EXPENSE = "EXPENSE"
TX_TYPE_INCOME = "INCOME"
TX_TYPE_TRANSFER = "TRANSFER"

BILL_STATUS_PAID = "PAID"
BILL_STATUS_PENDING = "PENDING"

CATEGORY_CREDIT_CARD = "信用卡費"
CATEGORY_SALARY = "薪資收入"
CATEGORY_DEFAULT = "其他"

SETTING_MONTHLY_SALARY = "MONTHLY_SALARY"


# ==============================================================================
# 內部輔助函式 (Internal Helpers) - 單一職責與商業邏輯運算解耦
# ==============================================================================
def _get_account_or_404(
    db: Session,
    account_id: int,
    user_id: int,
    detail: str = "帳戶不存在"
) -> Account:
    """單一職責：查詢特定使用者之帳戶實體，若不存在則拋出 404 HTTPException"""
    acc = db.query(Account).filter(
        Account.id == account_id,
        Account.user_id == user_id
    ).first()
    if not acc:
        raise HTTPException(status_code=404, detail=detail)
    return acc


def _calculate_balance_delta(tx_type: str, amount: float, reverse: bool = False) -> float:
    """
    純運算核心邏輯：計算特定交易類型對來源帳戶餘額的增減幅度 (Delta)。
    與資料庫 Session 完全解耦，支援獨立測試。
    - EXPENSE / TRANSFER: 扣除 (-amount)，若 reverse 則補回 (+amount)
    - INCOME: 增加 (+amount)，若 reverse 則扣除 (-amount)
    """
    multiplier = -1 if reverse else 1
    if tx_type == TX_TYPE_EXPENSE or tx_type == TX_TYPE_TRANSFER:
        return -amount * multiplier
    elif tx_type == TX_TYPE_INCOME:
        return amount * multiplier
    return 0.0


def _apply_balance_impact(
    source_acc: Account,
    target_acc: Optional[Account],
    tx_type: str,
    amount: float,
    reverse: bool = False
) -> None:
    """
    單一職責：根據交易類型原子更新帳戶餘額 (支援正向套用或反向還原)：
    - EXPENSE: 扣除/還原來源帳戶
    - INCOME: 增加/還原來源帳戶
    - TRANSFER: 來源與目標帳戶等額反向聯動
    """
    delta = _calculate_balance_delta(tx_type, amount, reverse=reverse)
    source_acc.balance += delta

    if tx_type == TX_TYPE_TRANSFER and target_acc:
        # 轉帳目標帳戶的變動幅度與來源剛好相反
        target_delta = -delta
        target_acc.balance += target_delta


def _rollback_transaction_balance(db: Session, tx: Transaction, user_id: int) -> None:
    """單一職責：還原既有交易紀錄對帳戶餘額的歷史影響"""
    if not getattr(tx, "affects_balance", True):
        return

    source_acc = db.query(Account).filter(
        Account.id == tx.account_id,
        Account.user_id == user_id
    ).first()
    if not source_acc:
        return

    target_acc = None
    if tx.tx_type == TX_TYPE_TRANSFER and tx.target_account_id:
        target_acc = db.query(Account).filter(
            Account.id == tx.target_account_id,
            Account.user_id == user_id
        ).first()

    _apply_balance_impact(
        source_acc=source_acc,
        target_acc=target_acc,
        tx_type=tx.tx_type,
        amount=tx.amount,
        reverse=True
    )


# ==============================================================================
# 公開 API 函式 (Public API Interfaces) - 保持簽章與向下相容 100% 一致
# ==============================================================================
def get_setting(db: Session, key: str, default: str = "", user_id: int = 1) -> str:
    """從資料庫讀取指定使用者的系統設定值，若無則回傳預設值 (user_id=1 相容舊版無前綴 key)"""
    scoped_key = f"u{user_id}:{key}"
    item = db.query(SystemSetting).filter(SystemSetting.key == scoped_key).first()
    if item and item.value is not None and item.value != "":
        return item.value

    # [相容保留 / 潛在 Dead Code] 針對早期 user_id=1 未加 u1: 前綴的舊版資料相容讀取
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

    # [相容保留 / 潛在 Dead Code] 針對早期 user_id=1 的無前綴舊紀錄同步更新
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
    source_acc = _get_account_or_404(db, tx_in.account_id, user_id, detail="來源帳戶不存在")

    target_acc = None
    if tx_in.tx_type == TX_TYPE_TRANSFER:
        if not tx_in.target_account_id:
            raise HTTPException(status_code=400, detail="轉帳必須指定目標帳戶")
        target_acc = _get_account_or_404(db, tx_in.target_account_id, user_id, detail="轉帳目標帳戶不存在")

    if getattr(tx_in, "affects_balance", True):
        _apply_balance_impact(
            source_acc=source_acc,
            target_acc=target_acc,
            tx_type=tx_in.tx_type,
            amount=tx_in.amount,
            reverse=False
        )

    tx_data = tx_in.dict() if hasattr(tx_in, "dict") else tx_in.model_dump()
    if not tx_data.get("date"):
        tx_data["date"] = datetime.utcnow()

    tx = Transaction(**tx_data, user_id=user_id)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx


def modify_transaction(
    db: Session,
    tx_id: int,
    tx_in: TransactionUpdate,
    user_id: int = 1
) -> Transaction:
    """編輯交易紀錄，並自動還原舊帳戶差額與套用新扣款"""
    tx = db.query(Transaction).filter(
        Transaction.id == tx_id,
        Transaction.user_id == user_id
    ).first()
    if not tx:
        raise HTTPException(status_code=404, detail="找不到該筆交易紀錄")

    # 1. 還原舊交易對帳戶餘額的影響
    _rollback_transaction_balance(db, tx, user_id)

    # 2. 驗證新帳戶與轉帳設定
    new_source_acc = _get_account_or_404(db, tx_in.account_id, user_id, detail="來源帳戶不存在")
    new_target_acc = None
    if tx_in.tx_type == TX_TYPE_TRANSFER:
        if not tx_in.target_account_id:
            raise HTTPException(status_code=400, detail="轉帳必須指定目標帳戶")
        new_target_acc = _get_account_or_404(db, tx_in.target_account_id, user_id, detail="轉帳目標帳戶不存在")

    # 3. 套用新交易對帳戶餘額的影響
    new_affects_balance = getattr(tx_in, "affects_balance", True)
    if new_affects_balance:
        _apply_balance_impact(
            source_acc=new_source_acc,
            target_acc=new_target_acc,
            tx_type=tx_in.tx_type,
            amount=tx_in.amount,
            reverse=False
        )

    # 4. 更新交易紀錄欄位
    tx.amount = tx_in.amount
    tx.tx_type = tx_in.tx_type
    tx.account_id = tx_in.account_id
    tx.target_account_id = tx_in.target_account_id if tx_in.tx_type == TX_TYPE_TRANSFER else None
    tx.category = tx_in.category or CATEGORY_DEFAULT
    tx.description = tx_in.description
    if tx_in.date:
        tx.date = tx_in.date
    tx.affects_balance = new_affects_balance

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

    # 1. 還原餘額
    if rollback_balance:
        _rollback_transaction_balance(db, tx, user_id)

    # 2. 若為扣繳帳單產生的流水帳，重設帳單為未繳狀態
    if tx.bill_id:
        bill = db.query(Bill).filter(
            Bill.id == tx.bill_id,
            Bill.user_id == user_id
        ).first()
        if bill:
            bill.status = BILL_STATUS_PENDING
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

    acc = _get_account_or_404(db, debit_id, uid, detail="扣款帳戶不存在")

    now = datetime.now() if is_auto else datetime.utcnow()
    mode_label = "自動扣款" if is_auto else "手動扣款"

    acc.balance -= bill.total_amount
    tx = Transaction(
        user_id=uid,
        date=now,
        amount=bill.total_amount,
        tx_type=TX_TYPE_EXPENSE,
        account_id=acc.id,
        category=CATEGORY_CREDIT_CARD,
        description=f"{bill.bank_name} 信用卡{mode_label} ({bill.statement_month} 帳單)",
        bill_id=bill.id
    )
    db.add(tx)
    db.flush()

    bill.status = BILL_STATUS_PAID
    bill.paid_date = now
    bill.paid_transaction_id = tx.id
    bill.debit_account_id = acc.id
    db.commit()
    return acc


def apply_salary_income(db: Session, req: SalaryApplyRequest, user_id: int = 1) -> Optional[int]:
    """更新每月月薪設定，並可選自動記錄一筆薪資入帳"""
    save_setting(db, SETTING_MONTHLY_SALARY, str(req.salary_amount), user_id=user_id)

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
                tx_type=TX_TYPE_INCOME,
                account_id=acc.id,
                category=CATEGORY_SALARY,
                description=f"{req.company_name or '公司'} {req.statement_month or ''} 薪資入帳"
            )
            db.add(tx)
            db.flush()
            tx_id = tx.id

    db.commit()
    return tx_id

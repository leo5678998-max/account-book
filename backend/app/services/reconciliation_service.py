from datetime import datetime, date, timedelta
from typing import Optional, List, Dict, Any
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from ..models import Bill, Transaction, Account
from ..schemas import (
    ReconciliationOverview,
    ReconciliationItem,
    ReconciliationQuickAddRequest,
)

SETTLEMENT_MODE_TRANSFER = "TRANSFER"
SETTLEMENT_MODE_EXPENSE = "EXPENSE"
CATEGORY_CREDIT_CARD = "信用卡費"
TX_TYPE_EXPENSE = "EXPENSE"
TX_TYPE_REFUND = "REFUND"
TX_TYPE_TRANSFER = "TRANSFER"
BILL_STATUS_PAID = "PAID"
BILL_STATUS_PENDING = "PENDING"


def find_matching_credit_account(db: Session, bill: Bill, user_id: int) -> Optional[Account]:
    """根據帳單資訊智慧尋找對應的信用卡資產帳戶"""
    if bill.credit_account_id:
        acc = db.query(Account).filter(
            Account.id == bill.credit_account_id,
            Account.user_id == user_id
        ).first()
        if acc:
            return acc

    user_accounts = db.query(Account).filter(Account.user_id == user_id).all()
    if not user_accounts:
        return None

    credit_accounts = [a for a in user_accounts if (a.account_type or "").upper() == "CREDIT"]
    bank_name = (bill.bank_name or "").lower()
    common_keywords = ["星展", "國泰", "cube", "玉山", "台新", "richart", "富邦", "聯邦", "永豐", "中信", "中國信託", "匯豐", "花旗"]

    # 1. 優先在 CREDIT 類型帳戶中比對關鍵字或名稱
    for ca in credit_accounts:
        c_name = (ca.name or "").lower()
        for kw in common_keywords:
            if kw in bank_name and kw in c_name:
                return ca
        if bank_name in c_name or c_name in bank_name:
            return ca

    # 2. 若 CREDIT 帳戶中找不到，比對所有帳戶 (因為使用者常將常用銀行設為一般活儲/日常帳戶，如「星展」)
    for a in user_accounts:
        a_name = (a.name or "").lower()
        for kw in common_keywords:
            if kw in bank_name and kw in a_name:
                return a
        if (bank_name and bank_name in a_name) or (a_name and a_name in bank_name):
            return a

    # 3. 若帳單有綁定 debit_account_id
    if bill.debit_account_id:
        acc = db.query(Account).filter(Account.id == bill.debit_account_id, Account.user_id == user_id).first()
        if acc:
            return acc

    # 4. 若只有一個信用卡帳戶，預設自動採用
    if len(credit_accounts) == 1:
        return credit_accounts[0]

    return None


def calculate_default_cycle_range(bill: Bill) -> tuple[date, date]:
    """計算帳單預設之對帳週期起訖日，確保涵蓋帳單週期、月份與繳款截止日"""
    candidates_end = []
    if bill.statement_date:
        candidates_end.append(bill.statement_date)
    if bill.due_date:
        candidates_end.append(bill.due_date)

    month_start = None
    if bill.statement_month and len(bill.statement_month) >= 7:
        try:
            parts = bill.statement_month.split("-")
            y, m = int(parts[0]), int(parts[1])
            month_start = date(y, m, 1)
            if m == 12:
                candidates_end.append(date(y + 1, 1, 1) - timedelta(days=1))
            else:
                candidates_end.append(date(y, m + 1, 1) - timedelta(days=1))
        except Exception:
            pass

    if candidates_end:
        end_d = max(candidates_end)
    else:
        end_d = date.today()

    if bill.statement_start_date:
        start_d = bill.statement_start_date
    elif bill.statement_date:
        start_d = bill.statement_date - timedelta(days=30)
    elif month_start:
        start_d = month_start
    elif bill.due_date:
        start_d = bill.due_date - timedelta(days=45)
    else:
        start_d = end_d - timedelta(days=30)

    # 確保月份起始日也能涵蓋進來
    if month_start and month_start < start_d:
        start_d = month_start

    return start_d, end_d


def get_bill_reconciliation_overview(
    db: Session,
    bill_id: int,
    user_id: int,
    credit_account_id: Optional[int] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    include_all_accounts: bool = False
) -> Dict[str, Any]:
    """取得特定帳單的對帳總覽與候選交易清單"""
    bill = db.query(Bill).filter(Bill.id == bill_id, Bill.user_id == user_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到指定帳單")

    # 1. 決定信用卡帳戶
    target_credit_acc = None
    if credit_account_id:
        target_credit_acc = db.query(Account).filter(
            Account.id == credit_account_id,
            Account.user_id == user_id
        ).first()
    elif not include_all_accounts:
        target_credit_acc = find_matching_credit_account(db, bill, user_id)

    # 2. 決定對帳日期區間
    def_start, def_end = calculate_default_cycle_range(bill)
    cycle_start = start_date or def_start
    cycle_end = end_date or def_end

    start_dt = datetime.combine(cycle_start, datetime.min.time())
    end_dt = datetime.combine(cycle_end, datetime.max.time())

    # 3. 撈取候選交易：
    # 包含：
    # A. 已經關聯至此帳單 (tx.bill_id == bill.id) 的交易（無論日期或帳戶）
    # B. 在指定帳戶（或所有信用卡）且在該週期區間內的支出與退款
    query = db.query(Transaction).filter(
        Transaction.user_id == user_id,
        Transaction.tx_type.in_([TX_TYPE_EXPENSE, TX_TYPE_REFUND])
    )

    filters = [Transaction.bill_id == bill.id]

    account_filter = None
    if target_credit_acc and not include_all_accounts:
        account_filter = (Transaction.account_id == target_credit_acc.id)
    elif not include_all_accounts:
        # 若無特定帳戶，抓取所有 CREDIT 類型帳戶
        credit_acc_ids = [
            a.id for a in db.query(Account).filter(
                Account.user_id == user_id,
                Account.account_type == "CREDIT"
            ).all()
        ]
        if credit_acc_ids:
            account_filter = Transaction.account_id.in_(credit_acc_ids)

    date_filter = and_(Transaction.date >= start_dt, Transaction.date <= end_dt)
    if account_filter is not None:
        filters.append(and_(account_filter, date_filter))
    else:
        filters.append(date_filter)

    txs = query.filter(or_(*filters)).order_by(Transaction.date.desc(), Transaction.id.desc()).all()

    # 自動寬容容錯：若依特定卡片過濾查無明細，但同週期內其他帳戶有支出明細，自動擴大納入候選
    if len(txs) == 0 and not include_all_accounts:
        fallback_txs = query.filter(
            or_(
                Transaction.bill_id == bill.id,
                and_(Transaction.date >= start_dt, Transaction.date <= end_dt)
            )
        ).order_by(Transaction.date.desc(), Transaction.id.desc()).all()
        if fallback_txs:
            txs = fallback_txs

    # 建立帳戶名稱快取
    acc_map = {a.id: a.name for a in db.query(Account).filter(Account.user_id == user_id).all()}

    # 4. 計算核對統計
    tx_items: List[ReconciliationItem] = []
    reconciled_sum = 0.0
    reconciled_count = 0
    unreconciled_count = 0

    for tx in txs:
        # 判定是否已對帳
        is_rec = bool(tx.is_reconciled or tx.bill_id == bill.id)
        amt = float(tx.amount or 0.0)

        # 退款在帳單中視為折抵（負項），支出為正項
        if is_rec:
            reconciled_count += 1
            if tx.tx_type == TX_TYPE_REFUND:
                reconciled_sum -= abs(amt)
            else:
                reconciled_sum += amt
        else:
            unreconciled_count += 1

        tx_items.append(ReconciliationItem(
            id=tx.id,
            date=tx.date or datetime.utcnow(),
            amount=amt,
            tx_type=tx.tx_type,
            category=tx.category or "其他",
            description=tx.description or "",
            account_id=tx.account_id,
            account_name=acc_map.get(tx.account_id, "未知帳戶"),
            is_reconciled=is_rec,
            reconciled_at=tx.reconciled_at,
            bill_id=tx.bill_id
        ))

    reconciled_sum = round(reconciled_sum, 2)
    difference = round(float(bill.total_amount or 0.0) - reconciled_sum, 2)
    is_balanced = abs(difference) < 0.01

    return {
        "bill_id": bill.id,
        "bank_name": bill.bank_name,
        "statement_month": bill.statement_month,
        "statement_date": bill.statement_date,
        "statement_start_date": cycle_start,
        "statement_end_date": cycle_end,
        "due_date": bill.due_date,
        "bill_total_amount": float(bill.total_amount or 0.0),
        "bill_status": bill.status,
        "debit_account_id": bill.debit_account_id,
        "credit_account_id": target_credit_acc.id if target_credit_acc else None,
        "credit_account_name": target_credit_acc.name if target_credit_acc else None,
        "matched_count": len(tx_items),
        "reconciled_count": reconciled_count,
        "unreconciled_count": unreconciled_count,
        "reconciled_amount": reconciled_sum,
        "difference": difference,
        "is_balanced": is_balanced,
        "transactions": tx_items
    }


def batch_update_reconciliation_checks(
    db: Session,
    bill_id: int,
    user_id: int,
    transaction_ids: List[int],
    is_reconciled: bool = True
) -> Dict[str, Any]:
    """批次勾選或取消對帳標記"""
    bill = db.query(Bill).filter(Bill.id == bill_id, Bill.user_id == user_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到指定帳單")

    if not transaction_ids:
        return {"status": "success", "updated_count": 0}

    txs = db.query(Transaction).filter(
        Transaction.id.in_(transaction_ids),
        Transaction.user_id == user_id
    ).all()

    now = datetime.utcnow()
    for tx in txs:
        tx.is_reconciled = is_reconciled
        if is_reconciled:
            tx.bill_id = bill.id
            tx.reconciled_at = now
        else:
            if tx.bill_id == bill.id:
                tx.bill_id = None
                tx.reconciled_at = None

    db.commit()
    return {"status": "success", "updated_count": len(txs)}


def quick_add_reconciliation_transaction(
    db: Session,
    bill_id: int,
    user_id: int,
    req: ReconciliationQuickAddRequest
) -> Dict[str, Any]:
    """在對帳畫面快捷補登漏記的刷卡或退款消費，並直接標記為已核銷"""
    bill = db.query(Bill).filter(Bill.id == bill_id, Bill.user_id == user_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到指定帳單")

    # 決定目標信用卡帳戶
    acc_id = req.credit_account_id or bill.credit_account_id
    if not acc_id:
        matched = find_matching_credit_account(db, bill, user_id)
        if matched:
            acc_id = matched.id
        else:
            first_acc = db.query(Account).filter(Account.user_id == user_id).first()
            if not first_acc:
                raise HTTPException(status_code=400, detail="請先建立至少一個帳戶")
            acc_id = first_acc.id

    acc = db.query(Account).filter(Account.id == acc_id, Account.user_id == user_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="帳戶不存在")

    now = req.date or (datetime.combine(bill.statement_date, datetime.min.time()) if bill.statement_date else datetime.utcnow())
    tx_amt = abs(float(req.amount))
    tx_type = req.tx_type.upper() if req.tx_type else TX_TYPE_EXPENSE

    # 調整餘額 (EXPENSE 減餘額, REFUND 加餘額)
    if tx_type == TX_TYPE_REFUND:
        acc.balance += tx_amt
    else:
        acc.balance -= tx_amt

    new_tx = Transaction(
        user_id=user_id,
        date=now,
        amount=tx_amt,
        tx_type=tx_type,
        account_id=acc.id,
        category=req.category or "其他",
        description=f"[對帳補登] {req.description or bill.bank_name}",
        bill_id=bill.id,
        is_reconciled=True,
        reconciled_at=datetime.utcnow()
    )
    db.add(new_tx)
    db.commit()
    db.refresh(new_tx)

    return {
        "status": "success",
        "message": f"已補登明細 NT$ {tx_amt:,.0f} 並加入本期對帳清單",
        "transaction_id": new_tx.id
    }


def execute_bill_reconciliation_settlement(
    db: Session,
    bill_id: int,
    user_id: int,
    debit_account_id: int,
    credit_account_id: Optional[int] = None,
    reconciled_transaction_ids: Optional[List[int]] = None,
    settlement_mode: str = SETTLEMENT_MODE_TRANSFER,
    note: Optional[str] = None
) -> Dict[str, Any]:
    """
    一鍵核銷結算並扣繳帳單：
    1. 將勾選的交易全數標記為 is_reconciled = True、關聯此 bill_id
    2. 從 debit_account 執行扣款
    3. 依 settlement_mode (TRANSFER 或 EXPENSE) 建立結算交易流水帳，若為 TRANSFER 則清償信用卡負債而不重複認列月開銷
    4. 標記帳單狀態為 PAID
    """
    bill = db.query(Bill).filter(Bill.id == bill_id, Bill.user_id == user_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到指定帳單")

    debit_acc = db.query(Account).filter(Account.id == debit_account_id, Account.user_id == user_id).first()
    if not debit_acc:
        raise HTTPException(status_code=404, detail="扣款帳戶不存在")

    now = datetime.utcnow()

    # 1. 標記勾選明細為已核對
    if reconciled_transaction_ids:
        txs = db.query(Transaction).filter(
            Transaction.id.in_(reconciled_transaction_ids),
            Transaction.user_id == user_id
        ).all()
        for t in txs:
            t.is_reconciled = True
            t.bill_id = bill.id
            t.reconciled_at = now

    # 2. 扣除存款帳戶餘額
    bill_amount = float(bill.total_amount or 0.0)
    debit_acc.balance -= bill_amount

    # 3. 處理結算流水帳
    credit_acc = None
    target_cid = credit_account_id or bill.credit_account_id
    if target_cid:
        credit_acc = db.query(Account).filter(Account.id == target_cid, Account.user_id == user_id).first()

    settlement_tx = None
    if settlement_mode.upper() == SETTLEMENT_MODE_TRANSFER and credit_acc:
        # 清償信用卡債模式：資金從活儲轉至信用卡，回補信用卡負債餘額，不重複計入月開銷
        credit_acc.balance += bill_amount
        settlement_tx = Transaction(
            user_id=user_id,
            date=now,
            amount=bill_amount,
            tx_type=TX_TYPE_TRANSFER,
            account_id=debit_acc.id,
            target_account_id=credit_acc.id,
            category=CATEGORY_CREDIT_CARD,
            description=f"繳納 {bill.bank_name} 信用卡費 ({bill.statement_month or ''} 帳單核銷)",
            bill_id=bill.id,
            is_reconciled=True,
            reconciled_at=now
        )
    else:
        # 直接支出扣款模式：列為「信用卡費」總額開銷
        settlement_tx = Transaction(
            user_id=user_id,
            date=now,
            amount=bill_amount,
            tx_type=TX_TYPE_EXPENSE,
            account_id=debit_acc.id,
            category=CATEGORY_CREDIT_CARD,
            description=f"{bill.bank_name} 信用卡費核銷扣款 ({bill.statement_month or ''} 帳單)",
            bill_id=bill.id,
            is_reconciled=True,
            reconciled_at=now
        )

    db.add(settlement_tx)
    db.flush()

    # 4. 更新帳單狀態
    bill.status = BILL_STATUS_PAID
    bill.paid_date = now
    bill.paid_transaction_id = settlement_tx.id
    bill.debit_account_id = debit_acc.id
    if target_cid:
        bill.credit_account_id = target_cid

    db.commit()

    return {
        "status": "success",
        "message": f"帳單已完成對帳核銷！已從【{debit_acc.name}】扣款 NT$ {bill_amount:,.0f}",
        "paid_transaction_id": settlement_tx.id,
        "reconciled_items_count": len(reconciled_transaction_ids or [])
    }

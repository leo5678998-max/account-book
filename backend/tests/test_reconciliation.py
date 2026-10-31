import unittest
from datetime import datetime, date, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, User, Account, Transaction, Bill
from backend.app.schemas import (
    ReconciliationQuickAddRequest,
    ReconciliationClearRequest,
)
from backend.app.services.reconciliation_service import (
    get_bill_reconciliation_overview,
    batch_update_reconciliation_checks,
    quick_add_reconciliation_transaction,
    execute_bill_reconciliation_settlement,
    TX_TYPE_EXPENSE,
    TX_TYPE_REFUND,
    TX_TYPE_TRANSFER,
    SETTLEMENT_MODE_TRANSFER,
    SETTLEMENT_MODE_EXPENSE,
)


class TestReconciliationService(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # 建立測試使用者
        self.user = User(
            id=1,
            username="testuser",
            password_hash="testhash",
            display_name="測試使用者"
        )
        self.db.add(self.user)

        # 建立活存帳戶 (扣款用)
        self.savings_acc = Account(
            id=1,
            user_id=1,
            name="台新活儲",
            account_type="SAVINGS",
            balance=50000.0
        )
        # 建立信用卡帳戶
        self.credit_acc = Account(
            id=2,
            user_id=1,
            name="星展 eco 永續卡",
            account_type="CREDIT",
            balance=0.0
        )
        self.db.add_all([self.savings_acc, self.credit_acc])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_get_reconciliation_overview(self):
        # 1. 建立帳單
        bill = Bill(
            user_id=1,
            bank_name="星展銀行",
            statement_month="2026-10",
            statement_date=date(2026, 10, 20),
            statement_start_date=date(2026, 9, 21),
            due_date=date(2026, 11, 5),
            total_amount=3500.0,
            status="PENDING",
            debit_account_id=self.savings_acc.id,
            credit_account_id=self.credit_acc.id
        )
        self.db.add(bill)
        self.db.commit()
        self.db.refresh(bill)

        # 2. 建立消費紀錄（一筆在週期內，一筆在週期外）
        t1 = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=2000.0,
            tx_type=TX_TYPE_EXPENSE,
            category="日常採買",
            description="全聯",
            date=datetime(2026, 10, 5, 12, 0),
            is_reconciled=False
        )
        t2 = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=1500.0,
            tx_type=TX_TYPE_EXPENSE,
            category="飲食",
            description="餐廳聚餐",
            date=datetime(2026, 10, 10, 19, 0),
            is_reconciled=False
        )
        t_outside = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=999.0,
            tx_type=TX_TYPE_EXPENSE,
            category="娛樂",
            description="下期消費",
            date=datetime(2026, 11, 1, 10, 0),
            is_reconciled=False
        )
        self.db.add_all([t1, t2, t_outside])
        self.db.commit()

        # 查詢對帳總覽
        overview = get_bill_reconciliation_overview(
            db=self.db,
            bill_id=bill.id,
            user_id=1
        )

        self.assertEqual(overview["bill_id"], bill.id)
        self.assertEqual(overview["bill_total_amount"], 3500.0)
        self.assertEqual(overview["matched_count"], 2) # t1, t2 在區間內
        self.assertEqual(overview["reconciled_count"], 0)
        self.assertEqual(overview["difference"], 3500.0)
        self.assertFalse(overview["is_balanced"])

    def test_batch_check_and_balance(self):
        bill = Bill(
            user_id=1,
            bank_name="星展銀行",
            statement_month="2026-10",
            statement_date=date(2026, 10, 20),
            due_date=date(2026, 11, 5),
            total_amount=3000.0,
            status="PENDING",
            credit_account_id=self.credit_acc.id
        )
        self.db.add(bill)
        self.db.commit()

        t1 = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=2000.0,
            tx_type=TX_TYPE_EXPENSE,
            date=datetime(2026, 10, 2)
        )
        t2 = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=1000.0,
            tx_type=TX_TYPE_EXPENSE,
            date=datetime(2026, 10, 3)
        )
        self.db.add_all([t1, t2])
        self.db.commit()

        # 批次標記 t1, t2 已核對
        batch_update_reconciliation_checks(self.db, bill.id, 1, [t1.id, t2.id], is_reconciled=True)

        overview = get_bill_reconciliation_overview(self.db, bill.id, 1)
        self.assertEqual(overview["reconciled_count"], 2)
        self.assertEqual(overview["reconciled_amount"], 3000.0)
        self.assertEqual(overview["difference"], 0.0)
        self.assertTrue(overview["is_balanced"])

    def test_quick_add_missing_transaction(self):
        bill = Bill(
            user_id=1,
            bank_name="星展銀行",
            due_date=date(2026, 11, 5),
            total_amount=500.0,
            credit_account_id=self.credit_acc.id
        )
        self.db.add(bill)
        self.db.commit()

        req = ReconciliationQuickAddRequest(
            amount=500.0,
            category="交通",
            description="中油加油漏記",
            tx_type="EXPENSE"
        )
        res = quick_add_reconciliation_transaction(self.db, bill.id, 1, req)
        self.assertEqual(res["status"], "success")

        # 驗證信用卡餘額已扣除，且明細直接為已對帳
        self.assertEqual(self.credit_acc.balance, -500.0)
        overview = get_bill_reconciliation_overview(self.db, bill.id, 1)
        self.assertEqual(overview["reconciled_count"], 1)
        self.assertTrue(overview["is_balanced"])

    def test_reconciliation_settlement_transfer(self):
        # 刷卡 1500 (信用卡餘額 -1500)
        self.credit_acc.balance = -1500.0
        bill = Bill(
            user_id=1,
            bank_name="星展銀行",
            statement_month="2026-10",
            due_date=date(2026, 11, 5),
            total_amount=1500.0,
            status="PENDING",
            debit_account_id=self.savings_acc.id,
            credit_account_id=self.credit_acc.id
        )
        self.db.add(bill)
        self.db.commit()

        t1 = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=1500.0,
            tx_type=TX_TYPE_EXPENSE,
            date=datetime(2026, 10, 5)
        )
        self.db.add(t1)
        self.db.commit()

        # 執行結算核銷（以 TRANSFER 模式）
        settle_res = execute_bill_reconciliation_settlement(
            db=self.db,
            bill_id=bill.id,
            user_id=1,
            debit_account_id=self.savings_acc.id,
            credit_account_id=self.credit_acc.id,
            reconciled_transaction_ids=[t1.id],
            settlement_mode=SETTLEMENT_MODE_TRANSFER
        )

        self.assertEqual(settle_res["status"], "success")
        self.assertEqual(bill.status, "PAID")
        # 活存扣除 1500: 50000 - 1500 = 48500
        self.assertEqual(self.savings_acc.balance, 48500.0)
        # 信用卡負債清償: -1500 + 1500 = 0
        self.assertEqual(self.credit_acc.balance, 0.0)

        # 驗證 t1 狀態為已對帳
        self.assertTrue(t1.is_reconciled)
        self.assertEqual(t1.bill_id, bill.id)

    def test_reconciliation_with_refund(self):
        bill = Bill(
            user_id=1,
            bank_name="星展銀行",
            statement_month="2026-10",
            due_date=date(2026, 11, 5),
            total_amount=1200.0, # 2000 - 800 退款 = 1200
            status="PENDING",
            credit_account_id=self.credit_acc.id
        )
        self.db.add(bill)
        self.db.commit()

        t_exp = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=2000.0,
            tx_type=TX_TYPE_EXPENSE,
            date=datetime(2026, 10, 2)
        )
        t_ref = Transaction(
            user_id=1,
            account_id=self.credit_acc.id,
            amount=800.0,
            tx_type=TX_TYPE_REFUND,
            date=datetime(2026, 10, 4)
        )
        self.db.add_all([t_exp, t_ref])
        self.db.commit()

        batch_update_reconciliation_checks(self.db, bill.id, 1, [t_exp.id, t_ref.id], is_reconciled=True)

        overview = get_bill_reconciliation_overview(self.db, bill.id, 1)
        # 2000 - 800 = 1200，完全與帳單 1200 吻合！
        self.assertEqual(overview["reconciled_amount"], 1200.0)
        self.assertEqual(overview["difference"], 0.0)
        self.assertTrue(overview["is_balanced"])


if __name__ == "__main__":
    unittest.main()

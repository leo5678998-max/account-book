import unittest
import os
import sys
from datetime import datetime

# Set up module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.core.database import Base
from app.models import User, Account, Transaction, Bill, SystemSetting
from app.schemas import TransactionCreate, TransactionUpdate, SalaryApplyRequest
from app.services.accounting_service import (
    get_setting,
    save_setting,
    get_default_debit_account,
    record_transaction,
    modify_transaction,
    remove_transaction,
    execute_bill_payment,
    apply_salary_income
)


class TestAccountingService(unittest.TestCase):
    def setUp(self):
        # Use an in-memory SQLite database for unit tests
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Seed test user
        self.user = User(id=1, username="testuser", password_hash="hash")
        self.db.add(self.user)

        # Seed test accounts
        self.acc1 = Account(id=1, user_id=1, name="主帳戶", balance=10000.0, is_dbs_default_debit=True)
        self.acc2 = Account(id=2, user_id=1, name="副帳戶", balance=5000.0)
        self.db.add_all([self.acc1, self.acc2])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_settings_crud(self):
        save_setting(self.db, "MY_KEY", "VAL123", user_id=1)
        self.db.commit()
        val = get_setting(self.db, "MY_KEY", default="DEF", user_id=1)
        self.assertEqual(val, "VAL123")

    def test_record_expense_and_income(self):
        # Expense
        tx_in = TransactionCreate(
            account_id=1,
            amount=2000.0,
            tx_type="EXPENSE",
            category="餐飲",
            description="午餐"
        )
        tx = record_transaction(self.db, tx_in, user_id=1)
        self.assertEqual(tx.amount, 2000.0)
        self.assertEqual(self.acc1.balance, 8000.0)

        # Income
        tx_in_inc = TransactionCreate(
            account_id=1,
            amount=5000.0,
            tx_type="INCOME",
            category="薪資收入",
            description="獎金"
        )
        tx2 = record_transaction(self.db, tx_in_inc, user_id=1)
        self.assertEqual(self.acc1.balance, 13000.0)

    def test_record_transfer(self):
        tx_in = TransactionCreate(
            account_id=1,
            target_account_id=2,
            amount=3000.0,
            tx_type="TRANSFER",
            category="轉帳",
            description="轉帳測試"
        )
        tx = record_transaction(self.db, tx_in, user_id=1)
        self.assertEqual(self.acc1.balance, 7000.0)
        self.assertEqual(self.acc2.balance, 8000.0)

    def test_modify_transaction(self):
        # Create an expense of 1000 on acc1 (balance becomes 9000)
        tx_in = TransactionCreate(
            account_id=1,
            amount=1000.0,
            tx_type="EXPENSE",
            category="購物"
        )
        tx = record_transaction(self.db, tx_in, user_id=1)
        self.assertEqual(self.acc1.balance, 9000.0)

        # Update to expense of 2500 on acc1 (balance should become 7500)
        tx_up = TransactionUpdate(
            account_id=1,
            amount=2500.0,
            tx_type="EXPENSE",
            category="購物",
            description="修改測試"
        )
        modified = modify_transaction(self.db, tx.id, tx_up, user_id=1)
        self.assertEqual(modified.amount, 2500.0)
        self.assertEqual(self.acc1.balance, 7500.0)

    def test_remove_transaction_and_restore_balance(self):
        tx_in = TransactionCreate(
            account_id=1,
            amount=1500.0,
            tx_type="EXPENSE",
            category="娛樂"
        )
        tx = record_transaction(self.db, tx_in, user_id=1)
        self.assertEqual(self.acc1.balance, 8500.0)

        remove_transaction(self.db, tx.id, rollback_balance=True, user_id=1)
        self.assertEqual(self.acc1.balance, 10000.0)
        self.assertIsNone(self.db.query(Transaction).filter(Transaction.id == tx.id).first())

    def test_refund_transaction_workflow(self):
        # 1. 原始支出 2000 元 (帳戶餘額從 10000 扣減至 8000)
        tx_in = TransactionCreate(
            account_id=1,
            amount=2000.0,
            tx_type="EXPENSE",
            category="日常採買",
            description="購買外套"
        )
        orig_tx = record_transaction(self.db, tx_in, user_id=1)
        self.assertEqual(self.acc1.balance, 8000.0)

        # 2. 進行退款 800 元 (負支出，帳戶餘額應增加回補至 8800)
        refund_in = TransactionCreate(
            account_id=1,
            amount=800.0,
            tx_type="REFUND",
            category="日常採買",
            description="[退款] 購買外套",
            related_transaction_id=orig_tx.id
        )
        refund_tx = record_transaction(self.db, refund_in, user_id=1)
        self.assertEqual(refund_tx.amount, 800.0)
        self.assertEqual(refund_tx.tx_type, "REFUND")
        self.assertEqual(refund_tx.related_transaction_id, orig_tx.id)
        self.assertEqual(self.acc1.balance, 8800.0)

        # 3. 刪除退款紀錄 (帳戶餘額應扣回 800 至 8000)
        remove_transaction(self.db, refund_tx.id, rollback_balance=True, user_id=1)
        self.assertEqual(self.acc1.balance, 8000.0)

    def test_execute_bill_payment(self):
        bill = Bill(
            user_id=1,
            bank_name="星展銀行",
            statement_month="2026-10",
            due_date=datetime.utcnow().date(),
            total_amount=3500.0,
            status="PENDING",
            debit_account_id=1
        )
        self.db.add(bill)
        self.db.commit()

        acc = execute_bill_payment(self.db, bill, user_id=1)
        self.assertEqual(bill.status, "PAID")
        self.assertEqual(acc.balance, 6500.0)
        self.assertIsNotNone(bill.paid_transaction_id)

    def test_modify_transaction_change_type_and_account(self):
        # 1. Create EXPENSE 1000 on acc1 (acc1: 10000 -> 9000)
        tx_in = TransactionCreate(
            account_id=1,
            amount=1000.0,
            tx_type="EXPENSE",
            category="測試"
        )
        tx = record_transaction(self.db, tx_in, user_id=1)
        self.assertEqual(self.acc1.balance, 9000.0)

        # 2. Change to INCOME 2000 on acc2 (acc1 should restore to 10000, acc2 should become 5000 + 2000 = 7000)
        tx_up = TransactionUpdate(
            account_id=2,
            amount=2000.0,
            tx_type="INCOME",
            category="測試"
        )
        modify_transaction(self.db, tx.id, tx_up, user_id=1)
        self.assertEqual(self.acc1.balance, 10000.0)
        self.assertEqual(self.acc2.balance, 7000.0)

    def test_pure_balance_delta_calculation(self):
        from app.services.accounting_service import _calculate_balance_delta, TX_TYPE_EXPENSE, TX_TYPE_INCOME, TX_TYPE_TRANSFER
        # Normal
        self.assertEqual(_calculate_balance_delta(TX_TYPE_EXPENSE, 500), -500)
        self.assertEqual(_calculate_balance_delta(TX_TYPE_INCOME, 500), 500)
        self.assertEqual(_calculate_balance_delta(TX_TYPE_TRANSFER, 500), -500)
        # Reverse (rollback)
        self.assertEqual(_calculate_balance_delta(TX_TYPE_EXPENSE, 500, reverse=True), 500)
        self.assertEqual(_calculate_balance_delta(TX_TYPE_INCOME, 500, reverse=True), -500)
        self.assertEqual(_calculate_balance_delta(TX_TYPE_TRANSFER, 500, reverse=True), 500)

    def test_apply_salary_income(self):
        req = SalaryApplyRequest(
            salary_amount=60000.0,
            record_transaction=True,
            account_id=1,
            company_name="測試科技",
            statement_month="2026-10"
        )
        tx_id = apply_salary_income(self.db, req, user_id=1)
        self.assertIsNotNone(tx_id)
        self.assertEqual(self.acc1.balance, 70000.0)
        salary_setting = get_setting(self.db, "MONTHLY_SALARY", user_id=1)
        self.assertEqual(salary_setting, "60000.0")

    def test_multi_currency_transaction_conversion(self):
        # 1. 記錄一筆日圓 JPY 1000 支出，指定匯率 0.205 -> 應自動折合為 205.0 台幣
        tx_in = TransactionCreate(
            account_id=1,
            amount=205.0,
            currency="JPY",
            original_amount=1000.0,
            exchange_rate=0.205,
            tx_type="EXPENSE",
            category="飲食",
            description="日本一蘭拉麵"
        )
        tx = record_transaction(self.db, tx_in, user_id=1)
        self.assertEqual(tx.currency, "JPY")
        self.assertEqual(tx.original_amount, 1000.0)
        self.assertEqual(tx.exchange_rate, 0.205)
        self.assertEqual(tx.amount, 205.0)
        # 帳戶餘額應扣減台幣 205.0 (原餘額 10000 -> 9795.0)
        self.assertEqual(self.acc1.balance, 9795.0)

        # 2. 編輯此筆為美元 USD 50，指定匯率 32.0 -> 應自動折合為 1600.0 台幣
        tx_up = TransactionUpdate(
            account_id=1,
            amount=1600.0,
            currency="USD",
            original_amount=50.0,
            exchange_rate=32.0,
            tx_type="EXPENSE",
            category="數位服務",
            description="OpenAI 訂閱"
        )
        tx_mod = modify_transaction(self.db, tx.id, tx_up, user_id=1)
        self.assertEqual(tx_mod.currency, "USD")
        self.assertEqual(tx_mod.original_amount, 50.0)
        self.assertEqual(tx_mod.exchange_rate, 32.0)
        self.assertEqual(tx_mod.amount, 1600.0)
        # 帳戶餘額應還原 205.0 再扣 1600.0 (10000 - 1600 = 8400.0)
        self.assertEqual(self.acc1.balance, 8400.0)


if __name__ == "__main__":
    unittest.main()

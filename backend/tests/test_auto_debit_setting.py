import unittest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import User, Account, Bill, Transaction, SystemSetting
from backend.app.services.scheduler import execute_auto_debits
from backend.app.services.accounting_service import save_setting


class TestAutoDebitSetting(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = TestingSessionLocal()

        self.user = User(username="test_auto_user", password_hash="hash", display_name="Auto User")
        self.db.add(self.user)
        self.db.commit()

        self.account = Account(
            user_id=self.user.id,
            name="星展活存測試",
            account_type="SAVINGS",
            balance=100000.0,
            is_dbs_default_debit=True
        )
        self.db.add(self.account)
        self.db.commit()

        self.bill = Bill(
            user_id=self.user.id,
            bank_name="星展銀行",
            statement_month="2026-10",
            due_date=date(2026, 11, 5),
            total_amount=5000.0,
            status="PENDING",
            debit_account_id=self.account.id
        )
        self.db.add(self.bill)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_auto_debit_skipped_when_disabled(self):
        """驗證當 AUTO_DEBIT_BILLS 未啟用時，到期帳單不會被自動扣款"""
        save_setting(self.db, "AUTO_DEBIT_BILLS", "false", user_id=self.user.id)
        self.db.commit()
        res = execute_auto_debits(self.db, user_id=self.user.id)

        self.assertEqual(res.get("status"), "skipped")
        self.assertEqual(res.get("paid_count"), 0)

        # 驗證帳單仍為 PENDING，帳戶餘額未被扣除
        self.db.refresh(self.bill)
        self.db.refresh(self.account)
        self.assertEqual(self.bill.status, "PENDING")
        self.assertEqual(self.account.balance, 100000.0)

    def test_auto_debit_executed_when_enabled(self):
        """驗證當 AUTO_DEBIT_BILLS 明確開啟時，到期帳單會執行扣款"""
        save_setting(self.db, "AUTO_DEBIT_BILLS", "true", user_id=self.user.id)
        self.db.commit()
        res = execute_auto_debits(self.db, user_id=self.user.id)

        self.assertEqual(res.get("status"), "success")
        self.assertEqual(res.get("paid_count"), 1)

        self.db.refresh(self.bill)
        self.db.refresh(self.account)
        self.assertEqual(self.bill.status, "PAID")
        self.assertEqual(self.account.balance, 95000.0)


if __name__ == "__main__":
    unittest.main()

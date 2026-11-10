import unittest
from datetime import date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.core.database import Base
from backend.app.models import User, Account, Transaction, SystemSetting
from backend.app.services.accounting_service import execute_auto_salary_credits, save_setting


class TestAutoSalary(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = TestingSessionLocal()

        self.user = User(username="test_salary_user", password_hash="hash", display_name="Salary User")
        self.db.add(self.user)
        self.db.commit()

        self.account = Account(
            user_id=self.user.id,
            name="華南薪轉戶",
            account_type="SAVINGS",
            balance=10000.0,
            is_dbs_default_debit=True
        )
        self.db.add(self.account)
        self.db.commit()

        save_setting(self.db, "MONTHLY_SALARY", "80000.0", user_id=self.user.id)
        save_setting(self.db, "SALARY_ACCOUNT_ID", str(self.account.id), user_id=self.user.id)
        save_setting(self.db, "SALARY_PAY_DAY", "1", user_id=self.user.id)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_auto_salary_skipped_when_disabled(self):
        """驗證當 AUTO_SALARY_INCOME_ENABLED 未啟用時，不執行薪資自動入帳"""
        save_setting(self.db, "AUTO_SALARY_INCOME_ENABLED", "false", user_id=self.user.id)
        self.db.commit()

        res = execute_auto_salary_credits(self.db, user_id=self.user.id)
        self.assertEqual(res.get("credited_count"), 0)

        # 帳戶餘額維持不變
        self.db.refresh(self.account)
        self.assertEqual(self.account.balance, 10000.0)

    def test_auto_salary_credited_when_enabled(self):
        """驗證當 AUTO_SALARY_INCOME_ENABLED 啟用且已過發薪日，自動建立薪資收入流水帳並增加存款"""
        save_setting(self.db, "AUTO_SALARY_INCOME_ENABLED", "true", user_id=self.user.id)
        self.db.commit()

        res = execute_auto_salary_credits(self.db, user_id=self.user.id)
        self.assertEqual(res.get("credited_count"), 1)

        # 帳戶餘額應增加 80,000 元 (10000 + 80000 = 90000)
        self.db.refresh(self.account)
        self.assertEqual(self.account.balance, 90000.0)

        # 應有薪資交易紀錄
        tx = self.db.query(Transaction).filter_by(user_id=self.user.id, tx_type="INCOME").first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, 80000.0)
        self.assertEqual(tx.category, "薪資收入")
        self.assertEqual(tx.account_id, self.account.id)

        # 再次執行不應重複入帳 (防呆去重)
        res2 = execute_auto_salary_credits(self.db, user_id=self.user.id)
        self.assertEqual(res2.get("credited_count"), 0)
        self.db.refresh(self.account)
        self.assertEqual(self.account.balance, 90000.0)

    def test_auto_salary_credited_with_net_salary_when_deduct_enabled(self):
        """驗證當啟用實領制 (DEDUCT_LABOR_HEALTH=true) 時，自動入帳金額為扣除勞健保後之實領淨額"""
        save_setting(self.db, "AUTO_SALARY_INCOME_ENABLED", "true", user_id=self.user.id)
        save_setting(self.db, "DEDUCT_LABOR_HEALTH", "true", user_id=self.user.id)
        save_setting(self.db, "HEALTH_INSURANCE_DEPENDENTS", "3", user_id=self.user.id)
        save_setting(self.db, "LABOR_HEALTH_AUTO_CALC", "true", user_id=self.user.id)
        self.db.commit()

        res = execute_auto_salary_credits(self.db, user_id=self.user.id)
        self.assertEqual(res.get("credited_count"), 1)

        # 80000 全薪扣除 4832 法定扣繳 (勞保1100 + 健保4口3732) = 實領 75168
        self.db.refresh(self.account)
        self.assertEqual(self.account.balance, 10000.0 + 75168.0)

        tx = self.db.query(Transaction).filter_by(user_id=self.user.id, tx_type="INCOME").first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.amount, 75168.0)
        self.assertIn("(實領)", tx.description)


if __name__ == "__main__":
    unittest.main()

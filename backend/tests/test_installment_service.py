import unittest
from datetime import datetime, date
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, User, Account, Transaction, InstallmentPlan
from backend.app.schemas import InstallmentPlanCreate, InstallmentPlanUpdate
from backend.app.services.installment_service import (
    calculate_installment_amounts,
    compute_installment_period_date,
    generate_amortization_schedule,
    create_installment_plan,
    charge_installment_period,
    settle_installment_in_full,
    get_installment_summary,
    get_installment_plans_list,
    get_installment_plan_detail,
    delete_installment_plan,
    INSTALLMENT_STATUS_ACTIVE,
    INSTALLMENT_STATUS_COMPLETED,
)


class TestInstallmentService(unittest.TestCase):
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

        # 建立信用卡帳戶
        self.card_acc = Account(
            id=1,
            user_id=1,
            name="星展 eco 卡",
            account_type="CREDIT",
            balance=0.0
        )
        self.db.add(self.card_acc)
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def test_calculate_installment_amounts(self):
        # 測試 10,000 元分 3 期
        monthly, first_amt = calculate_installment_amounts(10000, 3)
        self.assertEqual(monthly, 3333.33)
        self.assertEqual(first_amt, 3333.34)
        # 驗證總和嚴格等於 10,000
        self.assertEqual(first_amt + monthly * 2, 10000.0)

        # 測試整除 36,000 元分 12 期
        monthly_12, first_amt_12 = calculate_installment_amounts(36000, 12)
        self.assertEqual(monthly_12, 3000.0)
        self.assertEqual(first_amt_12, 3000.0)

    def test_compute_installment_period_date(self):
        start_d = date(2026, 10, 25)
        # 第 1 期: 2026-10-25
        d1 = compute_installment_period_date(start_d, 1, billing_day=25)
        self.assertEqual(d1, date(2026, 10, 25))
        # 第 2 期: 2026-11-25
        d2 = compute_installment_period_date(start_d, 2, billing_day=25)
        self.assertEqual(d2, date(2026, 11, 25))
        # 測試 2 月底天數防溢位 (例如 billing_day=31)
        d_feb = compute_installment_period_date(date(2026, 1, 31), 2, billing_day=31)
        self.assertEqual(d_feb, date(2026, 2, 28))

    def test_create_and_charge_installment_plan(self):
        plan_in = InstallmentPlanCreate(
            name="iPhone 16 Pro Max",
            total_amount=36000.0,
            total_periods=12,
            category="數位3C",
            account_id=self.card_acc.id,
            start_date=date(2026, 10, 25),
            billing_day=25,
            record_first_period=True # 建立當下即扣繳第 1 期
        )
        plan_res = create_installment_plan(self.db, user_id=1, plan_in=plan_in)

        self.assertEqual(plan_res["name"], "iPhone 16 Pro Max")
        self.assertEqual(plan_res["current_period"], 1)
        self.assertEqual(plan_res["paid_amount"], 3000.0)
        self.assertEqual(plan_res["remaining_amount"], 33000.0)
        self.assertEqual(plan_res["progress_percent"], 8.3)
        self.assertEqual(self.card_acc.balance, -3000.0)

        # 扣繳第 2 期
        res2 = charge_installment_period(self.db, plan_res["id"], user_id=1)
        self.assertEqual(res2["status"], "success")
        self.assertEqual(res2["current_period"], 2)
        self.assertEqual(self.card_acc.balance, -6000.0)

        # 驗證不能重複扣繳第 2 期
        with self.assertRaises(Exception):
            charge_installment_period(self.db, plan_res["id"], user_id=1, target_period=2)

    def test_settle_in_full(self):
        # 建立 10,000 元分 4 期
        plan_in = InstallmentPlanCreate(
            name="機票分期",
            total_amount=10000.0,
            total_periods=4,
            category="交通",
            account_id=self.card_acc.id,
            start_date=date(2026, 10, 1),
            record_first_period=True # 已繳 1 期 (2,500)
        )
        plan = create_installment_plan(self.db, user_id=1, plan_in=plan_in)

        # 提前結清剩餘 3 期 (7,500)
        settle_res = settle_installment_in_full(self.db, plan["id"], user_id=1)
        self.assertEqual(settle_res["status"], "success")

        detail = get_installment_plan_detail(self.db, plan["id"], user_id=1)
        self.assertEqual(detail["status"], INSTALLMENT_STATUS_COMPLETED)
        self.assertEqual(detail["remaining_amount"], 0.0)
        self.assertEqual(detail["progress_percent"], 100.0)
        self.assertEqual(self.card_acc.balance, -10000.0)

    def test_installment_summary_and_forecast(self):
        # 建立兩個分期計畫
        p1 = InstallmentPlanCreate(
            name="電視",
            total_amount=24000.0,
            total_periods=6, # 每期 4000
            account_id=self.card_acc.id,
            start_date=date.today(),
            record_first_period=False
        )
        create_installment_plan(self.db, user_id=1, plan_in=p1)

        summary = get_installment_summary(self.db, user_id=1, forecast_months=6)
        self.assertEqual(summary["total_plans_count"], 1)
        self.assertEqual(summary["active_plans_count"], 1)
        self.assertEqual(summary["total_debt_remaining"], 24000.0)
        self.assertEqual(len(summary["forecast"]), 6)
        # 第 1 個月應繳 4000
        self.assertEqual(summary["forecast"][0]["total_amount"], 4000.0)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.database import Base, get_db
from backend.app.main import app
from backend.app.models import User, Account, Transaction, RecurringExpense
from backend.app.services.auth_service import hash_password, create_access_token
from backend.app.services.accounting_service import save_setting
from backend.app.services.ai_advisor_service import build_financial_snapshot, generate_financial_advice


class TestAIAdvisorServiceAndEndpoints(unittest.TestCase):
    def setUp(self):
        # 建立獨立記憶體 SQLite 資料庫進行隔離測試
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        self.TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.TestingSessionLocal()

        def override_get_db():
            try:
                yield self.db
            finally:
                pass

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # 建立測試使用者
        self.user = User(
            username="advisor_tester",
            password_hash=hash_password("testpwd123"),
            display_name="顧問測試員"
        )
        self.db.add(self.user)
        self.db.commit()
        self.db.refresh(self.user)

        self.token = create_access_token(self.db, user_id=self.user.id, username=self.user.username)
        self.auth_headers = {"Authorization": f"Bearer {self.token}"}

        # 設定月薪
        save_setting(self.db, "MONTHLY_SALARY", "80000", user_id=self.user.id)

        # 建立帳戶 (活存 200,000 元)
        self.acc1 = Account(
            user_id=self.user.id,
            name="台新活儲",
            account_type="SAVINGS",
            balance=200000.0,
            currency="TWD"
        )
        self.db.add(self.acc1)
        self.db.commit()

        # 建立記帳明細 (支出 飲食 12,000, 居住 20,000)
        t1 = Transaction(
            user_id=self.user.id,
            account_id=self.acc1.id,
            tx_type="EXPENSE",
            category="飲食",
            amount=12000.0,
            description="日常餐飲",
            date=datetime(2026, 11, 1, 12, 0, 0)
        )
        t2 = Transaction(
            user_id=self.user.id,
            account_id=self.acc1.id,
            tx_type="EXPENSE",
            category="居住",
            amount=20000.0,
            description="租金",
            date=datetime(2026, 11, 2, 12, 0, 0)
        )
        self.db.add_all([t1, t2])

        # 建立固定開銷 (Netflix 390)
        rec = RecurringExpense(
            user_id=self.user.id,
            name="Netflix 訂閱",
            category="娛樂",
            amount=390.0,
            is_active=True
        )
        self.db.add(rec)
        self.db.commit()

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_build_financial_snapshot(self):
        """測試財務快照各項數值彙整正確性"""
        snapshot = build_financial_snapshot(self.db, self.user)
        self.assertEqual(snapshot["total_savings_twd"], 200000.0)
        self.assertEqual(snapshot["base_monthly_salary_twd"], 80000.0)
        self.assertGreater(snapshot["avg_monthly_expense_twd"], 0)
        self.assertGreater(snapshot["emergency_fund_months"], 0)
        self.assertEqual(snapshot["monthly_recurring_fixed_cost_twd"], 390.0)
        self.assertTrue(len(snapshot["top_expense_categories"]) > 0)

    def test_advisor_ask_missing_api_key_raises_400(self):
        """測試未設定 Gemini API Key 時應拋出明確 400 警示與引導"""
        res = self.client.post(
            "/api/ai/advisor/ask",
            headers=self.auth_headers,
            json={"question": "我想買 1500 萬的房子，以我的薪資能負擔嗎？"}
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("尚未設定 Gemini API Key", res.json()["detail"])

    @patch("backend.app.services.ai_advisor_service.genai.Client")
    def test_advisor_ask_success_with_mock_gemini(self, mock_genai_client_class):
        """測試成功調用 Gemini 並回傳專業結構化建議"""
        save_setting(self.db, "GEMINI_API_KEY", "AIzaFakeTestKey123", user_id=self.user.id)
        self.db.commit()

        # Mock client 與 response
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "### 專業買房建議\n根據您目前 20 萬存款與 8 萬月薪..."
        mock_client.models.generate_content.return_value = mock_response
        mock_genai_client_class.return_value = mock_client

        res = self.client.post(
            "/api/ai/advisor/ask",
            headers=self.auth_headers,
            json={
                "question": "我想買 1200 萬的房子，請給我頭期款與每月還款建議",
                "history": []
            }
        )
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertIn("advice", data)
        self.assertIn("專業買房建議", data["advice"])
        self.assertIn("snapshot", data)
        self.assertEqual(data["snapshot"]["total_savings_twd"], 200000.0)

    def test_get_financial_snapshot_endpoint(self):
        """測試取得即時個人財務快照 API"""
        res = self.client.get("/api/ai/advisor/snapshot", headers=self.auth_headers)
        self.assertEqual(res.status_code, 200, res.text)
        data = res.json()
        self.assertEqual(data["total_savings_twd"], 200000.0)
        self.assertEqual(data["base_monthly_salary_twd"], 80000.0)


if __name__ == "__main__":
    unittest.main()

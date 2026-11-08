import unittest
from unittest.mock import patch
import io
import sys
import os
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.app.main import app
from backend.app.core.database import get_db, Base
from backend.app.models import User, SystemSetting
from backend.app.services.auth_service import get_current_user


class TestAiOnlyParser(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # 建立測試使用者
        self.user = User(
            id=1,
            username="testuser",
            password_hash="hashed_pwd",
            display_name="Test User"
        )
        self.db.add(self.user)
        self.db.commit()

        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_missing_gemini_key_fails_cleanly_without_local_regex_fallback(self):
        """若使用者未設定 Gemini API Key，應直接提示設定 API Key，絕不 fallback 到本地正規表達式"""
        fake_pdf = b"%PDF-1.4 test content"
        files = {"file": ("dbs_statement.pdf", io.BytesIO(fake_pdf), "application/pdf")}

        response = self.client.post(
            "/api/ai/parse-document",
            files=files,
            data={"password": "testpassword"}
        )

        self.assertEqual(response.status_code, 400)
        detail = response.json().get("detail", "")
        self.assertIn("純 AI 智能辨識", detail)
        self.assertIn("Gemini API Key", detail)

    @patch("backend.app.routers.bills.parse_document_with_gemini")
    def test_ai_parsing_success_flow(self, mock_gemini):
        """當設定 Gemini API Key 時，必須全面調用純 Gemini AI 進行多模態辨識"""
        # 設定使用者的 Gemini Key 與帳單密碼
        self.db.add(SystemSetting(key="u1:GEMINI_API_KEY", value="AIzaFakeKey123", user_id=1))
        self.db.add(SystemSetting(key="u1:ID_CARD_PASSWORD", value="A123456789", user_id=1))
        self.db.commit()

        mock_gemini.return_value = {
            "success": True,
            "document_type": "CREDIT_CARD_BILL",
            "bank_or_company": "星展銀行",
            "statement_month": "2026-10",
            "total_amount": 13119.0,
            "minimum_amount": 1312.0,
            "due_date": "2026-11-08",
            "statement_date": "2026-10-25",
            "notes": "星展帳單已核對",
            "confidence_summary": "Gemini 3.5 辨識成功",
            "currency": "TWD",
            "original_amount": 13119.0,
            "exchange_rate": 1.0
        }

        fake_pdf = b"%PDF-1.4 encrypted content"
        files = {"file": ("credit_bill.pdf", io.BytesIO(fake_pdf), "application/pdf")}

        response = self.client.post(
            "/api/ai/parse-document",
            files=files
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["bank_or_company"], "星展銀行")
        self.assertEqual(data["total_amount"], 13119.0)
        self.assertEqual(data["due_date"], "2026-11-08")

        # 驗證調用參數是否包含使用者的 Key 與密碼清單
        mock_gemini.assert_called_once()
        _, kwargs = mock_gemini.call_args
        self.assertEqual(kwargs["api_key"], "AIzaFakeKey123")
        self.assertIn("A123456789", kwargs["password"])

    @patch("backend.app.routers.bills.parse_document_with_gemini")
    def test_ai_parsing_failure_returns_ai_error_directly(self, mock_gemini):
        """當 AI 辨識回報錯誤時，直接回傳 AI 錯誤訊息，嚴禁靜默降級到本地正規解析"""
        self.db.add(SystemSetting(key="u1:GEMINI_API_KEY", value="AIzaFakeKey123", user_id=1))
        self.db.commit()

        mock_gemini.return_value = {
            "success": False,
            "error": "此 PDF 帳單設有密碼保護，且您提供的解密密碼無法解鎖。"
        }

        fake_pdf = b"%PDF-1.4 protected"
        files = {"file": ("dbs_bill.pdf", io.BytesIO(fake_pdf), "application/pdf")}

        response = self.client.post(
            "/api/ai/parse-document",
            files=files
        )

        self.assertEqual(response.status_code, 400)
        detail = response.json().get("detail", "")
        self.assertIn("此 PDF 帳單設有密碼保護", detail)


if __name__ == "__main__":
    unittest.main()

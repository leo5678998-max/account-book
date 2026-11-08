import unittest
from fastapi.testclient import TestClient
from backend.app.main import app
from backend.app.routers import auth


class TestAuthSecurity(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_api_docs_hidden_by_default(self):
        """驗證外網 API 規格與文件預設隱藏以提升資安"""
        resp_docs = self.client.get("/docs")
        self.assertEqual(resp_docs.status_code, 404, "Swagger /docs 應預設回傳 404 隱藏")

        resp_redoc = self.client.get("/redoc")
        self.assertEqual(resp_redoc.status_code, 404, "Redoc 應預設回傳 404 隱藏")

        resp_openapi = self.client.get("/openapi.json")
        self.assertEqual(resp_openapi.status_code, 404, "openapi.json 應預設回傳 404 隱藏")

    def test_auth_config_endpoint(self):
        """驗證取得認證公開配置端點正常回應"""
        resp = self.client.get("/api/auth/config")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("allow_registration", data)
        self.assertFalse(data["allow_registration"], "預設應關閉公開註冊")

    def test_public_registration_disabled(self):
        """驗證當公開註冊關閉時，呼叫註冊 API 會回傳 403 Forbidden"""
        auth.ALLOW_REGISTRATION = False
        resp = self.client.post("/api/auth/register", json={
            "username": "hacker_test",
            "password": "password123",
            "display_name": "Hacker"
        })
        self.assertEqual(resp.status_code, 403)
        self.assertIn("公開註冊功能已關閉", resp.json().get("detail", ""))


if __name__ == "__main__":
    unittest.main()

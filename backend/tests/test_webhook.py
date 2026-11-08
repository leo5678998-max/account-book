import unittest
import os
import sys

# Set up module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.core.database import Base, get_db
from app.models import User, Account, Transaction, SystemSetting
from app.services.auth_service import create_access_token
from app.services.webhook_service import (
    parse_webhook_amount,
    auto_categorize_merchant,
    parse_webhook_datetime,
    parse_notification_text,
    get_or_create_webhook_token,
    regenerate_webhook_token,
    find_user_by_webhook_token,
    resolve_target_account,
    process_apple_pay_transaction,
    WEBHOOK_TOKEN_SETTING_KEY,
)
from app.main import app


class TestWebhookServiceAndEndpoints(unittest.TestCase):
    def setUp(self):
        # Create an in-memory SQLite database for testing (shared across threads/connections)
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool
        )
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()

        # Seed test user
        self.user = User(id=1, username="test_webhook_user", password_hash="dummy_hash")
        self.db.add(self.user)

        # Seed test accounts
        self.card_acc = Account(
            id=1,
            user_id=1,
            name="國泰世華 CUBE 卡",
            account_type="CREDIT",
            balance=0.0,
            account_number="1234",
            is_dbs_default_debit=False
        )
        self.savings_acc = Account(
            id=2,
            user_id=1,
            name="台新活儲",
            account_type="SAVINGS",
            balance=50000.0,
            account_number="5678",
            is_dbs_default_debit=True
        )
        self.db.add_all([self.card_acc, self.savings_acc])
        self.db.commit()

        # Override FastAPI get_db dependency
        def override_get_db():
            db_session = self.Session()
            try:
                yield db_session
            finally:
                db_session.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

        # Generate JWT token for authorized endpoints
        self.jwt_token = create_access_token(self.db, user_id=self.user.id, username=self.user.username)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)

    def test_parse_webhook_amount(self):
        # Numeric inputs
        self.assertEqual(parse_webhook_amount(150), 150.0)
        self.assertEqual(parse_webhook_amount(150.75), 150.75)
        # String inputs
        self.assertEqual(parse_webhook_amount("150"), 150.0)
        self.assertEqual(parse_webhook_amount("$150"), 150.0)
        self.assertEqual(parse_webhook_amount("NT$ 1,250.50"), 1250.5)
        self.assertEqual(parse_webhook_amount("1,200元"), 1200.0)
        self.assertEqual(parse_webhook_amount("  TWD 80  "), 80.0)

        # Invalid inputs
        with self.assertRaises(ValueError):
            parse_webhook_amount(0)
        with self.assertRaises(ValueError):
            parse_webhook_amount("-50")
        with self.assertRaises(ValueError):
            parse_webhook_amount("abc")
        with self.assertRaises(ValueError):
            parse_webhook_amount(None)

    def test_auto_categorize_merchant(self):
        self.assertEqual(auto_categorize_merchant("7-ELEVEN 敦南門市"), "飲食")
        self.assertEqual(auto_categorize_merchant("星巴克 Starbucks"), "飲食")
        self.assertEqual(auto_categorize_merchant("Uber Eats"), "飲食")
        self.assertEqual(auto_categorize_merchant("台灣高鐵 售票機"), "交通")
        self.assertEqual(auto_categorize_merchant("台灣中油加油站"), "交通")
        self.assertEqual(auto_categorize_merchant("全聯福利中心"), "日常採買")
        self.assertEqual(auto_categorize_merchant("好市多 COSTCO"), "日常採買")
        self.assertEqual(auto_categorize_merchant("威秀影城"), "娛樂休閒")
        self.assertEqual(auto_categorize_merchant("康是美藥局"), "日常採買")  # 全聯/康是美 in 日常採買
        self.assertEqual(auto_categorize_merchant("完全不明奇怪商家"), "其他")
        self.assertEqual(auto_categorize_merchant(None), "其他")

    def test_token_lifecycle_and_user_lookup(self):
        # 1. Generate token
        token1 = get_or_create_webhook_token(self.db, user_id=self.user.id)
        self.assertTrue(len(token1) >= 20)

        # 2. Re-getting should return same token
        token1_again = get_or_create_webhook_token(self.db, user_id=self.user.id)
        self.assertEqual(token1, token1_again)

        # 3. Find user by token
        found_user = find_user_by_webhook_token(self.db, token1)
        self.assertIsNotNone(found_user)
        self.assertEqual(found_user.id, self.user.id)

        # 4. Regenerate token
        token2 = regenerate_webhook_token(self.db, user_id=self.user.id)
        self.assertNotEqual(token1, token2)

        # 5. Old token should not find user
        self.assertIsNone(find_user_by_webhook_token(self.db, token1))
        # 6. New token finds user
        found_user2 = find_user_by_webhook_token(self.db, token2)
        self.assertIsNotNone(found_user2)
        self.assertEqual(found_user2.id, self.user.id)

    def test_resolve_target_account(self):
        # 1. Match by exact or partial name
        acc = resolve_target_account(self.db, user_id=1, card_name="國泰世華 CUBE 卡")
        self.assertEqual(acc.id, self.card_acc.id)

        acc_sub = resolve_target_account(self.db, user_id=1, card_name="國泰 CUBE")
        self.assertEqual(acc_sub.id, self.card_acc.id)

        # 2. Match by last 4 digits
        acc_digits = resolve_target_account(self.db, user_id=1, card_name="信用卡 (末四碼 1234)")
        self.assertEqual(acc_digits.id, self.card_acc.id)

        # 3. Fallback when card name not matched: should hit default debit account (savings_acc)
        acc_fallback = resolve_target_account(self.db, user_id=1, card_name="玉山 Pi 卡 (未建帳戶)")
        self.assertEqual(acc_fallback.id, self.savings_acc.id)

    def test_process_apple_pay_transaction(self):
        payload = {
            "amount": "120",
            "merchant": "7-11 敦南門市",
            "card_name": "國泰世華 CUBE 卡",
            "note": "買咖啡"
        }
        tx = process_apple_pay_transaction(self.db, user_id=self.user.id, payload=payload)
        self.assertEqual(tx.amount, 120.0)
        self.assertEqual(tx.category, "飲食")
        self.assertEqual(tx.description, "7-11 敦南門市 - 買咖啡")
        self.assertEqual(tx.account_id, self.card_acc.id)
        # Check balance deduction (EXPENSE on card_acc 0.0 -> -120.0)
        self.db.refresh(self.card_acc)
        self.assertEqual(self.card_acc.balance, -120.0)

    def test_webhook_api_endpoint_via_query_param(self):
        token = get_or_create_webhook_token(self.db, user_id=self.user.id)

        res = self.client.post(
            f"/api/webhook/apple-pay?token={token}",
            json={
                "amount": "85",
                "merchant": "星巴克",
                "card_name": "國泰世華 CUBE 卡"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["amount"], 85.0)
        self.assertEqual(data["category"], "飲食")
        self.assertEqual(data["account_name"], "國泰世華 CUBE 卡")

    def test_webhook_api_endpoint_via_header(self):
        token = get_or_create_webhook_token(self.db, user_id=self.user.id)

        res = self.client.post(
            "/api/webhook/apple-pay",
            headers={"X-Webhook-Token": token},
            json={
                "amount": 250,
                "merchant": "台灣高鐵",
                "category": "交通"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["category"], "交通")
        self.assertEqual(data["amount"], 250.0)

    def test_inverted_apple_pay_payload(self):
        # When iOS Shortcuts inverts key and value:
        inverted_payload = {
            "88": 0,
            "全聯福利中心": "文字",
            "國泰世華 CUBE 卡": "文字"
        }
        tx = process_apple_pay_transaction(self.db, user_id=self.user.id, payload=inverted_payload)
        self.assertEqual(tx.amount, 88.0)
        self.assertEqual(tx.category, "日常採買")
        self.assertIn("全聯", tx.description)
        self.assertEqual(tx.account_id, self.card_acc.id)

    def test_webhook_api_invalid_token(self):
        res = self.client.post(
            "/api/webhook/apple-pay?token=invalid_token_123",
            json={"amount": 100, "merchant": "全聯"}
        )
        self.assertEqual(res.status_code, 401)

    def test_webhook_token_management_endpoints(self):
        headers = {"Authorization": f"Bearer {self.jwt_token}"}

        # 1. GET /api/webhook/token
        res_get = self.client.get("/api/webhook/token", headers=headers)
        self.assertEqual(res_get.status_code, 200)
        data_get = res_get.json()
        self.assertIn("webhook_token", data_get)
        self.assertTrue(data_get["webhook_url"].startswith("/api/webhook/apple-pay?token="))

        tok1 = data_get["webhook_token"]

        # 2. POST /api/webhook/token/regenerate
        res_regen = self.client.post("/api/webhook/token/regenerate", headers=headers)
        self.assertEqual(res_regen.status_code, 200)
        data_regen = res_regen.json()
        tok2 = data_regen["webhook_token"]
        self.assertNotEqual(tok1, tok2)

        # 3. POST /api/webhook/apple-pay/test
        res_test = self.client.post(
            "/api/webhook/apple-pay/test",
            headers=headers,
            json={"amount": "65", "merchant": "路易莎咖啡"}
        )
        self.assertEqual(res_test.status_code, 200)
        self.assertEqual(res_test.json()["amount"], 65.0)

    def test_parse_notification_text(self):
        # 1. LINE Pay
        line_pay_res = parse_notification_text("您已於 7-ELEVEN 成功付款 NT$ 85 元。", app="LINE Pay", title="付款成功")
        self.assertEqual(line_pay_res["amount"], 85.0)
        self.assertEqual(line_pay_res["merchant"], "7-ELEVEN")
        self.assertEqual(line_pay_res["card_name"], "LINE Pay")

        # 2. Bank card (國泰世華 CUBE)
        cube_res = parse_notification_text("您於 10/29 02:00 在 蝦皮購物 消費 NT$ 1,299", app="國泰世華 CUBE", title="刷卡通知")
        self.assertEqual(cube_res["amount"], 1299.0)
        self.assertEqual(cube_res["merchant"], "蝦皮購物")
        self.assertEqual(cube_res["card_name"], "國泰世華")

        # 3. Bank card with store prefix
        ctbc_res = parse_notification_text("您於 10/29 02:00 消費 NT$ 550 元，特店：Uber Eats", app="中國信託 Home Bank")
        self.assertEqual(ctbc_res["amount"], 550.0)
        self.assertEqual(ctbc_res["merchant"], "Uber Eats")
        self.assertEqual(ctbc_res["card_name"], "中國信託")

        # 4. DBS Card+ notification (with Chinese date, space in merchant, amount in title)
        dbs_res = parse_notification_text(
            "信用卡號末四碼 2459 於 10月30日 20:12 在 BREEZE CENTER交易。",
            app="星展 Card+",
            title="【星展信用卡刷卡交易】約 NT$812元"
        )
        self.assertEqual(dbs_res["amount"], 812.0)
        self.assertEqual(dbs_res["merchant"], "BREEZE CENTER")
        self.assertEqual(dbs_res["card_name"], "星展 2459")
        self.assertEqual(auto_categorize_merchant(dbs_res["merchant"]), "日常採買")

    def test_webhook_with_raw_notification_text(self):
        token = get_or_create_webhook_token(self.db, user_id=self.user.id)
        # Send raw notification text without amount field
        res = self.client.post(
            f"/api/webhook/apple-pay?token={token}",
            json={
                "text": "您已於 7-ELEVEN 成功付款 NT$ 95 元。",
                "app": "LINE Pay",
                "title": "付款成功"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["amount"], 95.0)
        self.assertEqual(data["category"], "飲食")

    def test_twin_notification_auto_merge(self):
        token = get_or_create_webhook_token(self.db, user_id=self.user.id)
        # Notification 1 from LINE Pay
        res1 = self.client.post(
            f"/api/webhook/apple-pay?token={token}",
            json={"amount": 135.0, "merchant": "LINE Pay"}
        )
        self.assertEqual(res1.status_code, 200)
        tx_id_1 = res1.json()["transaction_id"]

        # Notification 2 from Credit card 2 seconds later (same amount)
        res2 = self.client.post(
            f"/api/webhook/apple-pay?token={token}",
            json={"amount": 135.0, "merchant": "路易莎咖啡", "card_name": "國泰世華"}
        )
        self.assertEqual(res2.status_code, 200)
        tx_id_2 = res2.json()["transaction_id"]

        # Must merge into the same transaction, not duplicate
        self.assertEqual(tx_id_1, tx_id_2)
        # Merchant should be upgraded to 路易莎咖啡
        merged_tx = self.db.query(Transaction).filter(Transaction.id == tx_id_1).first()
        self.assertEqual(merged_tx.description, "路易莎咖啡")
        self.assertEqual(merged_tx.category, "飲食")

    def test_concurrent_twin_notification_auto_merge(self):
        import concurrent.futures
        token = get_or_create_webhook_token(self.db, user_id=self.user.id)

        # 模擬兩筆推播同時發送到伺服器 (如 星展 Card+ CaptainLimited 與 LINE 艇長有限公司)
        def send_req1():
            return self.client.post(
                f"/api/webhook/apple-pay?token={token}",
                json={"amount": 70.0, "merchant": "CaptainLimited", "app": "星展 Card+"}
            )

        def send_req2():
            return self.client.post(
                f"/api/webhook/apple-pay?token={token}",
                json={"amount": 70.0, "merchant": "艇長有限公司前港營業所", "app": "LINE"}
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(send_req1)
            f2 = executor.submit(send_req2)
            r1 = f1.result()
            r2 = f2.result()

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        id1 = r1.json()["transaction_id"]
        id2 = r2.json()["transaction_id"]

        # 必須去重合併為同一個交易 ID
        self.assertEqual(id1, id2)
        # 中文詳細店名應覆蓋英文銀行商家名
        self.db.expire_all()
        merged_tx = self.db.query(Transaction).filter(Transaction.id == id1).first()
        self.assertIn("艇長有限公司", merged_tx.description)

    def test_webhook_refund_auto_detection(self):
        token = get_or_create_webhook_token(self.db, user_id=self.user.id)
        # Send a refund notification
        res = self.client.post(
            f"/api/webhook/apple-pay?token={token}",
            json={
                "text": "您於 10/30 在 BREEZE CENTER 刷退成功 NT$ 812元",
                "app": "星展 Card+",
                "title": "星展信用卡退刷通知"
            }
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["amount"], 812.0)
        self.assertEqual(data["category"], "日常採買")

        # Verify transaction in database
        tx = self.db.query(Transaction).filter(Transaction.id == data["transaction_id"]).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.tx_type, "REFUND")
        self.assertIn("[退款]", tx.description)


if __name__ == "__main__":
    unittest.main()

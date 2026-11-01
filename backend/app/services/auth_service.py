import os
import json
import time
import hmac
import base64
import hashlib
import secrets
from typing import Optional, Dict, Any
from fastapi import Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.database import get_db, SessionLocal, Base
from ..models import User, SystemSetting


def hash_password(password: str) -> str:
    """使用 PBKDF2-HMAC-SHA256 與隨機鹽安全雜湊密碼"""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return f"{salt}${dk.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """驗證密碼是否與儲存的雜湊相符"""
    if not stored_hash or "$" not in stored_hash:
        return False
    salt, expected_hex = stored_hash.split("$", 1)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120000)
    return hmac.compare_digest(dk.hex(), expected_hex)


def _get_jwt_secret(db: Session) -> str:
    """取得或自動產生系統 JWT 簽章密鑰"""
    env_secret = os.getenv("JWT_SECRET_KEY")
    if env_secret:
        return env_secret

    item = db.query(SystemSetting).filter(SystemSetting.key == "SYSTEM_JWT_SECRET").first()
    if item and item.value:
        return item.value

    new_secret = secrets.token_hex(32)
    if not item:
        item = SystemSetting(key="SYSTEM_JWT_SECRET", value=new_secret, description="JWT HMAC Signing Key", user_id=1)
        db.add(item)
    else:
        item.value = new_secret
    db.commit()
    return new_secret


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + padding).encode("ascii"))


def create_access_token(db: Session, user_id: int, username: str, expires_days: int = 30) -> str:
    """簽發 HMAC-SHA256 存取權杖 (JWT 格式)"""
    secret = _get_jwt_secret(db)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": user_id,
        "username": username,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_days * 86400
    }
    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    s_b64 = _b64url_encode(sig)
    return f"{h_b64}.{p_b64}.{s_b64}"


def decode_access_token(db: Session, token: str) -> Optional[Dict[str, Any]]:
    """驗證並解碼 JWT 存取權杖"""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h_b64, p_b64, s_b64 = parts
        secret = _get_jwt_secret(db)
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(s_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None

        payload = json.loads(_b64url_decode(p_b64).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """FastAPI 依賴注入：解析 Authorization Bearer Token 並回傳當前登入使用者"""
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
    elif request.query_params.get("token"):
        token = request.query_params.get("token")

    if not token:
        raise HTTPException(status_code=401, detail="尚未登入，請先登入帳號")

    payload = decode_access_token(db, token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="登入憑證無效或已過期，請重新登入")

    user_id = int(payload["sub"])
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="使用者帳號不存在，請重新登入")

    return user


def run_schema_migrations(engine) -> None:
    """
    自動檢查並升級現有 SQLite 資料庫結構：
    1. 為舊版單租戶資料表補上 user_id 欄位 (預設歸屬於 user_id = 1)
    2. 若無任何使用者，自動建立 id=1 預設帳號 (admin / admin123)，確保原有帳本資料無縫保留
    """
    tables_need_user_id = [
        "accounts",
        "transactions",
        "bills",
        "system_settings",
        "stock_holdings",
        "recurring_expenses",
        "installment_plans"
    ]

    # 確保新資料表如 installment_plans 存在
    Base.metadata.create_all(bind=engine)

    with engine.begin() as conn:
        for table in tables_need_user_id:
            try:
                rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
                if not rows:
                    continue
                col_names = [r[1] for r in rows]
                if "user_id" not in col_names:
                    print(f"[Migration] 為資料表 {table} 新增 user_id 欄位...")
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN user_id INTEGER DEFAULT 1"))
                    conn.execute(text(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL"))
                else:
                    conn.execute(text(f"UPDATE {table} SET user_id = 1 WHERE user_id IS NULL"))

                if table == "recurring_expenses":
                    if "updated_at" not in col_names:
                        conn.execute(text("ALTER TABLE recurring_expenses ADD COLUMN updated_at DATETIME"))
                    if "auto_debit" not in col_names:
                        conn.execute(text("ALTER TABLE recurring_expenses ADD COLUMN auto_debit BOOLEAN DEFAULT 0"))

                if table == "transactions":
                    if "affects_balance" not in col_names:
                        conn.execute(text("ALTER TABLE transactions ADD COLUMN affects_balance BOOLEAN DEFAULT 1"))
                    if "related_transaction_id" not in col_names:
                        conn.execute(text("ALTER TABLE transactions ADD COLUMN related_transaction_id INTEGER NULL"))
                    if "is_reconciled" not in col_names:
                        conn.execute(text("ALTER TABLE transactions ADD COLUMN is_reconciled BOOLEAN DEFAULT 0"))
                    if "reconciled_at" not in col_names:
                        conn.execute(text("ALTER TABLE transactions ADD COLUMN reconciled_at DATETIME NULL"))
                    if "installment_plan_id" not in col_names:
                        conn.execute(text("ALTER TABLE transactions ADD COLUMN installment_plan_id INTEGER NULL"))
                    if "installment_period" not in col_names:
                        conn.execute(text("ALTER TABLE transactions ADD COLUMN installment_period INTEGER NULL"))

                if table == "bills":
                    if "credit_account_id" not in col_names:
                        conn.execute(text("ALTER TABLE bills ADD COLUMN credit_account_id INTEGER NULL"))
                    if "statement_start_date" not in col_names:
                        conn.execute(text("ALTER TABLE bills ADD COLUMN statement_start_date DATE NULL"))
            except Exception as e:
                print(f"[Migration] 檢查資料表 {table} 時發生警告: {e}")

    # 確保至少存在 id=1 的預設擁有者帳號，讓既有資料有所歸屬
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        if user_count == 0:
            default_user = User(
                id=1,
                username="admin",
                password_hash=hash_password("admin123"),
                display_name="預設管理員"
            )
            db.add(default_user)
            db.commit()
            print("[Migration] 已自動建立預設管理員帳號: admin (預設密碼: admin123)，原有帳務資料已綁定至此帳號")
    except Exception as e:
        print(f"[Migration] 初始化預設使用者警告: {e}")
    finally:
        db.close()


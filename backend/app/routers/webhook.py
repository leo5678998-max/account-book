import logging
import os
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, Account
from ..schemas import (
    ApplePayWebhookPayload,
    ApplePayWebhookResponse,
    WebhookTokenResponse,
)
from ..services.auth_service import get_current_user
from ..services.webhook_service import (
    get_or_create_webhook_token,
    regenerate_webhook_token,
    find_user_by_webhook_token,
    process_apple_pay_transaction,
)

# 專屬 Webhook 交易與除錯日誌設置
LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "logs"))
os.makedirs(LOG_DIR, exist_ok=True)
WEBHOOK_LOG_FILE = os.path.join(LOG_DIR, "webhook.log")

webhook_logger = logging.getLogger("account_book.webhook")
webhook_logger.setLevel(logging.INFO)
if not webhook_logger.handlers:
    _fh = logging.FileHandler(WEBHOOK_LOG_FILE, encoding="utf-8")
    _fh.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    webhook_logger.addHandler(_fh)
    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("[%(asctime)s] [WEBHOOK-%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    webhook_logger.addHandler(_sh)

router = APIRouter(prefix="/api/webhook", tags=["Webhook Automation"])


def _extract_webhook_token(
    request: Request,
    query_token: Optional[str] = None,
    body_token: Optional[str] = None,
) -> Optional[str]:
    """
    從多種來源依序解析 Webhook Token：
    1. 自訂 HTTP Header: X-Webhook-Token
    2. 標準 Authorization: Bearer <token>
    3. URL 查詢參數: ?token=<token>
    4. 請求內文 JSON: {"token": "..."}
    """
    # 1. X-Webhook-Token
    header_token = request.headers.get("X-Webhook-Token")
    if header_token and header_token.strip():
        return header_token.strip()

    # 2. Authorization: Bearer <token>
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()
        if token:
            return token

    # 3. Query string
    if query_token and query_token.strip():
        return query_token.strip()

    # 4. JSON body
    if body_token and body_token.strip():
        return body_token.strip()

    return None


@router.post("/apple-pay", response_model=ApplePayWebhookResponse)
def handle_apple_pay_webhook(
    payload: ApplePayWebhookPayload,
    request: Request,
    token: Optional[str] = Query(None, description="使用者專屬 Webhook 安全金鑰"),
    db: Session = Depends(get_db)
):
    """
    接收 Apple Pay / iOS 捷徑自動化付款事件，驗證金鑰後自動新增交易紀錄並更新帳戶餘額。
    金鑰可置於 Header ('X-Webhook-Token'), Query 參數 ('?token=...'), 或 Body ('token')。
    """
    payload_dict = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    resolved_token = _extract_webhook_token(
        request=request,
        query_token=token,
        body_token=payload_dict.get("token")
    )

    if not resolved_token:
        webhook_logger.warning("[認證失敗] 未提供 Webhook 金鑰")
        raise HTTPException(
            status_code=401,
            detail="未提供 Webhook 金鑰。請於網址參數加上 ?token=<金鑰> 或傳入 Header 'X-Webhook-Token'"
        )

    user = find_user_by_webhook_token(db, resolved_token)
    if not user:
        webhook_logger.warning(f"[認證失敗] Webhook 金鑰無效: {resolved_token[:6]}***")
        raise HTTPException(
            status_code=401,
            detail="Webhook 金鑰無效或不存在，請至系統設定中確認或重新生成金鑰"
        )

    # 執行記帳處理
    try:
        tx = process_apple_pay_transaction(db, user_id=user.id, payload=payload_dict)
    except HTTPException as he:
        webhook_logger.warning(
            f"[記帳失敗] 原因: {he.detail} | App: {payload_dict.get('app')} | 標題: {payload_dict.get('title')} | 內文: {payload_dict.get('text')}"
        )
        raise he
    except Exception as e:
        webhook_logger.error(f"[系統異常] 錯誤: {e} | Payload: {payload_dict}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"記帳處理失敗: {str(e)}")

    # 查詢受影響帳戶最新資訊
    account = db.query(Account).filter(Account.id == tx.account_id).first()
    acc_name = account.name if account else "未知帳戶"
    webhook_logger.info(
        f"[記帳成功] NT$ {tx.amount} ({tx.category}) | 商家: {tx.description} | 帳戶: {acc_name} | App: {payload_dict.get('app')}"
    )

    return ApplePayWebhookResponse(
        status="success",
        message="Apple Pay 交易已成功自動記帳",
        transaction_id=tx.id,
        amount=tx.amount,
        category=tx.category,
        account_name=account.name if account else "未知帳戶",
        account_balance=account.balance if account else 0.0
    )


@router.post("/apple-pay/test", response_model=ApplePayWebhookResponse)
def test_apple_pay_webhook(
    payload: ApplePayWebhookPayload,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    在網頁設定中測試 Webhook 記帳邏輯 (已登入狀態直接觸發，免輸入 Token)
    """
    payload_dict = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
    tx = process_apple_pay_transaction(db, user_id=current_user.id, payload=payload_dict)

    account = db.query(Account).filter(Account.id == tx.account_id).first()

    return ApplePayWebhookResponse(
        status="success",
        message="Webhook 測試交易已成功寫入",
        transaction_id=tx.id,
        amount=tx.amount,
        category=tx.category,
        account_name=account.name if account else "未知帳戶",
        account_balance=account.balance if account else 0.0
    )


@router.get("/token", response_model=WebhookTokenResponse)
def get_user_webhook_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得當前使用者之 Webhook 專屬金鑰與端點路徑"""
    tok = get_or_create_webhook_token(db, current_user.id)
    return WebhookTokenResponse(
        webhook_token=tok,
        webhook_url=f"/api/webhook/apple-pay?token={tok}"
    )


@router.post("/token/regenerate", response_model=WebhookTokenResponse)
def regenerate_user_webhook_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """重新生成當前使用者之 Webhook 專屬金鑰 (使舊金鑰立即失效)"""
    new_tok = regenerate_webhook_token(db, current_user.id)
    return WebhookTokenResponse(
        webhook_token=new_tok,
        webhook_url=f"/api/webhook/apple-pay?token={new_tok}"
    )


@router.get("/logs")
def get_webhook_logs(
    limit: int = 40,
    current_user: User = Depends(get_current_user)
):
    """取得最近的 Webhook 自動記帳日誌 (包含成功、失敗原因與原始推播紀錄)"""
    if not os.path.exists(WEBHOOK_LOG_FILE):
        return {"logs": []}
    try:
        with open(WEBHOOK_LOG_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        return {"logs": lines[-limit:]}
    except Exception as e:
        return {"logs": [f"讀取日誌失敗: {str(e)}"]}

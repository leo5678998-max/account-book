import re
import secrets
from datetime import datetime
from typing import Optional, Any, Tuple, List
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import User, Account, Transaction, SystemSetting
from ..schemas import TransactionCreate
from .accounting_service import (
    get_setting,
    save_setting,
    get_default_debit_account,
    record_transaction,
    TX_TYPE_EXPENSE,
    CATEGORY_DEFAULT,
)

# ==============================================================================
# 領域常數定義 (Domain Constants)
# ==============================================================================
WEBHOOK_TOKEN_SETTING_KEY = "WEBHOOK_TOKEN"

# 智能自動分類關鍵字規則表 (依先後優先順序比對)
MERCHANT_CATEGORY_RULES: List[Tuple[str, List[str]]] = [
    (
        "飲食",
        [
            "7-11", "7-eleven", "全家", "familymart", "family", "萊爾富", "ok超商",
            "麥當勞", "mcdonald", "肯德基", "kfc", "摩斯", "mos burger",
            "星巴克", "starbucks", "路易莎", "louisa", "cama",
            "foodpanda", "uber eats", "ubereats", "熊貓",
            "餐廳", "食堂", "咖啡", "茶", "麵", "飯", "便當", "飲料",
            "手搖", "點心", "壽司", "火鍋", "牛排", "早午餐", "早餐", "宵夜",
            "清心", "麻古", "迷客夏", "五十嵐", "50嵐", "可不可", "得正",
            "爭鮮", "藏壽司", "壽司郎", "瓦城", "王品", "石二鍋", "陶板屋",
            "subway", "漢堡王", "burger king", "麵包", "烘焙", "拉麵", "烘培",
            "甜點", "蛋糕", "披薩", "pizza", "炸雞", "定食", "居酒屋", "小吃"
        ]
    ),
    (
        "交通",
        [
            "高鐵", "台鐵", "捷運", "悠遊卡", "一卡通", "icash",
            "uber", "yoxi", "line go", "計程車", "taxi",
            "中油", "台亞", "全國加油", "加油站", "加油", "停車", "嘟嘟房",
            "udrive", "irent", "goshare", "wemo", "停車大聲公",
            "車麻吉", "autopass", "etags", "國道", "機票", "航空", "長榮航空", "中華航空", "星宇"
        ]
    ),
    (
        "日常採買",
        [
            "全聯", "家樂福", "好市多", "costco", "大潤發", "愛買",
            "屈臣氏", "康是美", "寶雅", "poya", "蝦皮", "shopee",
            "momo", "pchome", "特力屋", "ikea", "無印良品", "muji",
            "uniqlo", "net", "gu", "zara", "超市", "市集", "文具",
            "生活百貨", "光南", "寶家", "大創", "daiso", "便利購", "松本清"
        ]
    ),
    (
        "娛樂休閒",
        [
            "威秀", "國賓", "秀泰", "電影", "cinema", "netflix",
            "spotify", "youtube", "disney", "apple.com/bill", "itunes",
            "app store", "google play", "steam", "playstation", "nintendo",
            "klook", "kkday", "飯店", "民宿", "旅館", "hotel", "ktv",
            "錢櫃", "好樂迪", "健身", "world gym", "健身工廠", "展覽", "門票"
        ]
    ),
    (
        "保險醫療",
        [
            "診所", "醫院", "藥局", "健保", "齒科", "牙醫", "眼科", "耳鼻喉",
            "皮膚科", "保險", "國泰人壽", "富邦人壽", "南山人壽", "掛號"
        ]
    )
]


# ==============================================================================
# 純商業邏輯與資料運算輔助函式 (Pure Business Logic)
# ==============================================================================
def parse_webhook_amount(amount_raw: Any) -> float:
    """
    純邏輯：解析輸入金額，支援 int, float 或帶幣別符號/千分位的字串 (如 'NT$ 1,200', '$50', '85.5')。
    若無效或金額小於等於 0，拋出 ValueError。
    """
    if amount_raw is None:
        raise ValueError("金額不可為空")

    if isinstance(amount_raw, (int, float)):
        val = float(amount_raw)
        if val <= 0:
            raise ValueError("金額必須大於 0")
        return round(abs(val), 2)

    # 字串前處理
    s = str(amount_raw).strip()
    # 移除常見貨幣符號、字樣與逗號
    s = s.replace(",", "").replace("$", "").replace("NT$", "").replace("NT", "").replace("TWD", "").replace("元", "").strip()

    # 正則提取數值
    match = re.search(r"[-+]?\d+(?:\.\d+)?", s)
    if not match:
        raise ValueError(f"無法解析金額格式: '{amount_raw}'")

    val = float(match.group(0))
    if val <= 0:
        raise ValueError("金額必須大於 0")
    return round(abs(val), 2)


def auto_categorize_merchant(merchant: Optional[str]) -> str:
    """
    純邏輯：根據商家名稱進行關鍵字比對，智能分類。
    若無相符或無商家名稱，回傳預設分類 CATEGORY_DEFAULT ('其他')。
    """
    if not merchant or not isinstance(merchant, str):
        return CATEGORY_DEFAULT

    m_lower = merchant.lower().strip()
    for cat, keywords in MERCHANT_CATEGORY_RULES:
        for kw in keywords:
            if kw.lower() in m_lower:
                return cat

    return CATEGORY_DEFAULT


def parse_webhook_datetime(date_raw: Any) -> datetime:
    """
    純邏輯：解析交易時間字串，支援 ISO 格式或常見日期格式；若無提供或解析失敗則回退至目前 UTC 時間。
    """
    if not date_raw:
        return datetime.utcnow()

    if isinstance(date_raw, datetime):
        return date_raw

    date_str = str(date_raw).strip()
    # 嘗試常見時間格式
    formats = [
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ]
    # 處理尾端 Z 或時區如 +08:00
    cleaned = re.sub(r"[+-]\d{2}:\d{2}$", "", date_str).rstrip("Z")

    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt)
        except ValueError:
            continue

    # 回退目前時間
    return datetime.utcnow()


# ==============================================================================
# 資料存取與領域服務函式 (Data Access & Service Layer)
# ==============================================================================
def get_or_create_webhook_token(db: Session, user_id: int) -> str:
    """取得特定使用者的 Webhook Token，若不存在則自動安全生成並寫入資料庫"""
    token = get_setting(db, WEBHOOK_TOKEN_SETTING_KEY, default="", user_id=user_id)
    if token and token.strip():
        return token.strip()

    new_token = secrets.token_urlsafe(32)
    save_setting(db, WEBHOOK_TOKEN_SETTING_KEY, new_token, user_id=user_id)
    db.commit()
    return new_token


def regenerate_webhook_token(db: Session, user_id: int) -> str:
    """重新生成特定使用者的 Webhook Token (金鑰外洩或需重設時使用)"""
    new_token = secrets.token_urlsafe(32)
    save_setting(db, WEBHOOK_TOKEN_SETTING_KEY, new_token, user_id=user_id)
    db.commit()
    return new_token


def find_user_by_webhook_token(db: Session, token: Optional[str]) -> Optional[User]:
    """根據 Webhook Token 尋找對應之 User 實體"""
    if not token or not isinstance(token, str):
        return None

    tok = token.strip()
    if not tok:
        return None

    # 查詢 SystemSetting 中值相符之紀錄
    setting = db.query(SystemSetting).filter(SystemSetting.value == tok).first()
    if not setting:
        return None

    # 確保該 setting key 確實為 WEBHOOK_TOKEN
    is_valid_key = (
        setting.key == WEBHOOK_TOKEN_SETTING_KEY
        or setting.key.endswith(f":{WEBHOOK_TOKEN_SETTING_KEY}")
    )
    if not is_valid_key:
        return None

    return db.query(User).filter(User.id == setting.user_id).first()


def resolve_target_account(db: Session, user_id: int, card_name: Optional[str] = None) -> Account:
    """
    匹配扣款帳戶邏輯：
    1. 若提供 card_name，依序以「完全吻合」、「模糊包含」、「卡號後四碼」比對使用者現有帳戶。
    2. 若未匹配或未提供，優先使用預設信用卡扣款帳戶 (Default Debit Account)。
    3. 若無預設，選取第一筆 CREDIT 信用卡帳戶或任一帳戶。
    4. 若該使用者完全無任何帳戶，自動建立預設 Apple Pay 錢包帳戶以保障交易不漏記。
    """
    user_accounts = db.query(Account).filter(Account.user_id == user_id).all()

    if not user_accounts:
        # 使用者尚未建立帳戶時，自動防呆建立預設錢包帳戶
        new_acc = Account(
            user_id=user_id,
            name="Apple Pay 錢包",
            account_type="CREDIT",
            balance=0.0,
            currency="TWD",
            is_dbs_default_debit=False
        )
        db.add(new_acc)
        db.commit()
        db.refresh(new_acc)
        return new_acc

    if card_name and isinstance(card_name, str):
        target_name = card_name.strip().lower()
        if target_name:
            # 1. 完全比對
            for acc in user_accounts:
                if acc.name and acc.name.lower() == target_name:
                    return acc

            # 2. 包含比對 (單向包含或多關鍵字比對)
            for acc in user_accounts:
                acc_lower = (acc.name or "").lower()
                if not acc_lower:
                    continue
                if target_name in acc_lower or acc_lower in target_name:
                    return acc
                # 若 card_name 包含多個單詞 (如 '國泰 CUBE')，檢查是否所有單詞皆包含於帳戶名稱中
                words = [w for w in target_name.split() if w]
                if len(words) > 1 and all(w in acc_lower for w in words):
                    return acc

            # 3. 卡號/帳號後四碼比對 (若 card_name 內含 4 位數字)
            digits = re.findall(r"\d{4}", target_name)
            if digits:
                for d in digits:
                    for acc in user_accounts:
                        if acc.account_number and d in acc.account_number:
                            return acc

    # 4. 回退：使用者預設扣款帳戶
    default_acc = get_default_debit_account(db, user_id=user_id)
    if default_acc:
        return default_acc

    # 5. 回退：第一筆 CREDIT 信用卡帳戶
    credit_acc = next((a for a in user_accounts if a.account_type == "CREDIT"), None)
    if credit_acc:
        return credit_acc

    # 6. 回退：使用者第一筆帳戶
    return user_accounts[0]


def process_apple_pay_transaction(db: Session, user_id: int, payload: dict) -> Transaction:
    """
    核心記帳流程：
    解析 Webhook Payload、驗證數值、智能匹配帳戶與分類，呼叫 record_transaction 建立交易並更新餘額。
    """
    # 1. 金額解析
    raw_amount = payload.get("amount")
    try:
        amount = parse_webhook_amount(raw_amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # 2. 帳戶匹配
    card_name = payload.get("card_name") or payload.get("card") or payload.get("account_name")
    target_acc = resolve_target_account(db, user_id=user_id, card_name=card_name)

    # 3. 商家與備註處理
    merchant = str(payload.get("merchant") or payload.get("title") or "").strip()
    note = str(payload.get("note") or payload.get("notes") or "").strip()

    if merchant and note:
        description = f"{merchant} - {note}"
    elif merchant:
        description = merchant
    elif note:
        description = note
    else:
        description = "Apple Pay 快速交易"

    # 4. 分類智能推導
    provided_category = str(payload.get("category") or "").strip()
    if provided_category and provided_category != CATEGORY_DEFAULT:
        category = provided_category
    else:
        category = auto_categorize_merchant(merchant or description)

    # 5. 時間處理
    tx_date = parse_webhook_datetime(payload.get("date"))

    # 6. 寫入交易紀錄
    tx_in = TransactionCreate(
        account_id=target_acc.id,
        amount=amount,
        tx_type=TX_TYPE_EXPENSE,
        category=category,
        description=description,
        date=tx_date,
        affects_balance=True
    )

    return record_transaction(db, tx_in, user_id=user_id)

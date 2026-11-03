import re
import secrets
import threading
from datetime import datetime, timedelta
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
    TX_TYPE_REFUND,
    CATEGORY_DEFAULT,
)

# ==============================================================================
# 領域常數定義 (Domain Constants)
# ==============================================================================
WEBHOOK_TOKEN_SETTING_KEY = "WEBHOOK_TOKEN"
_webhook_process_lock = threading.RLock()

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
            "dejeng", "oolong", "tea", "coffee", "cafe",
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
            "生活百貨", "光南", "寶家", "大創", "daiso", "便利購", "松本清",
            "微風", "breeze", "新光三越", "sogo", "遠百", "遠東百貨", "誠品"
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


def parse_notification_text(text: str, app: Optional[str] = None, title: Optional[str] = None) -> dict:
    """
    純商業邏輯：從推播通知原始文字 (App 通知 / 簡訊) 提取金額、店家、卡片與備註。
    支援 LINE Pay、台灣各大銀行推播 (國泰、中信、台新、玉山、星展、富邦、渣打、華南等) 及 Apple Pay / Google 錢包。
    """
    if not text and not title:
        return {"amount": None, "merchant": None, "card_name": None}

    raw_text = str(text or "").strip()
    raw_title = str(title or "").strip()
    raw_app = str(app or "").strip()
    combined = f"{raw_app} {raw_title} {raw_text}".strip()

    # 1. 提取金額
    amount = None
    # 模式 A: 貨幣符號或字樣 + 數字 (例如: NT$ 85, 新台幣 120, $150, TWD 300)
    m_amt = re.search(r'(?:NT\$|NTD|TWD|HKD|USD|\$|新台幣)\s*([0-9,]+(?:\.[0-9]+)?)', combined, re.IGNORECASE)
    if not m_amt:
        # 模式 B: 數字 + 元/TWD (例如: 85元, 150 元)
        m_amt = re.search(r'([0-9,]+(?:\.[0-9]+)?)\s*(?:元|TWD|NTD)', combined, re.IGNORECASE)
    if not m_amt:
        # 模式 C: 消費/扣款/付款/刷卡/金額 後方跟隨之金額數值
        m_amt = re.search(r'(?:消費|扣款|付款|刷卡|金額|交易)[^\d\r\n]{0,8}([0-9,]+(?:\.[0-9]+)?)', combined)

    if m_amt:
        raw_val = m_amt.group(1).replace(",", "").strip()
        try:
            val = float(raw_val)
            if val > 0:
                amount = val
        except ValueError:
            pass

    # 2. 提取商家名稱
    merchant = None
    # 先清除日期時間 (例如 10/29 02:00, 2026/10/29, 10月30日, 20:12) 以免誤觸「於 10/29 在 XX 消費」
    cleaned_for_mer = re.sub(r'(?:於|在)?\s*\d{1,4}[/\-]\d{1,2}(?:[/\-]\d{1,2})?', '', raw_text)
    cleaned_for_mer = re.sub(r'(?:於|在)?\s*\d{1,2}月\d{1,2}日?', '', cleaned_for_mer)
    cleaned_for_mer = re.sub(r'(?:於|在)?\s*\d{1,2}:\d{2}(?::\d{2})?', '', cleaned_for_mer)

    # 模式 A: 商店名稱/特店/店家/特店名稱/特約商店/商店: [店家] (優先匹配完整前綴)
    m_mer = re.search(r'(?:商店名稱|特約商店|特店名稱|店家名稱|商店|特店|店家)[：:\s]+([^\r\n,，。!！]+)', raw_text)
    if not m_mer:
        # 模式 B: 在/於 [店家] 消費/扣款/付款/刷卡/交易 (支援含空白之店家如 BREEZE CENTER, Uber Eats)
        m_mer = re.search(r'(?:在|於)\s*([^\r\n,，。!！]{2,30}?)\s*(?:消費|扣款|付款|刷卡|成功|交易)', cleaned_for_mer)

    if m_mer:
        merchant = m_mer.group(1).strip()
        # 清除常見支付前綴 (例如 LINEPAY*簡單早餐 -> 簡單早餐)
        merchant = re.sub(r'^(?:LINEPAY\*|LINEPAY_)', '', merchant)

    # 模式 C: 比對常見知名連鎖商家清單
    if not merchant:
        lower_text = combined.lower()
        for cat, keywords in MERCHANT_CATEGORY_RULES:
            for kw in keywords:
                if len(kw) >= 2 and kw.lower() in lower_text:
                    merchant = kw
                    break
            if merchant:
                break

    # 3. 提取卡片或帳戶名稱
    card_name = None
    m_digits = re.search(r'(?:末四碼|卡號(?:末四碼)?|後四碼)[：:\s]*(\d{4})', combined)
    if m_digits:
        card_name = m_digits.group(1)

    known_banks = [
        "國泰世華", "國泰", "中國信託", "中信", "台新", "玉山", "星展", "富邦", "台北富邦",
        "渣打", "華南", "郵局", "中華郵政", "永豐", "聯邦", "第一銀行", "兆豐", "新光", "LINE Pay", "街口"
    ]
    for b in known_banks:
        if b.lower() in combined.lower():
            if not card_name:
                card_name = b
            else:
                card_name = f"{b} {card_name}"
            break

    if not card_name and raw_app:
        card_name = raw_app.strip()

    # 4. 判斷是否為退款/退刷通知
    REFUND_KEYWORDS = ["退款", "退刷", "刷退", "沖正", "取消交易", "退貨"]
    is_refund = any(kw in combined for kw in REFUND_KEYWORDS)

    return {
        "amount": amount,
        "merchant": merchant,
        "card_name": card_name,
        "is_refund": is_refund
    }


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


def normalize_apple_pay_payload(payload: dict, db: Session, user_id: int) -> dict:
    """
    容錯前處理：
    1. 支援推播通知原始文字解析 (text / body / message)，自動提取金額、店家與卡片。
    2. 若使用者在 iOS 捷徑中誤將變數選在「左邊 (Key)」，導致鍵值倒置，自動偵測並還原。
    """
    cleaned = {k: v for k, v in payload.items() if v is not None}

    # 1. 支援推播通知原始文字解析 (例如 iOS 通知自動化傳入的 text / body / title)
    raw_text = str(cleaned.get("text") or cleaned.get("body") or cleaned.get("message") or "").strip()
    raw_title = str(cleaned.get("title") or "").strip()
    if raw_text or raw_title:
        parsed = parse_notification_text(
            raw_text,
            app=cleaned.get("app"),
            title=raw_title
        )
        if (cleaned.get("amount") is None or str(cleaned.get("amount")).strip() == "") and parsed.get("amount"):
            cleaned["amount"] = parsed["amount"]
        if not cleaned.get("merchant") and parsed.get("merchant"):
            cleaned["merchant"] = parsed["merchant"]
        if not cleaned.get("card_name") and parsed.get("card_name"):
            cleaned["card_name"] = parsed["card_name"]
        if parsed.get("is_refund"):
            cleaned["is_refund"] = True

    if cleaned.get("amount") is not None and str(cleaned.get("amount")).strip() != "":
        return cleaned

    # 2. 鍵值倒置容錯 (Key 為金額或商家名稱)
    STANDARD_KEYS = {"amount", "merchant", "card_name", "category", "note", "date", "token", "text", "app", "title", "body"}
    numeric_keys = []
    other_keys = []
    for k in payload.keys():
        if k in STANDARD_KEYS:
            continue
        try:
            val = parse_webhook_amount(k)
            numeric_keys.append((k, val))
        except (ValueError, TypeError):
            other_keys.append(k)

    if numeric_keys:
        cleaned["amount"] = numeric_keys[0][1]
        user_accounts = db.query(Account).filter(Account.user_id == user_id).all()
        account_names = [(a.name or "").lower() for a in user_accounts]

        for k in other_keys:
            if not k or not isinstance(k, str) or k in STANDARD_KEYS:
                continue
            k_strip = k.strip()
            if k_strip in ("文字", "0", "未命名", "null", "undefined"):
                continue
            k_lower = k_strip.lower()
            if any(k_lower in acc_name or acc_name in k_lower for acc_name in account_names if acc_name):
                cleaned["card_name"] = k_strip
            else:
                if not cleaned.get("merchant"):
                    cleaned["merchant"] = k_strip
                else:
                    cleaned["merchant"] += f" {k_strip}"

    return cleaned


def process_apple_pay_transaction(db: Session, user_id: int, payload: dict) -> Transaction:
    """
    核心記帳流程：
    解析 Webhook Payload、驗證數值、智能匹配帳戶與分類，呼叫 record_transaction 建立交易並更新餘額。
    使用 _webhook_process_lock 確保執行緒安全，防止雙重推播 (如 LINE Pay + 信用卡) 併發寫入造成重複記帳。
    """
    with _webhook_process_lock:
        db.expire_all()

        # 0. 容錯正規化 (支援推播文字解析與 iOS 捷徑鍵值倒置自動校正)
        payload = normalize_apple_pay_payload(payload, db, user_id)

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

        # 4.5. 判斷是否為退款/退刷交易 (Refund)
        is_refund = (
            payload.get("tx_type") == "REFUND"
            or payload.get("is_refund") is True
        )
        final_tx_type = TX_TYPE_REFUND if is_refund else TX_TYPE_EXPENSE
        if is_refund and not description.startswith("[退款]"):
            description = f"[退款] {description}"

        # 5. 時間處理
        tx_date = parse_webhook_datetime(payload.get("date"))

        # 5.5. 雙重通知智慧去重/合併 (Twin Notifications Auto-Merge within 120s)
        # 例如：同一筆消費同時觸發 LINE Pay 付款通知 與 銀行信用卡刷卡通知 (如 LINE Pay 艇長有限公司 vs 星展 Card+ CaptainLimited)
        time_window = timedelta(seconds=120)
        recent_duplicate = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.amount == amount,
                Transaction.tx_type == final_tx_type,
                Transaction.date >= tx_date - time_window,
                Transaction.date <= tx_date + time_window,
            )
            .order_by(Transaction.id.desc())
            .first()
        )
        if recent_duplicate:
            # 若新通知帶有更具體的商家名稱（非 LINE Pay 且比舊名稱更清楚，例如中文「艇長有限公司」優於銀行英文「CaptainLimited」），更新原紀錄描述與分類
            if merchant and merchant != "LINE Pay":
                is_better_description = (
                    recent_duplicate.description == "LINE Pay"
                    or (not re.search(r'[\u4e00-\u9fff]', recent_duplicate.description) and re.search(r'[\u4e00-\u9fff]', merchant))
                )
                if is_better_description:
                    recent_duplicate.description = merchant
                    recent_duplicate.category = category
                    db.commit()
                    db.refresh(recent_duplicate)
            return recent_duplicate

        # 6. 寫入交易紀錄
        tx_in = TransactionCreate(
            account_id=target_acc.id,
            amount=amount,
            tx_type=final_tx_type,
            category=category,
            description=description,
            date=tx_date,
            affects_balance=True
        )

        return record_transaction(db, tx_in, user_id=user_id)

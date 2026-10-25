import imaplib
import email
from email.header import decode_header
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session

from ..accounting_service import get_setting, save_setting

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

BANK_KEYWORDS = [
    "星展", "dbs", "國泰", "cathay", "中信", "中國信託", "ctbc",
    "玉山", "e.sun", "esun", "台新", "taishin", "富邦", "fubon",
    "永豐", "sinopac", "聯邦", "匯豐", "hsbc", "渣打", "華南",
    "第一銀行", "兆豐", "合庫", "新光", "遠東", "彰銀", "上海商銀"
]

BILL_KEYWORDS = [
    "信用卡", "電子帳單", "對帳單", "帳單", "estatement", "cbgcc", "statement"
]


def decode_mime_header(raw_val: Optional[str]) -> str:
    """安全解碼 MIME 郵件標頭或附件檔名 (支援 UTF-8 / Big5 等編碼)"""
    if not raw_val:
        return ""
    try:
        parts = decode_header(raw_val)
        decoded = []
        for content, charset in parts:
            if isinstance(content, bytes):
                enc = charset or "utf-8"
                try:
                    decoded.append(content.decode(enc, errors="replace"))
                except LookupError:
                    decoded.append(content.decode("utf-8", errors="replace"))
            else:
                decoded.append(str(content))
        return "".join(decoded).strip()
    except Exception:
        return str(raw_val).strip()


def resolve_imap_server(email_addr: str, custom_server: str = "") -> str:
    """根據信箱網域自動推斷對應的 IMAP 伺服器位址"""
    if custom_server and custom_server.strip():
        return custom_server.strip()
    addr = (email_addr or "").lower().strip()
    if "@yahoo." in addr:
        return "imap.mail.yahoo.com"
    if any(d in addr for d in ["@outlook.", "@hotmail.", "@live.", "@msn."]):
        return "outlook.office365.com"
    if "@icloud." in addr or "@me.com" in addr:
        return "imap.mail.me.com"
    return "imap.gmail.com"


class ImapService:
    """
    使用標準 IMAP SSL + 應用程式密碼 (App Password) 收取信用卡電子帳單 PDF。
    完全免除 Google OAuth 商業驗證、無 100 人限制、無 7 天 Token 過期問題，且支援各家信箱。
    """
    def __init__(self, db: Session, user_id: int = 1):
        self.db = db
        self.user_id = user_id

    @property
    def email_address(self) -> str:
        return get_setting(self.db, "IMAP_EMAIL", "", user_id=self.user_id).strip()

    @property
    def app_password(self) -> str:
        raw_pwd = get_setting(self.db, "IMAP_APP_PASSWORD", "", user_id=self.user_id)
        # 自動移除 Google 16 碼應用程式密碼中間的空白
        return "".join(raw_pwd.split())

    @property
    def imap_server(self) -> str:
        custom = get_setting(self.db, "IMAP_SERVER", "", user_id=self.user_id).strip()
        return resolve_imap_server(self.email_address, custom)

    def is_configured(self) -> bool:
        return bool(self.email_address and self.app_password)

    def test_connection(self, email_addr: Optional[str] = None, app_pwd: Optional[str] = None, server: Optional[str] = None) -> Dict[str, Any]:
        """測試 IMAP 信箱連線與應用程式密碼是否正確"""
        target_email = (email_addr if email_addr is not None else self.email_address).strip()
        raw_pwd = app_pwd if app_pwd is not None else self.app_password
        target_pwd = "".join(raw_pwd.split())
        target_server = resolve_imap_server(target_email, server if server is not None else self.imap_server)

        if not target_email or not target_pwd:
            return {"success": False, "message": "請填寫信箱帳號與 16 碼應用程式密碼"}

        mail = None
        try:
            mail = imaplib.IMAP4_SSL(target_server, 993, timeout=15)
            mail.login(target_email, target_pwd)
            status, messages = mail.select("INBOX", readonly=True)
            total_msgs = int(messages[0]) if (status == "OK" and messages and messages[0]) else 0
            mail.logout()
            return {
                "success": True,
                "message": f"連線成功！已連接 {target_server} (收件匣共 {total_msgs} 封信件)"
            }
        except imaplib.IMAP4.error as e:
            err_str = str(e)
            return {
                "success": False,
                "message": f"信箱驗證失敗：請確認已開啟 Google 兩步驟驗證，並填入 16 碼「應用程式密碼」而非一般登入密碼。({err_str})"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"無法連線至伺服器 {target_server}: {str(e)}"
            }
        finally:
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass

    def fetch_credit_card_bill_attachments(self, days: int = 60, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        透過 IMAP 搜尋最近 N 天內的信用卡電子帳單信件，並擷取 PDF 附件位元組
        """
        if not self.is_configured():
            raise ValueError("尚未設定 IMAP 信箱與應用程式密碼")

        since_dt = datetime.now() - timedelta(days=days)
        since_str = f"{since_dt.day:02d}-{MONTH_NAMES[since_dt.month - 1]}-{since_dt.year}"

        mail = None
        attachments_found: List[Dict[str, Any]] = []

        try:
            mail = imaplib.IMAP4_SSL(self.imap_server, 993, timeout=25)
            mail.login(self.email_address, self.app_password)
            mail.select("INBOX", readonly=True)

            status, data = mail.search(None, f'(SINCE "{since_str}")')
            if status != "OK" or not data or not data[0]:
                return []

            msg_nums = data[0].split()
            # 取最近 100 封信件進行批次標頭檢查 (大幅節省 95% 以上網路 round-trip 耗時)
            recent_nums = msg_nums[-100:]
            if not recent_nums:
                return []

            batch_nums = b",".join(recent_nums)
            hdr_status, hdr_data = mail.fetch(batch_nums, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE MESSAGE-ID)])")
            if hdr_status != "OK" or not hdr_data:
                return []

            matched_targets = []
            for item in hdr_data:
                if not isinstance(item, tuple) or len(item) < 2:
                    continue
                num_part = item[0].split()[0]
                raw_header = item[1]
                hdr_msg = email.message_from_bytes(raw_header)
                subject = decode_mime_header(hdr_msg.get("Subject", ""))
                subj_lower = subject.lower()
                is_bill_subject = any(kw in subj_lower for kw in BILL_KEYWORDS)
                if is_bill_subject:
                    matched_targets.append({
                        "num": num_part,
                        "subject": subject or "信用卡電子帳單",
                        "date_received": decode_mime_header(hdr_msg.get("Date", "")),
                        "msg_id_hdr": decode_mime_header(hdr_msg.get("Message-ID", "")).strip("<> ")
                    })

            # 從最新的匹配信件依序提取 PDF 附件
            for target in reversed(matched_targets):
                if len(attachments_found) >= max_results:
                    break

                num = target["num"]
                subject = target["subject"]
                date_received = target["date_received"]
                msg_id_hdr = target["msg_id_hdr"]

                # 僅針對標題包含帳單關鍵字的信件下載完整信件內容以提取 PDF 附件
                msg_status, msg_data = mail.fetch(num, "(BODY.PEEK[])")
                if msg_status != "OK" or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
                full_msg = email.message_from_bytes(raw_email)

                for part in full_msg.walk():
                    if part.get_content_maintype() == "multipart":
                        continue

                    raw_filename = part.get_filename()
                    filename = decode_mime_header(raw_filename) if raw_filename else ""
                    content_type = (part.get_content_type() or "").lower()

                    is_pdf = filename.lower().endswith(".pdf") or (content_type == "application/pdf" and filename)
                    if not is_pdf:
                        continue

                    file_bytes = part.get_payload(decode=True)
                    if not file_bytes:
                        continue

                    unique_msg_id = msg_id_hdr or f"imap-{self.email_address}-{num.decode('ascii', errors='ignore')}-{filename}"

                    attachments_found.append({
                        "message_id": unique_msg_id,
                        "subject": subject,
                        "date_received": date_received,
                        "filename": filename or "statement.pdf",
                        "pdf_bytes": file_bytes
                    })

            return attachments_found
        finally:
            if mail:
                try:
                    mail.logout()
                except Exception:
                    pass


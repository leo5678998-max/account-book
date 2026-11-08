import sys
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from datetime import datetime, date
from typing import Optional
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from ..core.database import SessionLocal
from ..models import User, Account, Bill
from .accounting_service import get_setting, execute_bill_payment, execute_auto_salary_credits
from .integrations.gmail_service import GmailService
from .integrations.imap_service import ImapService
from .integrations.dbs_parser import parse_dbs_pdf, normalize_date
from .integrations.ai_parser import parse_document_with_gemini
from .stock_service import refresh_all_stock_prices
from .recurring_service import execute_auto_recurring_debits

scheduler = BackgroundScheduler()


def sync_bills_from_gmail(db: Session = None, user_id: int = 1):
    """
    從 IMAP 信箱 (應用程式密碼) 或 Gmail OAuth 撈取信用卡電子帳單並解析寫入資料庫。
    優先使用免審查、零費用的 IMAP 應用程式密碼機制。
    """
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        imap_service = ImapService(db, user_id=user_id)
        gmail_service = GmailService(db, user_id=user_id)

        use_imap = imap_service.is_configured()
        use_gmail_oauth = (not use_imap) and gmail_service.is_connected()

        if not use_imap and not use_gmail_oauth:
            print(f"[Scheduler] 使用者 (ID={user_id}) 尚未設定 IMAP 應用程式密碼或 Gmail 授權，略過自動同步")
            return {
                "status": "skipped",
                "message": "尚未設定收信信箱，請至右上角【設定】填寫 Gmail 信箱與 16 碼「應用程式密碼 (App Password)」"
            }

        id_card_pwd = get_setting(db, "ID_CARD_PASSWORD", "", user_id=user_id)
        dbs_pwd = get_setting(db, "DBS_PDF_PASSWORD", "", user_id=user_id)
        pwd_candidates = [p.strip() for p in [id_card_pwd, dbs_pwd] if p and p.strip()]

        if not pwd_candidates:
            print(f"[Scheduler] 使用者 (ID={user_id}) 尚未設定帳單解密密碼")
            return {
                "status": "error",
                "message": "尚未設定帳單解密密碼 (請在【設定】中填寫身分證字號或銀行 PDF 密碼)"
            }

        # 每位使用者獨立使用自己的 Gemini API Key (不共用)
        gemini_key = get_setting(db, "GEMINI_API_KEY", "", user_id=user_id).strip()

        # 找出該使用者的預設扣款帳戶
        default_debit_acc = db.query(Account).filter(
            Account.user_id == user_id,
            Account.is_dbs_default_debit == True
        ).first()
        debit_acc_id = default_debit_acc.id if default_debit_acc else None

        if use_imap:
            attachments = imap_service.fetch_credit_card_bill_attachments(days=60, max_results=10)
        else:
            attachments = gmail_service.fetch_dbs_bill_attachments(max_results=5)

        new_bills_count = 0
        errors = []

        for att in attachments:
            msg_id = att["message_id"]
            scoped_msg_id = f"u{user_id}:{msg_id}"
            filename = att["filename"] or ""

            # 檔名防呆：若是 CBGCS (Consumer Savings 存款帳戶月結單)，直接跳過
            if filename.startswith("CBGCS"):
                print(f"[Scheduler] 檔案 {filename} 為星展存款對帳單，自動略過")
                continue

            # 檢查該使用者是否已處理過此信件
            existing_bill = db.query(Bill).filter(
                Bill.user_id == user_id,
                (Bill.email_message_id == scoped_msg_id) | (Bill.email_message_id == msg_id)
            ).first()
            if existing_bill:
                continue

            parse_result = None

            # 優先使用該使用者自備的 Gemini API Key 進行高精度解析
            if gemini_key:
                ai_res = parse_document_with_gemini(att["pdf_bytes"], filename, gemini_key, pwd_candidates)
                if ai_res.get("success"):
                    if ai_res.get("document_type") != "CREDIT_CARD_BILL":
                        print(f"[Scheduler] AI 辨識 {filename} 為非信用卡單據 ({ai_res.get('document_type')})，略過")
                        continue

                    due_date_obj = normalize_date(ai_res.get("due_date")) if ai_res.get("due_date") else None
                    stmt_date_obj = normalize_date(ai_res.get("statement_date")) if ai_res.get("statement_date") else None

                    parse_result = {
                        "bank_name": ai_res.get("bank_or_company") or "信用卡帳單",
                        "statement_month": ai_res.get("statement_month"),
                        "statement_date": stmt_date_obj,
                        "due_date": due_date_obj,
                        "total_amount": float(ai_res.get("total_amount", 0.0)),
                        "minimum_amount": float(ai_res.get("minimum_amount", 0.0)),
                    }

            # 若無 AI 或 AI 失敗，使用本地星展解析器
            if not parse_result:
                local_fallback_pwd = dbs_pwd or id_card_pwd
                local_res = parse_dbs_pdf(att["pdf_bytes"], local_fallback_pwd)
                if not local_res.get("success"):
                    errors.append(f"信件 {att['subject']} 解析失敗: {local_res.get('error')}")
                    continue
                parse_result = local_res

            due_date = parse_result.get("due_date")
            if not due_date:
                print(f"[Scheduler] 檔案 {filename} 無繳款截止日，略過信用卡扣款記錄")
                continue

            today = date.today()
            initial_status = "PAID" if due_date < today else "PENDING"

            new_bill = Bill(
                user_id=user_id,
                bank_name=parse_result.get("bank_name") or "信用卡帳單",
                statement_month=parse_result.get("statement_month"),
                statement_date=parse_result.get("statement_date"),
                due_date=due_date,
                total_amount=parse_result.get("total_amount", 0.0),
                minimum_amount=parse_result.get("minimum_amount", 0.0),
                status=initial_status,
                email_message_id=scoped_msg_id,
                pdf_filename=filename,
                debit_account_id=debit_acc_id
            )
            db.add(new_bill)
            db.commit()
            new_bills_count += 1
            print(f"[Scheduler] 成功匯入新帳單 (user={user_id}): {new_bill.statement_month} 應繳 {new_bill.total_amount}")

        return {
            "status": "success",
            "mode": "IMAP" if use_imap else "GMAIL_OAUTH",
            "imported_count": new_bills_count,
            "errors": errors
        }

    except Exception as e:
        print(f"[Scheduler] 同步信箱帳單過程發生錯誤: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if close_db:
            db.close()


def execute_auto_debits(db: Session = None, user_id: Optional[int] = None):
    """檢查所有已到期/即將到期的帳單，並從指定存款帳戶自動扣款（需使用者明確開啟 AUTO_DEBIT_BILLS）"""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        today = date.today()
        if user_id is not None:
            is_enabled = get_setting(db, "AUTO_DEBIT_BILLS", "false", user_id=user_id).lower() in ("true", "1")
            if not is_enabled:
                print(f"[Scheduler] 使用者 (ID={user_id}) 未開啟帳單自動扣款，略過扣款")
                return {"status": "skipped", "message": "未啟用帳單自動扣款功能", "paid_count": 0}

        query = db.query(Bill).filter(
            Bill.status == "PENDING",
            Bill.due_date <= today
        )
        if user_id is not None:
            query = query.filter(Bill.user_id == user_id)

        pending_bills = query.all()

        paid_count = 0
        for bill in pending_bills:
            bill_uid = bill.user_id or 1
            if not (get_setting(db, "AUTO_DEBIT_BILLS", "false", user_id=bill_uid).lower() in ("true", "1")):
                print(f"[Scheduler] 帳單 ID {bill.id} 所屬使用者 (ID={bill_uid}) 未開啟自動扣款，略過")
                continue
            try:
                acc = execute_bill_payment(db, bill, is_auto=True, user_id=bill.user_id)
                paid_count += 1
                print(f"[Scheduler] 成功自動扣款: 從【{acc.name}】扣除 {bill.total_amount}，更新餘額為 {acc.balance}")
            except Exception as inner_err:
                print(f"[Scheduler] 帳單 ID {bill.id} 自動扣款略過: {inner_err}")
                continue

        return {"status": "success", "paid_count": paid_count}
    except Exception as e:
        print(f"[Scheduler] 自動扣款過程發生錯誤: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if close_db:
            db.close()


def scheduled_daily_routine():
    """每日排程任務：為所有使用者撈取新帳單、執行自動扣款（若已啟用），並更新股票最新現價"""
    print(f"[{datetime.now()}] 觸發每日自動巡檢任務...")
    db = SessionLocal()
    try:
        users = db.query(User).all()
        for u in users:
            sync_bills_from_gmail(db, user_id=u.id)
            is_enabled = get_setting(db, "AUTO_DEBIT_BILLS", "false", user_id=u.id).lower() in ("true", "1")
            if is_enabled:
                execute_auto_debits(db, user_id=u.id)
            else:
                print(f"[Scheduler] 使用者 (ID={u.id}) 停用帳單自動扣款，僅同步帳單不扣款")
        execute_auto_salary_credits(db)
        execute_auto_recurring_debits(db)
        refresh_all_stock_prices(db)
    except Exception as e:
        print(f"[Scheduler] 每日巡檢任務發生錯誤: {e}")
    finally:
        db.close()


def start_scheduler():
    if not scheduler.running:
        scheduler.add_job(scheduled_daily_routine, 'cron', hour=3, minute=0, id='daily_bill_job')
        scheduler.start()
        print("[Scheduler] 排程服務已啟動 (每天凌晨 03:00 執行自動抓帳單與扣款)")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()

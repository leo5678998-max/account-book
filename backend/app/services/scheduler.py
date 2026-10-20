from datetime import datetime, date
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from ..database import SessionLocal
from ..models import Account, Transaction, Bill, SystemSetting
from .gmail_service import GmailService
from .dbs_parser import parse_dbs_pdf

scheduler = BackgroundScheduler()

def get_db_setting(db: Session, key: str) -> str:
    s = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    return s.value if s and s.value else ""

def sync_bills_from_gmail(db: Session = None):
    """從 Gmail 撈取星展銀行帳單並解析寫入資料庫"""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        gmail_service = GmailService(db)
        if not gmail_service.is_connected():
            print("[Scheduler] Gmail 尚未授權串接，略過自動同步")
            return {"status": "skipped", "message": "Gmail 尚未授權"}

        pdf_password = get_db_setting(db, "DBS_PDF_PASSWORD")
        if not pdf_password:
            print("[Scheduler] 尚未設定星展 PDF 密碼 (身分證/生日)")
            return {"status": "error", "message": "尚未設定星展 PDF 帳單密碼"}

        # 找出預設扣款帳戶
        default_debit_acc = db.query(Account).filter(Account.is_dbs_default_debit == True).first()
        debit_acc_id = default_debit_acc.id if default_debit_acc else None

        attachments = gmail_service.fetch_dbs_bill_attachments(max_results=5)
        new_bills_count = 0
        errors = []

        for att in attachments:
            msg_id = att["message_id"]
            # 檢查是否已處理過
            existing_bill = db.query(Bill).filter(Bill.email_message_id == msg_id).first()
            if existing_bill:
                continue

            # 解密與解析
            parse_result = parse_dbs_pdf(att["pdf_bytes"], pdf_password)
            if not parse_result.get("success"):
                errors.append(f"信件 {att['subject']} 解析失敗: {parse_result.get('error')}")
                continue

            new_bill = Bill(
                bank_name="星展銀行",
                statement_month=parse_result.get("statement_month"),
                statement_date=parse_result.get("statement_date"),
                due_date=parse_result.get("due_date"),
                total_amount=parse_result.get("total_amount", 0.0),
                minimum_amount=parse_result.get("minimum_amount", 0.0),
                status="PENDING",
                email_message_id=msg_id,
                pdf_filename=att["filename"],
                debit_account_id=debit_acc_id
            )
            db.add(new_bill)
            db.commit()
            new_bills_count += 1
            print(f"[Scheduler] 成功匯入新帳單: {new_bill.statement_month} 應繳 {new_bill.total_amount}，截止日 {new_bill.due_date}")

        return {
            "status": "success",
            "imported_count": new_bills_count,
            "errors": errors
        }

    except Exception as e:
        print(f"[Scheduler] 同步 Gmail 過程發生錯誤: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if close_db:
            db.close()

def execute_auto_debits(db: Session = None):
    """檢查所有已到期/即將到期的帳單，並從指定存款帳戶自動扣款"""
    close_db = False
    if db is None:
        db = SessionLocal()
        close_db = True

    try:
        today = date.today()
        # 找出狀態為 PENDING 且 扣款日 <= 今天的帳單
        pending_bills = db.query(Bill).filter(
            Bill.status == "PENDING",
            Bill.due_date <= today
        ).all()

        paid_count = 0
        for bill in pending_bills:
            if not bill.debit_account_id:
                # 若未綁定，找預設扣款帳戶
                default_acc = db.query(Account).filter(Account.is_dbs_default_debit == True).first()
                if default_acc:
                    bill.debit_account_id = default_acc.id

            if not bill.debit_account_id:
                print(f"[Scheduler] 帳單 ID {bill.id} 尚未指定扣款帳戶，無法自動扣款")
                continue

            acc = db.query(Account).filter(Account.id == bill.debit_account_id).first()
            if not acc:
                continue

            # 執行扣款
            acc.balance -= bill.total_amount
            tx = Transaction(
                date=datetime.now(),
                amount=bill.total_amount,
                tx_type="EXPENSE",
                account_id=acc.id,
                category="信用卡費",
                description=f"{bill.bank_name} 信用卡自動扣款 ({bill.statement_month} 帳單)",
                bill_id=bill.id
            )
            db.add(tx)
            db.flush()

            bill.status = "PAID"
            bill.paid_date = datetime.now()
            bill.paid_transaction_id = tx.id
            db.commit()
            paid_count += 1
            print(f"[Scheduler] 成功自動扣款: 從【{acc.name}】扣除 {bill.total_amount}，更新餘額為 {acc.balance}")

        return {"status": "success", "paid_count": paid_count}
    except Exception as e:
        print(f"[Scheduler] 自動扣款過程發生錯誤: {e}")
        return {"status": "error", "message": str(e)}
    finally:
        if close_db:
            db.close()

def scheduled_daily_routine():
    """每日排程任務：先撈取新帳單，再檢查是否有需扣款的帳單"""
    print(f"[{datetime.now()}] 觸發每日自動巡檢任務...")
    sync_bills_from_gmail()
    execute_auto_debits()

def start_scheduler():
    if not scheduler.running:
        # 設定每天凌晨 3:00 自動執行一次巡檢
        scheduler.add_job(scheduled_daily_routine, 'cron', hour=3, minute=0, id='daily_bill_job')
        scheduler.start()
        print("[Scheduler] 排程服務已啟動 (每天凌晨 03:00 執行自動抓帳單與扣款)")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()


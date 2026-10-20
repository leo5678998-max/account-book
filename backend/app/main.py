import sys
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import os
import json
from datetime import datetime
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from typing import List, Optional

from .database import engine, Base, get_db
from .models import Account, Transaction, Bill, SystemSetting
from .schemas import (
    AccountCreate, AccountUpdate, AccountResponse,
    TransactionCreate, TransactionResponse,
    BillResponse, SettingsUpdate, SettingsStatus
)
from .services.gmail_service import GmailService
from .services.dbs_parser import parse_dbs_pdf
from .services.scheduler import start_scheduler, stop_scheduler, sync_bills_from_gmail, execute_auto_debits

# 初始化資料表
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Personal Finance & Auto Bill Debit",
    description="多帳戶資產記帳與星展銀行 Gmail 信用卡帳單自動扣款系統",
    version="1.0.0"
)

# 支援跨來源存取 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Account Book API is running"}


@app.on_event("startup")
def on_startup():
    start_scheduler()

@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()

# ================= 帳戶 API =================
@app.get("/api/accounts", response_model=List[AccountResponse])
def get_accounts(db: Session = Depends(get_db)):
    return db.query(Account).order_by(Account.id.asc()).all()

@app.post("/api/accounts", response_model=AccountResponse)
def create_account(account_in: AccountCreate, db: Session = Depends(get_db)):
    # 若設為星展預設扣款帳戶，先將其他帳戶重置
    if account_in.is_dbs_default_debit:
        db.query(Account).update({Account.is_dbs_default_debit: False})
        
    account = Account(**account_in.dict())
    db.add(account)
    db.commit()
    db.refresh(account)
    return account

@app.put("/api/accounts/{account_id}", response_model=AccountResponse)
def update_account(account_id: int, account_in: AccountUpdate, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="找不到該帳戶")
    
    update_data = account_in.dict(exclude_unset=True)
    if update_data.get("is_dbs_default_debit"):
        db.query(Account).update({Account.is_dbs_default_debit: False})

    for field, val in update_data.items():
        setattr(acc, field, val)

    db.commit()
    db.refresh(acc)
    return acc

@app.delete("/api/accounts/{account_id}")
def delete_account(account_id: int, db: Session = Depends(get_db)):
    acc = db.query(Account).filter(Account.id == account_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="找不到該帳戶")
    db.delete(acc)
    db.commit()
    return {"status": "success", "message": "帳戶已刪除"}

# ================= 交易記帳 API =================
@app.get("/api/transactions", response_model=List[TransactionResponse])
def get_transactions(limit: int = 100, db: Session = Depends(get_db)):
    return db.query(Transaction).order_by(Transaction.date.desc(), Transaction.id.desc()).limit(limit).all()

@app.post("/api/transactions", response_model=TransactionResponse)
def create_transaction(tx_in: TransactionCreate, db: Session = Depends(get_db)):
    source_acc = db.query(Account).filter(Account.id == tx_in.account_id).first()
    if not source_acc:
        raise HTTPException(status_code=404, detail="來源帳戶不存在")

    # 更新帳戶餘額
    if tx_in.tx_type == "EXPENSE":
        source_acc.balance -= tx_in.amount
    elif tx_in.tx_type == "INCOME":
        source_acc.balance += tx_in.amount
    elif tx_in.tx_type == "TRANSFER":
        if not tx_in.target_account_id:
            raise HTTPException(status_code=400, detail="轉帳必須指定目標帳戶")
        target_acc = db.query(Account).filter(Account.id == tx_in.target_account_id).first()
        if not target_acc:
            raise HTTPException(status_code=404, detail="轉帳目標帳戶不存在")
        source_acc.balance -= tx_in.amount
        target_acc.balance += tx_in.amount

    tx_data = tx_in.dict()
    if not tx_data.get("date"):
        tx_data["date"] = datetime.utcnow()

    tx = Transaction(**tx_data)
    db.add(tx)
    db.commit()
    db.refresh(tx)
    return tx

# ================= 信用卡帳單 API =================
@app.get("/api/bills", response_model=List[BillResponse])
def get_bills(db: Session = Depends(get_db)):
    return db.query(Bill).order_by(Bill.due_date.desc()).all()

@app.post("/api/bills/{bill_id}/pay")
def manual_pay_bill(bill_id: int, account_id: Optional[int] = None, db: Session = Depends(get_db)):
    """手動立即為特定帳單執行扣款"""
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="帳單不存在")
    if bill.status == "PAID":
        raise HTTPException(status_code=400, detail="該帳單已完成扣款")

    debit_id = account_id or bill.debit_account_id
    if not debit_id:
        default_acc = db.query(Account).filter(Account.is_dbs_default_debit == True).first()
        if default_acc:
            debit_id = default_acc.id

    if not debit_id:
        raise HTTPException(status_code=400, detail="請指定扣款帳戶")

    acc = db.query(Account).filter(Account.id == debit_id).first()
    if not acc:
        raise HTTPException(status_code=404, detail="扣款帳戶不存在")

    acc.balance -= bill.total_amount
    tx = Transaction(
        date=datetime.utcnow(),
        amount=bill.total_amount,
        tx_type="EXPENSE",
        account_id=acc.id,
        category="信用卡費",
        description=f"{bill.bank_name} 信用卡手動扣款 ({bill.statement_month} 帳單)",
        bill_id=bill.id
    )
    db.add(tx)
    db.flush()

    bill.status = "PAID"
    bill.paid_date = datetime.utcnow()
    bill.paid_transaction_id = tx.id
    bill.debit_account_id = acc.id
    db.commit()

    return {"status": "success", "message": f"已從【{acc.name}】扣除 NT$ {bill.total_amount:,.0f}"}

# ================= Gmail 同步與手動上傳 PDF =================
@app.post("/api/sync/gmail")
def trigger_gmail_sync(db: Session = Depends(get_db)):
    """手動點擊觸發 Gmail 帳單抓取"""
    result = sync_bills_from_gmail(db)
    return result

@app.post("/api/sync/auto-debit")
def trigger_auto_debit(db: Session = Depends(get_db)):
    """手動觸發到期帳單扣款檢驗"""
    result = execute_auto_debits(db)
    return result

@app.post("/api/bills/upload-pdf")
async def upload_pdf_bill(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """提供手動上傳星展加密 PDF 測試與手動補登功能"""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="僅支援 PDF 檔案")

    pdf_bytes = await file.read()
    
    # 若未帶入密碼，嘗試從系統設定讀取
    if not password:
        s = db.query(SystemSetting).filter(SystemSetting.key == "DBS_PDF_PASSWORD").first()
        password = s.value if s else ""

    if not password:
        raise HTTPException(status_code=400, detail="請輸入解密密碼或先在後台設定預設帳單密碼")

    res = parse_dbs_pdf(pdf_bytes, password)
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("error"))

    default_acc = db.query(Account).filter(Account.is_dbs_default_debit == True).first()

    bill = Bill(
        bank_name="星展銀行",
        statement_month=res.get("statement_month"),
        statement_date=res.get("statement_date"),
        due_date=res.get("due_date"),
        total_amount=res.get("total_amount", 0.0),
        minimum_amount=res.get("minimum_amount", 0.0),
        status="PENDING",
        pdf_filename=file.filename,
        debit_account_id=default_acc.id if default_acc else None
    )
    db.add(bill)
    db.commit()
    db.refresh(bill)

    return {"status": "success", "bill": res}

# ================= 系統與 Google OAuth 設定 API =================
@app.get("/api/settings", response_model=SettingsStatus)
def get_settings_status(db: Session = Depends(get_db)):
    gmail_service = GmailService(db)
    has_pwd = bool(db.query(SystemSetting).filter(SystemSetting.key == "DBS_PDF_PASSWORD", SystemSetting.value != "").first())
    has_client_id = bool(db.query(SystemSetting).filter(SystemSetting.key == "GOOGLE_CLIENT_ID", SystemSetting.value != "").first()) or bool(os.getenv("GOOGLE_CLIENT_ID"))
    default_acc = db.query(Account).filter(Account.is_dbs_default_debit == True).first()
    salary_setting = db.query(SystemSetting).filter(SystemSetting.key == "MONTHLY_SALARY").first()
    salary = float(salary_setting.value) if salary_setting and salary_setting.value else 50000.0

    return SettingsStatus(
        is_google_connected=gmail_service.is_connected(),
        has_pdf_password=has_pwd,
        google_client_id_configured=has_client_id,
        default_debit_account_name=default_acc.name if default_acc else None,
        monthly_salary=salary
    )

@app.post("/api/settings")
def update_settings(settings: SettingsUpdate, db: Session = Depends(get_db)):
    if settings.google_client_id is not None:
        _save_setting(db, "GOOGLE_CLIENT_ID", settings.google_client_id)
    if settings.google_client_secret is not None:
        _save_setting(db, "GOOGLE_CLIENT_SECRET", settings.google_client_secret)
    if settings.google_redirect_uri is not None:
        _save_setting(db, "GOOGLE_REDIRECT_URI", settings.google_redirect_uri)
    if settings.dbs_pdf_password is not None:
        _save_setting(db, "DBS_PDF_PASSWORD", settings.dbs_pdf_password)
    if settings.monthly_salary is not None:
        _save_setting(db, "MONTHLY_SALARY", str(settings.monthly_salary))
    if settings.default_debit_account_id is not None:
        db.query(Account).update({Account.is_dbs_default_debit: False})
        db.query(Account).filter(Account.id == settings.default_debit_account_id).update({Account.is_dbs_default_debit: True})

    db.commit()
    return {"status": "success", "message": "設定已更新"}

def _save_setting(db: Session, key: str, value: str):
    item = db.query(SystemSetting).filter(SystemSetting.key == key).first()
    if not item:
        item = SystemSetting(key=key, value=value)
        db.add(item)
    else:
        item.value = value

# Google OAuth 流程
@app.get("/api/auth/google/url")
def get_google_auth_url(redirect_uri: Optional[str] = None, db: Session = Depends(get_db)):
    gmail = GmailService(db)
    try:
        url = gmail.get_auth_url(redirect_uri=redirect_uri)
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/auth/google/callback")
def google_auth_callback(code: str, state: Optional[str] = None, db: Session = Depends(get_db)):
    gmail = GmailService(db)
    try:
        gmail.handle_auth_callback(code=code)
        # 授權成功後導向前端首頁
        return RedirectResponse(url="/?auth=success")
    except Exception as e:
        return {"status": "error", "message": str(e)}

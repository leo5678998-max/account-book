import sys
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import os
import json
from datetime import datetime, date
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
    BillCreate, BillUpdate, BillResponse,
    DocumentParseResponse, SalaryApplyRequest,
    SettingsUpdate, SettingsStatus
)
from .services.gmail_service import GmailService
from .services.dbs_parser import parse_dbs_pdf, normalize_date
from .services.ai_parser import parse_document_with_gemini
from .services.scheduler import start_scheduler, stop_scheduler, sync_bills_from_gmail, execute_auto_debits

# 初始化資料表
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Personal Finance & Auto Bill Debit",
    description="多帳戶資產記帳、AI 智能多單據辨識 (各家信用卡/薪資單) 與自動扣款系統",
    version="2.0.0"
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

# ================= 信用卡帳單 API (含增修查刪) =================
@app.get("/api/bills", response_model=List[BillResponse])
def get_bills(db: Session = Depends(get_db)):
    return db.query(Bill).order_by(Bill.due_date.desc()).all()

@app.post("/api/bills", response_model=BillResponse)
def create_bill(bill_in: BillCreate, db: Session = Depends(get_db)):
    bill = Bill(**bill_in.dict())
    if not bill.debit_account_id:
        default_acc = db.query(Account).filter(Account.is_dbs_default_debit == True).first()
        if default_acc:
            bill.debit_account_id = default_acc.id

    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill

@app.put("/api/bills/{bill_id}", response_model=BillResponse)
def update_bill(bill_id: int, bill_in: BillUpdate, db: Session = Depends(get_db)):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到該帳單")

    update_data = bill_in.dict(exclude_unset=True)
    for field, val in update_data.items():
        setattr(bill, field, val)

    db.commit()
    db.refresh(bill)
    return bill

@app.delete("/api/bills/{bill_id}")
def delete_bill(bill_id: int, db: Session = Depends(get_db)):
    bill = db.query(Bill).filter(Bill.id == bill_id).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到該帳單")
    db.delete(bill)
    db.commit()
    return {"status": "success", "message": "帳單已刪除"}

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

# ================= 🤖 AI 多模態智慧單據辨識 (支援各家帳單/薪資單/圖片/PDF) =================
@app.post("/api/ai/parse-document", response_model=DocumentParseResponse)
async def parse_document(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    接收 PDF 或 圖片，自動辨識是哪家銀行的信用卡帳單或薪資單，回傳預覽資訊供使用者核對
    """
    file_bytes = await file.read()
    
    # 1. 取得 Gemini API Key (優先從 DB，次之從環境變數)
    key_setting = db.query(SystemSetting).filter(SystemSetting.key == "GEMINI_API_KEY").first()
    gemini_key = key_setting.value if key_setting and key_setting.value else os.getenv("GEMINI_API_KEY", "")

    # 若未帶入密碼，嘗試從系統設定讀取
    if not password:
        s = db.query(SystemSetting).filter(SystemSetting.key == "DBS_PDF_PASSWORD").first()
        password = s.value if s else ""

    # 若有設定 Gemini API Key，直接使用 AI 進行多模態辨識
    if gemini_key:
        res = parse_document_with_gemini(
            file_bytes=file_bytes,
            filename=file.filename,
            api_key=gemini_key,
            password=password
        )
        if res.get("success"):
            return DocumentParseResponse(
                success=True,
                document_type=res.get("document_type", "CREDIT_CARD_BILL"),
                bank_or_company=res.get("bank_or_company", "未知機構"),
                statement_month=res.get("statement_month"),
                total_amount=float(res.get("total_amount", 0.0)),
                minimum_amount=float(res.get("minimum_amount", 0.0)),
                due_date=res.get("due_date"),
                statement_date=res.get("statement_date"),
                notes=res.get("notes"),
                confidence_summary=res.get("confidence_summary"),
                raw_snippet=res.get("raw_snippet")
            )
        else:
            # AI 辨識失敗時若為 PDF 可 fallback 至本地 parser
            print(f"[AI Parser] Gemini 辨識失敗: {res.get('error')}，嘗試本地解析")

    # 若沒有 Gemini Key，且上傳為 PDF，嘗試本地 fallback (星展)
    if file.filename.lower().endswith(".pdf"):
        if not password:
            raise HTTPException(status_code=400, detail="本地 PDF 解析需要解密密碼，或請設定 GEMINI_API_KEY 啟用 AI 辨識")

        local_res = parse_dbs_pdf(file_bytes, password)
        if not local_res.get("success"):
            raise HTTPException(status_code=400, detail=local_res.get("error", "PDF 解析失敗"))

        due_date_str = local_res.get("due_date").strftime("%Y-%m-%d") if local_res.get("due_date") else None
        statement_date_str = local_res.get("statement_date").strftime("%Y-%m-%d") if local_res.get("statement_date") else None

        warn_msg = " (提醒：金額為 0 元，建議在預覽框核對並手動修正)" if local_res.get("needs_review") else ""

        return DocumentParseResponse(
            success=True,
            document_type="CREDIT_CARD_BILL",
            bank_or_company=local_res.get("bank_name", "星展銀行"),
            statement_month=local_res.get("statement_month"),
            total_amount=local_res.get("total_amount", 0.0),
            minimum_amount=local_res.get("minimum_amount", 0.0),
            due_date=due_date_str,
            statement_date=statement_date_str,
            confidence_summary="使用本地正規表達式解析" + warn_msg,
            raw_snippet=local_res.get("raw_snippet")
        )

    raise HTTPException(
        status_code=400,
        detail="圖片辨識或非星展銀行單據需要 GEMINI_API_KEY，請至右上角【設定】填入免費的 Gemini API Key"
    )

# ================= 薪資套用 API =================
@app.post("/api/salary/apply")
def apply_salary(req: SalaryApplyRequest, db: Session = Depends(get_db)):
    """當辨識為薪資單時，更新每月月薪設定，並可選自動記錄一筆薪資入帳"""
    _save_setting(db, "MONTHLY_SALARY", str(req.salary_amount))

    tx_id = None
    if req.record_transaction and req.account_id:
        acc = db.query(Account).filter(Account.id == req.account_id).first()
        if acc:
            acc.balance += req.salary_amount
            tx = Transaction(
                date=datetime.utcnow(),
                amount=req.salary_amount,
                tx_type="INCOME",
                account_id=acc.id,
                category="薪資收入",
                description=f"{req.company_name or '公司'} {req.statement_month or ''} 薪資入帳"
            )
            db.add(tx)
            db.flush()
            tx_id = tx.id

    db.commit()
    return {
        "status": "success",
        "message": f"每月月薪已更新為 NT$ {req.salary_amount:,.0f}" + ("，並已記錄入帳" if tx_id else "")
    }

# ================= Gmail 同步與手動上傳 =================
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

# ================= 系統與 Google OAuth / Gemini API 設定 =================
@app.get("/api/settings", response_model=SettingsStatus)
def get_settings_status(db: Session = Depends(get_db)):
    gmail_service = GmailService(db)
    has_pwd = bool(db.query(SystemSetting).filter(SystemSetting.key == "DBS_PDF_PASSWORD", SystemSetting.value != "").first())
    has_client_id = bool(db.query(SystemSetting).filter(SystemSetting.key == "GOOGLE_CLIENT_ID", SystemSetting.value != "").first()) or bool(os.getenv("GOOGLE_CLIENT_ID"))
    has_gemini = bool(db.query(SystemSetting).filter(SystemSetting.key == "GEMINI_API_KEY", SystemSetting.value != "").first()) or bool(os.getenv("GEMINI_API_KEY"))
    default_acc = db.query(Account).filter(Account.is_dbs_default_debit == True).first()
    salary_setting = db.query(SystemSetting).filter(SystemSetting.key == "MONTHLY_SALARY").first()
    salary = float(salary_setting.value) if salary_setting and salary_setting.value else 50000.0

    return SettingsStatus(
        is_google_connected=gmail_service.is_connected(),
        has_pdf_password=has_pwd,
        google_client_id_configured=has_client_id,
        has_gemini_api_key=has_gemini,
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
    if settings.gemini_api_key is not None:
        _save_setting(db, "GEMINI_API_KEY", settings.gemini_api_key)
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
        return RedirectResponse(url="/?auth=success")
    except Exception as e:
        return {"status": "error", "message": str(e)}

from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, Bill, Account, Transaction
from ..schemas import (
    BillCreate,
    BillUpdate,
    BillResponse,
    DocumentParseResponse,
    SalaryApplyRequest,
    BatchSaveRequest,
    BatchSaveResponse,
    BatchSaveResultItem
)
from ..services.accounting_service import (
    get_setting,
    get_default_debit_account,
    execute_bill_payment,
    apply_salary_income
)
from ..services.auth_service import get_current_user
from ..services.integrations.ai_parser import parse_document_with_gemini
from ..services.integrations.dbs_parser import parse_dbs_pdf
from ..services.scheduler import sync_bills_from_gmail, execute_auto_debits

router = APIRouter(tags=["Bills & Sync"])


@router.get("/api/bills", response_model=List[BillResponse])
def get_bills(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    return db.query(Bill).filter(
        Bill.user_id == current_user.id
    ).order_by(Bill.due_date.desc()).all()


@router.post("/api/bills", response_model=BillResponse)
def create_bill(
    bill_in: BillCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    bill = Bill(**bill_in.dict(), user_id=current_user.id)
    if not bill.debit_account_id:
        default_acc = get_default_debit_account(db, user_id=current_user.id)
        if default_acc:
            bill.debit_account_id = default_acc.id

    db.add(bill)
    db.commit()
    db.refresh(bill)
    return bill


@router.put("/api/bills/{bill_id}", response_model=BillResponse)
def update_bill(
    bill_id: int,
    bill_in: BillUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    bill = db.query(Bill).filter(
        Bill.id == bill_id,
        Bill.user_id == current_user.id
    ).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到該帳單")

    update_data = bill_in.dict(exclude_unset=True)
    for field, val in update_data.items():
        setattr(bill, field, val)

    db.commit()
    db.refresh(bill)
    return bill


@router.delete("/api/bills/{bill_id}")
def delete_bill(
    bill_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    bill = db.query(Bill).filter(
        Bill.id == bill_id,
        Bill.user_id == current_user.id
    ).first()
    if not bill:
        raise HTTPException(status_code=404, detail="找不到該帳單")
    db.delete(bill)
    db.commit()
    return {"status": "success", "message": "帳單已刪除"}


@router.post("/api/bills/{bill_id}/pay")
def manual_pay_bill(
    bill_id: int,
    account_id: Optional[int] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手動立即為特定帳單執行扣款"""
    bill = db.query(Bill).filter(
        Bill.id == bill_id,
        Bill.user_id == current_user.id
    ).first()
    if not bill:
        raise HTTPException(status_code=404, detail="帳單不存在")
    if bill.status == "PAID":
        raise HTTPException(status_code=400, detail="該帳單已完成扣款")

    acc = execute_bill_payment(db, bill, account_id=account_id, is_auto=False, user_id=current_user.id)
    return {"status": "success", "message": f"已從【{acc.name}】扣除 NT$ {bill.total_amount:,.0f}"}


@router.post("/api/ai/parse-document", response_model=DocumentParseResponse)
async def parse_document(
    file: UploadFile = File(...),
    password: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """接收 PDF 或圖片，使用該使用者專屬的 Gemini API Key 自動辨識信用卡帳單或薪資單"""
    file_bytes = await file.read()
    # 嚴格使用當前登入使用者自己的 Gemini API Key (不與他人共用)
    gemini_key = get_setting(db, "GEMINI_API_KEY", "", user_id=current_user.id).strip()

    pwd_candidates = []
    if password and password.strip():
        pwd_candidates.append(password.strip())

    id_card_pwd = get_setting(db, "ID_CARD_PASSWORD", "", user_id=current_user.id)
    if id_card_pwd:
        pwd_candidates.append(id_card_pwd.strip())

    dbs_pwd = get_setting(db, "DBS_PDF_PASSWORD", "", user_id=current_user.id)
    if dbs_pwd:
        pwd_candidates.append(dbs_pwd.strip())

    if gemini_key:
        res = parse_document_with_gemini(
            file_bytes=file_bytes,
            filename=file.filename,
            api_key=gemini_key,
            password=pwd_candidates
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
                raw_snippet=res.get("raw_snippet"),
                currency=res.get("currency", "TWD"),
                original_amount=res.get("original_amount"),
                exchange_rate=res.get("exchange_rate", 1.0)
            )
        else:
            print(f"[AI Parser] Gemini 辨識失敗 (user={current_user.id}): {res.get('error')}，嘗試本地解析")

    if file.filename.lower().endswith(".pdf"):
        fallback_pwd = password or dbs_pwd or id_card_pwd
        if not fallback_pwd:
            raise HTTPException(status_code=400, detail="本地 PDF 解析需要解密密碼，或請至【設定】填寫您個人的 Gemini API Key 啟用 AI 辨識")

        local_res = parse_dbs_pdf(file_bytes, fallback_pwd)
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
        detail="圖片辨識或非星展銀行單據需要您個人的 GEMINI_API_KEY，請至右上角【設定】填入免費的 Gemini API Key"
    )


@router.post("/api/salary/apply")
def apply_salary(
    req: SalaryApplyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """當辨識為薪資單時，更新每月月薪設定，並可選自動記錄一筆薪資入帳"""
    tx_id = apply_salary_income(db, req, user_id=current_user.id)
    return {
        "status": "success",
        "message": f"每月月薪已更新為 NT$ {req.salary_amount:,.0f}" + ("，並已記錄入帳" if tx_id else "")
    }


@router.post("/api/sync/gmail")
def trigger_gmail_sync(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手動點擊觸發信箱 (IMAP 應用程式密碼 / Gmail) 帳單抓取"""
    return sync_bills_from_gmail(db, user_id=current_user.id)


@router.post("/api/sync/auto-debit")
def trigger_auto_debit(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手動觸發到期帳單扣款檢驗"""
    return execute_auto_debits(db, user_id=current_user.id)


@router.post("/api/ai/batch-save", response_model=BatchSaveResponse)
def batch_save_documents(
    req: BatchSaveRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """批次儲存經 AI 辨識確認的多筆單據（日常發票記帳、信用卡帳單、薪資單）"""
    results = []
    saved_count = 0
    failed_count = 0
    default_acc = get_default_debit_account(db, user_id=current_user.id)
    first_acc = db.query(Account).filter(Account.user_id == current_user.id).first()

    for item in req.items:
        try:
            doc_type = (item.document_type or "EXPENSE_RECEIPT").upper()
            target_acc_id = item.account_id or (default_acc.id if default_acc else (first_acc.id if first_acc else None))
            
            # 處理日期字串
            parsed_date = None
            if item.date:
                try:
                    parsed_date = datetime.strptime(item.date[:10], "%Y-%m-%d")
                except Exception:
                    parsed_date = datetime.utcnow()
            else:
                parsed_date = datetime.utcnow()

            if doc_type == "CREDIT_CARD_BILL":
                due_d = parsed_date.date()
                bill = Bill(
                    user_id=current_user.id,
                    bank_name=item.bank_or_company or "信用卡",
                    statement_month=item.statement_month,
                    due_date=due_d,
                    statement_date=due_d,
                    total_amount=float(item.total_amount),
                    minimum_amount=float(item.minimum_amount or 0.0),
                    status="PENDING",
                    debit_account_id=target_acc_id
                )
                db.add(bill)
                db.commit()
                db.refresh(bill)
                saved_count += 1
                results.append(BatchSaveResultItem(
                    success=True,
                    message=f"已成功建立 {bill.bank_name} 待繳帳單",
                    document_type=doc_type,
                    amount=bill.total_amount,
                    description=item.description or bill.bank_name
                ))

            elif doc_type == "SALARY_SLIP":
                salary_req = SalaryApplyRequest(
                    salary_amount=float(item.total_amount),
                    statement_month=item.statement_month,
                    company_name=item.bank_or_company,
                    record_transaction=True,
                    account_id=target_acc_id
                )
                tx_id = apply_salary_income(db, salary_req, user_id=current_user.id)
                saved_count += 1
                results.append(BatchSaveResultItem(
                    success=True,
                    message=f"已更新月薪 NT$ {item.total_amount:,.0f} 並記錄薪資入帳",
                    document_type=doc_type,
                    amount=item.total_amount,
                    description=item.description or f"{item.bank_or_company or '公司'} 薪資"
                ))

            else:
                # 預設為日常消費發票/收據 (EXPENSE_RECEIPT)
                if not target_acc_id:
                    raise Exception("找不到可扣款的資產帳戶，請先至【帳戶管理】建立帳戶")

                acc = db.query(Account).filter(Account.id == target_acc_id, Account.user_id == current_user.id).first()
                if not acc:
                    raise Exception(f"扣款帳戶不存在 (ID: {target_acc_id})")

                acc.balance -= float(item.total_amount)
                desc = item.description or f"{item.bank_or_company or '消費'} 支出"
                if item.currency and item.currency != "TWD" and item.original_amount:
                    desc += f" (原幣 {item.currency} {item.original_amount:,.2f})"

                tx = Transaction(
                    user_id=current_user.id,
                    date=parsed_date,
                    amount=float(item.total_amount),
                    tx_type="EXPENSE",
                    account_id=acc.id,
                    category=item.category or "其他",
                    description=desc
                )
                db.add(tx)
                db.commit()
                db.refresh(tx)
                saved_count += 1
                results.append(BatchSaveResultItem(
                    success=True,
                    message=f"已成功記錄支出 NT$ {item.total_amount:,.0f}（自 {acc.name} 扣除）",
                    document_type=doc_type,
                    amount=item.total_amount,
                    description=desc
                ))

        except Exception as err:
            db.rollback()
            failed_count += 1
            results.append(BatchSaveResultItem(
                success=False,
                message=f"儲存失敗: {str(err)}",
                document_type=item.document_type or "UNKNOWN",
                amount=item.total_amount,
                description=item.description or item.bank_or_company
            ))

    return BatchSaveResponse(
        total=len(req.items),
        saved_count=saved_count,
        failed_count=failed_count,
        results=results
    )

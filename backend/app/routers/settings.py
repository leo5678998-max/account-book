import json
from typing import Optional, List
from pydantic import BaseModel
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, Account
from ..schemas import SettingsUpdate, SettingsStatus
from ..services.accounting_service import (
    get_setting,
    save_setting,
    get_default_debit_account,
    execute_auto_salary_credits
)
from ..services.webhook_service import get_or_create_webhook_token
from ..services.auth_service import get_current_user
from ..services.integrations.gmail_service import GmailService
from ..services.integrations.imap_service import ImapService
from ..services.insurance_service import calculate_insurance_summary

router = APIRouter(tags=["Settings & Email Sync"])

DEFAULT_EXPENSE_CATEGORIES = [
    "飲食", "房租水電", "交通", "日常採買", "娛樂休閒", "保險醫療", "信用卡費", "薪資收入", "其他"
]


class CategoriesUpdateRequest(BaseModel):
    categories: List[str]


@router.get("/api/categories")
def get_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """讀取使用者的自訂常用支出分類清單"""
    val = get_setting(db, "EXPENSE_CATEGORIES", "", user_id=current_user.id)
    if val:
        try:
            cats = json.loads(val)
            if isinstance(cats, list) and len(cats) > 0:
                return {"categories": cats}
        except Exception:
            pass
    return {"categories": list(DEFAULT_EXPENSE_CATEGORIES)}


@router.post("/api/categories")
def update_categories(
    req: CategoriesUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新使用者的常用支出分類清單"""
    cleaned = []
    seen = set()
    for c in req.categories:
        if not isinstance(c, str):
            continue
        c_str = c.strip()
        if c_str and c_str not in seen:
            seen.add(c_str)
            cleaned.append(c_str)
    if not cleaned:
        cleaned = list(DEFAULT_EXPENSE_CATEGORIES)
    save_setting(db, "EXPENSE_CATEGORIES", json.dumps(cleaned, ensure_ascii=False), user_id=current_user.id)
    db.commit()
    return {"status": "success", "categories": cleaned}


@router.post("/api/categories/reset")
def reset_categories(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """重設回系統預設支出分類清單"""
    save_setting(db, "EXPENSE_CATEGORIES", json.dumps(DEFAULT_EXPENSE_CATEGORIES, ensure_ascii=False), user_id=current_user.id)
    db.commit()
    return {"status": "success", "categories": list(DEFAULT_EXPENSE_CATEGORIES)}


class CategoryColorsUpdateRequest(BaseModel):
    colors: dict


@router.get("/api/category-colors")
def get_category_colors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """讀取使用者的自訂分類色彩對應表"""
    val = get_setting(db, "CATEGORY_CUSTOM_COLORS", "", user_id=current_user.id)
    if val:
        try:
            colors = json.loads(val)
            if isinstance(colors, dict):
                return {"colors": colors}
        except Exception:
            pass
    return {"colors": {}}


@router.post("/api/category-colors")
def update_category_colors(
    req: CategoryColorsUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """更新使用者的自訂分類色彩對應表"""
    cleaned = {}
    if isinstance(req.colors, dict):
        for k, v in req.colors.items():
            if isinstance(k, str) and isinstance(v, str):
                k_clean = k.strip()
                v_clean = v.strip()
                if k_clean and v_clean.startswith("#") and len(v_clean) in (4, 7, 9):
                    cleaned[k_clean] = v_clean
    save_setting(db, "CATEGORY_CUSTOM_COLORS", json.dumps(cleaned, ensure_ascii=False), user_id=current_user.id)
    db.commit()
    return {"status": "success", "colors": cleaned}


@router.post("/api/category-colors/reset")
def reset_category_colors(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """重設回系統預設分類色彩"""
    save_setting(db, "CATEGORY_CUSTOM_COLORS", "{}", user_id=current_user.id)
    db.commit()
    return {"status": "success", "colors": {}}


class ImapTestRequest(BaseModel):
    imap_email: Optional[str] = None
    imap_app_password: Optional[str] = None
    imap_server: Optional[str] = None


@router.get("/api/settings", response_model=SettingsStatus)
def get_settings_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    uid = current_user.id
    gmail_service = GmailService(db, user_id=uid)
    imap_service = ImapService(db, user_id=uid)

    pwd_val = get_setting(db, "DBS_PDF_PASSWORD", "", user_id=uid)
    id_card_val = get_setting(db, "ID_CARD_PASSWORD", "", user_id=uid)
    cid_val = get_setting(db, "GOOGLE_CLIENT_ID", "", user_id=uid)
    uri_val = get_setting(db, "GOOGLE_REDIRECT_URI", "http://localhost:8000/api/auth/google/callback", user_id=uid)
    # 嚴格獨立：每位使用者只讀取自己的 Gemini API Key，絕不與其他使用者共用
    gemini_val = get_setting(db, "GEMINI_API_KEY", "", user_id=uid)

    imap_email_val = get_setting(db, "IMAP_EMAIL", "", user_id=uid)
    imap_pwd_val = get_setting(db, "IMAP_APP_PASSWORD", "", user_id=uid)
    imap_server_val = get_setting(db, "IMAP_SERVER", "imap.gmail.com", user_id=uid) or "imap.gmail.com"

    default_acc = get_default_debit_account(db, user_id=uid)
    salary_str = get_setting(db, "MONTHLY_SALARY", "", user_id=uid)
    salary = float(salary_str) if salary_str else 50000.0

    deduct_labor_health_str = get_setting(db, "DEDUCT_LABOR_HEALTH", "false", user_id=uid)
    deduct_labor_health = deduct_labor_health_str.lower() in ("true", "1")

    dependents_str = get_setting(db, "HEALTH_INSURANCE_DEPENDENTS", "1", user_id=uid)
    dependents = int(dependents_str) if dependents_str and dependents_str.isdigit() else 1

    auto_calc_str = get_setting(db, "LABOR_HEALTH_AUTO_CALC", "true", user_id=uid)
    auto_calc = auto_calc_str.lower() in ("true", "1")

    pension_rate_str = get_setting(db, "PENSION_RATE", "0.0", user_id=uid)
    try:
        pension_rate = float(pension_rate_str)
    except (ValueError, TypeError):
        pension_rate = 0.0

    tax_rate_str = get_setting(db, "TAX_RATE", "0.0", user_id=uid)
    try:
        tax_rate = float(tax_rate_str)
    except (ValueError, TypeError):
        tax_rate = 0.0

    show_chart_str = get_setting(db, "SHOW_DEDUCTIONS_IN_CHART", "true", user_id=uid)
    show_deductions_in_chart = show_chart_str.lower() in ("true", "1")

    labor_fee_str = get_setting(db, "LABOR_INSURANCE_FEE", "", user_id=uid) or None
    health_fee_str = get_setting(db, "HEALTH_INSURANCE_FEE", "", user_id=uid) or None
    pension_fee_str = get_setting(db, "PENSION_FEE", "", user_id=uid) or None
    tax_fee_str = get_setting(db, "TAX_FEE", "", user_id=uid) or None

    if auto_calc or labor_fee_str is None or health_fee_str is None or pension_fee_str is None or tax_fee_str is None:
        calc = calculate_insurance_summary(salary, dependents, pension_rate, tax_rate)
        labor_fee = float(calc["labor_insurance"]["fee"])
        health_fee = float(calc["health_insurance"]["fee"])
        pension_fee = float(calc["labor_pension"]["fee"])
        tax_fee = float(calc["income_tax"]["fee"])
    else:
        labor_fee = float(labor_fee_str)
        health_fee = float(health_fee_str)
        pension_fee = float(pension_fee_str)
        tax_fee = float(tax_fee_str)

    if deduct_labor_health:
        net_salary = max(0.0, salary - labor_fee - health_fee - pension_fee - tax_fee)
    else:
        net_salary = salary

    is_imap_ok = imap_service.is_configured()
    is_gmail_ok = gmail_service.is_connected()

    auto_debit_bills_val = get_setting(db, "AUTO_DEBIT_BILLS", "false", user_id=uid).lower() in ("true", "1")

    salary_acc_id_str = get_setting(db, "SALARY_ACCOUNT_ID", "", user_id=uid)
    salary_acc_id = int(salary_acc_id_str) if salary_acc_id_str and salary_acc_id_str.isdigit() else None
    salary_acc = None
    if salary_acc_id:
        salary_acc = db.query(Account).filter(Account.id == salary_acc_id, Account.user_id == uid).first()
    if not salary_acc and default_acc:
        salary_acc = default_acc
        salary_acc_id = default_acc.id

    pay_day_str = get_setting(db, "SALARY_PAY_DAY", "5", user_id=uid)
    pay_day = int(pay_day_str) if pay_day_str and pay_day_str.isdigit() else 5

    auto_salary_income_val = get_setting(db, "AUTO_SALARY_INCOME_ENABLED", "false", user_id=uid).lower() in ("true", "1")
    bookkeeping_start_month_val = get_setting(db, "BOOKKEEPING_START_MONTH", "2026-11", user_id=uid)

    webhook_tok = get_or_create_webhook_token(db, uid)
    webhook_path = f"/api/webhook/apple-pay?token={webhook_tok}"

    return SettingsStatus(
        is_google_connected=(is_imap_ok or is_gmail_ok),
        is_imap_configured=is_imap_ok,
        has_pdf_password=bool(pwd_val or id_card_val),
        google_client_id_configured=bool(cid_val),
        has_gemini_api_key=bool(gemini_val),
        default_debit_account_name=default_acc.name if default_acc else None,
        auto_debit_bills=auto_debit_bills_val,
        salary_account_id=salary_acc_id,
        salary_account_name=salary_acc.name if salary_acc else None,
        salary_pay_day=pay_day,
        auto_salary_income=auto_salary_income_val,
        monthly_salary=salary,
        deduct_labor_health=deduct_labor_health,
        health_insurance_dependents=dependents,
        labor_insurance_fee=labor_fee,
        health_insurance_fee=health_fee,
        pension_rate=pension_rate,
        pension_fee=pension_fee,
        tax_rate=tax_rate,
        tax_fee=tax_fee,
        show_deductions_in_chart=show_deductions_in_chart,
        labor_health_auto_calc=auto_calc,
        net_salary=net_salary,
        gemini_api_key=gemini_val,
        dbs_pdf_password=pwd_val,
        id_card_password=id_card_val,
        imap_email=imap_email_val,
        imap_app_password=imap_pwd_val,
        imap_server=imap_server_val,
        google_client_id=cid_val,
        google_redirect_uri=uri_val,
        webhook_token=webhook_tok,
        webhook_url=webhook_path,
        bookkeeping_start_month=bookkeeping_start_month_val
    )


@router.post("/api/settings")
def update_settings(
    settings: SettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    uid = current_user.id
    if settings.google_client_id is not None:
        save_setting(db, "GOOGLE_CLIENT_ID", settings.google_client_id.strip(), user_id=uid)
    if settings.google_client_secret is not None and settings.google_client_secret.strip() != "":
        save_setting(db, "GOOGLE_CLIENT_SECRET", settings.google_client_secret.strip(), user_id=uid)
    if settings.google_redirect_uri is not None and settings.google_redirect_uri.strip() != "":
        save_setting(db, "GOOGLE_REDIRECT_URI", settings.google_redirect_uri.strip(), user_id=uid)
    if settings.imap_email is not None:
        save_setting(db, "IMAP_EMAIL", settings.imap_email.strip(), user_id=uid)
    if settings.imap_app_password is not None:
        save_setting(db, "IMAP_APP_PASSWORD", settings.imap_app_password.strip(), user_id=uid)
    if settings.imap_server is not None:
        save_setting(db, "IMAP_SERVER", settings.imap_server.strip() or "imap.gmail.com", user_id=uid)
    if settings.id_card_password is not None:
        save_setting(db, "ID_CARD_PASSWORD", settings.id_card_password.strip(), user_id=uid)
    if settings.dbs_pdf_password is not None:
        save_setting(db, "DBS_PDF_PASSWORD", settings.dbs_pdf_password.strip(), user_id=uid)
    if settings.gemini_api_key is not None:
        save_setting(db, "GEMINI_API_KEY", settings.gemini_api_key.strip(), user_id=uid)
    if settings.monthly_salary is not None:
        save_setting(db, "MONTHLY_SALARY", str(settings.monthly_salary), user_id=uid)
    if settings.deduct_labor_health is not None:
        save_setting(db, "DEDUCT_LABOR_HEALTH", "true" if settings.deduct_labor_health else "false", user_id=uid)
    if settings.health_insurance_dependents is not None:
        save_setting(db, "HEALTH_INSURANCE_DEPENDENTS", str(max(1, settings.health_insurance_dependents)), user_id=uid)
    if settings.labor_health_auto_calc is not None:
        save_setting(db, "LABOR_HEALTH_AUTO_CALC", "true" if settings.labor_health_auto_calc else "false", user_id=uid)
    if settings.labor_insurance_fee is not None:
        save_setting(db, "LABOR_INSURANCE_FEE", str(settings.labor_insurance_fee), user_id=uid)
    if settings.health_insurance_fee is not None:
        save_setting(db, "HEALTH_INSURANCE_FEE", str(settings.health_insurance_fee), user_id=uid)
    if settings.pension_rate is not None:
        save_setting(db, "PENSION_RATE", str(max(0.0, min(0.06, settings.pension_rate))), user_id=uid)
    if settings.pension_fee is not None:
        save_setting(db, "PENSION_FEE", str(settings.pension_fee), user_id=uid)
    if settings.tax_rate is not None:
        save_setting(db, "TAX_RATE", str(max(0.0, min(0.30, settings.tax_rate))), user_id=uid)
    if settings.tax_fee is not None:
        save_setting(db, "TAX_FEE", str(settings.tax_fee), user_id=uid)
    if settings.show_deductions_in_chart is not None:
        save_setting(db, "SHOW_DEDUCTIONS_IN_CHART", "true" if settings.show_deductions_in_chart else "false", user_id=uid)
    if settings.auto_debit_bills is not None:
        save_setting(db, "AUTO_DEBIT_BILLS", "true" if settings.auto_debit_bills else "false", user_id=uid)
    if settings.salary_account_id is not None:
        save_setting(db, "SALARY_ACCOUNT_ID", str(settings.salary_account_id), user_id=uid)
    if settings.salary_pay_day is not None:
        save_setting(db, "SALARY_PAY_DAY", str(max(1, min(31, settings.salary_pay_day))), user_id=uid)
    if settings.auto_salary_income is not None:
        save_setting(db, "AUTO_SALARY_INCOME_ENABLED", "true" if settings.auto_salary_income else "false", user_id=uid)
    if settings.bookkeeping_start_month is not None:
        save_setting(db, "BOOKKEEPING_START_MONTH", settings.bookkeeping_start_month.strip(), user_id=uid)
    if settings.default_debit_account_id is not None:
        db.query(Account).filter(Account.user_id == uid).update({Account.is_dbs_default_debit: False})
        db.query(Account).filter(
            Account.id == settings.default_debit_account_id,
            Account.user_id == uid
        ).update({Account.is_dbs_default_debit: True})

    db.commit()

    # 若開啟每月自動薪資入帳，立即檢查本月是否已符合發薪日並入帳
    if settings.auto_salary_income:
        execute_auto_salary_credits(db, user_id=uid)

    return {"status": "success", "message": "設定已更新"}


@router.post("/api/salary/trigger-credit")
def trigger_salary_credit_now(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手動觸發立即為本月入帳薪資流水帳"""
    return execute_auto_salary_credits(db, user_id=current_user.id)


@router.post("/api/settings/test-imap")
def test_imap_connection(
    req: ImapTestRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """測試 IMAP 信箱與 16 碼應用程式密碼連線"""
    imap = ImapService(db, user_id=current_user.id)
    res = imap.test_connection(
        email_addr=req.imap_email,
        app_pwd=req.imap_app_password,
        server=req.imap_server
    )
    if not res.get("success"):
        raise HTTPException(status_code=400, detail=res.get("message", "IMAP 連線測試失敗"))
    return res


@router.get("/api/settings/calculate-insurance")
def calculate_insurance(salary: float = 50000.0, dependents: int = 1, pension_rate: float = 0.0, tax_rate: float = 0.0):
    return calculate_insurance_summary(salary, dependents, pension_rate, tax_rate)


@router.get("/api/auth/google/url")
def get_google_auth_url(
    redirect_uri: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    gmail = GmailService(db, user_id=current_user.id)
    try:
        url = gmail.get_auth_url(redirect_uri=redirect_uri)
        return {"auth_url": url}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/api/auth/google/callback")
def google_auth_callback(code: str, state: Optional[str] = None, db: Session = Depends(get_db)):
    gmail = GmailService(db, user_id=1)
    try:
        gmail.handle_auth_callback(code=code)
        return RedirectResponse(url="/?auth=success")
    except Exception as e:
        return {"status": "error", "message": str(e)}

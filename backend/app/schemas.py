from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime, date


# ================= 使用者註冊與登入 Schema =================
class UserRegister(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

class UserProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    current_password: Optional[str] = None
    new_password: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse

class AccountBase(BaseModel):
    name: str
    account_type: str = "SAVINGS" # SAVINGS, CREDIT, CASH, INVESTMENT
    balance: float = 0.0
    currency: str = "TWD"
    account_number: Optional[str] = None
    is_dbs_default_debit: bool = False

class AccountCreate(AccountBase):
    pass

class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_type: Optional[str] = None
    balance: Optional[float] = None
    account_number: Optional[str] = None
    is_dbs_default_debit: Optional[bool] = None

class AccountResponse(AccountBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class TransactionCreate(BaseModel):
    amount: float
    tx_type: str = "EXPENSE" # EXPENSE, INCOME, TRANSFER, REFUND
    account_id: int
    target_account_id: Optional[int] = None
    category: str = "其他"
    description: Optional[str] = None
    date: Optional[datetime] = None
    affects_balance: bool = True
    related_transaction_id: Optional[int] = None
    is_reconciled: Optional[bool] = False

class TransactionUpdate(TransactionCreate):
    pass

class TransactionResponse(BaseModel):
    id: int
    amount: float
    tx_type: str
    account_id: int
    target_account_id: Optional[int] = None
    category: str
    description: Optional[str] = None
    date: datetime
    bill_id: Optional[int] = None
    related_transaction_id: Optional[int] = None
    affects_balance: bool = True
    is_reconciled: bool = False
    reconciled_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class BillCreate(BaseModel):
    bank_name: str
    statement_month: Optional[str] = None
    statement_date: Optional[date] = None
    statement_start_date: Optional[date] = None
    due_date: date
    total_amount: float
    minimum_amount: float = 0.0
    status: str = "PENDING"
    pdf_filename: Optional[str] = None
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None

class BillUpdate(BaseModel):
    bank_name: Optional[str] = None
    statement_month: Optional[str] = None
    statement_date: Optional[date] = None
    statement_start_date: Optional[date] = None
    due_date: Optional[date] = None
    total_amount: Optional[float] = None
    minimum_amount: Optional[float] = None
    status: Optional[str] = None
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None

class BillResponse(BaseModel):
    id: int
    bank_name: str
    statement_month: Optional[str] = None
    statement_date: Optional[date] = None
    statement_start_date: Optional[date] = None
    due_date: date
    total_amount: float
    minimum_amount: float
    status: str
    email_message_id: Optional[str] = None
    pdf_filename: Optional[str] = None
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None
    paid_date: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class ReconciliationItem(BaseModel):
    id: int
    date: datetime
    amount: float
    tx_type: str
    category: str
    description: Optional[str] = None
    account_id: int
    account_name: Optional[str] = None
    is_reconciled: bool = False
    reconciled_at: Optional[datetime] = None
    bill_id: Optional[int] = None

class ReconciliationOverview(BaseModel):
    bill_id: int
    bank_name: str
    statement_month: Optional[str] = None
    statement_date: Optional[date] = None
    statement_start_date: Optional[date] = None
    statement_end_date: Optional[date] = None
    due_date: date
    bill_total_amount: float
    bill_status: str
    debit_account_id: Optional[int] = None
    credit_account_id: Optional[int] = None
    credit_account_name: Optional[str] = None

    matched_count: int
    reconciled_count: int
    unreconciled_count: int
    reconciled_amount: float
    difference: float
    is_balanced: bool

    transactions: List[ReconciliationItem]

class ReconciliationCheckRequest(BaseModel):
    transaction_ids: List[int]
    is_reconciled: bool = True

class ReconciliationClearRequest(BaseModel):
    debit_account_id: int
    credit_account_id: Optional[int] = None
    reconciled_transaction_ids: List[int] = []
    settlement_mode: str = "TRANSFER" # "TRANSFER" (清償卡債) or "EXPENSE" (信用卡費支出)
    note: Optional[str] = None

class ReconciliationQuickAddRequest(BaseModel):
    date: Optional[datetime] = None
    amount: float
    category: str = "其他"
    description: str
    tx_type: str = "EXPENSE"
    credit_account_id: Optional[int] = None

class DocumentParseResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    document_type: str = "UNKNOWN" # CREDIT_CARD_BILL, SALARY_SLIP, EXPENSE_RECEIPT, UNKNOWN
    bank_or_company: Optional[str] = None
    statement_month: Optional[str] = None
    total_amount: float = 0.0
    minimum_amount: float = 0.0
    due_date: Optional[str] = None
    statement_date: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    confidence_summary: Optional[str] = None
    raw_snippet: Optional[str] = None
    currency: Optional[str] = "TWD"
    original_amount: Optional[float] = None
    exchange_rate: Optional[float] = 1.0

class BatchApplyItem(BaseModel):
    document_type: str = "EXPENSE_RECEIPT" # EXPENSE_RECEIPT, CREDIT_CARD_BILL, SALARY_SLIP
    bank_or_company: Optional[str] = None
    statement_month: Optional[str] = None
    date: Optional[str] = None # YYYY-MM-DD
    category: Optional[str] = "其他"
    description: Optional[str] = None
    total_amount: float = 0.0
    original_amount: Optional[float] = None
    currency: Optional[str] = "TWD"
    exchange_rate: Optional[float] = 1.0
    account_id: Optional[int] = None
    minimum_amount: Optional[float] = 0.0
    notes: Optional[str] = None

class BatchSaveRequest(BaseModel):
    items: List[BatchApplyItem]

class BatchSaveResultItem(BaseModel):
    success: bool
    message: str
    document_type: str
    amount: float
    description: Optional[str] = None

class BatchSaveResponse(BaseModel):
    total: int
    saved_count: int
    failed_count: int
    results: List[BatchSaveResultItem]

class SalaryApplyRequest(BaseModel):
    salary_amount: float
    statement_month: Optional[str] = None
    company_name: Optional[str] = None
    record_transaction: bool = True
    account_id: Optional[int] = None

class SettingsUpdate(BaseModel):
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: Optional[str] = None
    imap_email: Optional[str] = None
    imap_app_password: Optional[str] = None
    imap_server: Optional[str] = None
    dbs_pdf_password: Optional[str] = None
    id_card_password: Optional[str] = None
    gemini_api_key: Optional[str] = None
    default_debit_account_id: Optional[int] = None
    monthly_salary: Optional[float] = None
    deduct_labor_health: Optional[bool] = None
    health_insurance_dependents: Optional[int] = None
    labor_insurance_fee: Optional[float] = None
    health_insurance_fee: Optional[float] = None
    pension_rate: Optional[float] = None
    pension_fee: Optional[float] = None
    tax_rate: Optional[float] = None
    tax_fee: Optional[float] = None
    show_deductions_in_chart: Optional[bool] = None
    labor_health_auto_calc: Optional[bool] = None

class SettingsStatus(BaseModel):
    is_google_connected: bool
    is_imap_configured: bool = False
    has_pdf_password: bool
    google_client_id_configured: bool
    has_gemini_api_key: bool
    default_debit_account_name: Optional[str] = None
    monthly_salary: float = 50000.0
    deduct_labor_health: bool = False
    health_insurance_dependents: int = 1
    labor_insurance_fee: float = 0.0
    health_insurance_fee: float = 0.0
    pension_rate: float = 0.0
    pension_fee: float = 0.0
    tax_rate: float = 0.0
    tax_fee: float = 0.0
    show_deductions_in_chart: bool = True
    labor_health_auto_calc: bool = True
    net_salary: float = 50000.0
    gemini_api_key: Optional[str] = ""
    dbs_pdf_password: Optional[str] = ""
    id_card_password: Optional[str] = ""
    imap_email: Optional[str] = ""
    imap_app_password: Optional[str] = ""
    imap_server: Optional[str] = "imap.gmail.com"
    google_client_id: Optional[str] = ""
    google_redirect_uri: Optional[str] = ""
    webhook_token: Optional[str] = ""
    webhook_url: Optional[str] = ""


# ================= 股票持股相關 Schema =================
class StockHoldingBase(BaseModel):
    symbol: str
    name: Optional[str] = None
    shares: float
    cost_price: float
    currency: Optional[str] = None
    notes: Optional[str] = None

class StockHoldingCreate(StockHoldingBase):
    pass

class StockHoldingUpdate(BaseModel):
    symbol: Optional[str] = None
    name: Optional[str] = None
    shares: Optional[float] = None
    cost_price: Optional[float] = None
    currency: Optional[str] = None
    notes: Optional[str] = None

class StockHoldingResponse(StockHoldingBase):
    id: int
    current_price: float = 0.0
    total_cost: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: float = 0.0
    return_rate: float = 0.0
    market_value_twd: float = 0.0
    unrealized_pnl_twd: float = 0.0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class StockPortfolioSummary(BaseModel):
    total_market_value_twd: float = 0.0
    total_cost_twd: float = 0.0
    total_unrealized_pnl_twd: float = 0.0
    total_return_rate: float = 0.0
    usd_to_twd_rate: float = 32.0
    holdings: List[StockHoldingResponse] = []


# ================= 每月固定花費相關 Schema =================
class RecurringExpenseBase(BaseModel):
    name: str
    amount: float
    category: str = "其他"
    frequency: str = "MONTHLY" # "MONTHLY" (月繳) 或 "YEARLY" (年繳)
    due_month: Optional[int] = None # 1~12 (年繳時生效)
    due_day: Optional[int] = None # 1~31
    account_id: Optional[int] = None
    auto_debit: bool = False # 是否到達扣款日自動扣除帳戶存款
    is_active: bool = True
    notes: Optional[str] = None

class RecurringExpenseCreate(RecurringExpenseBase):
    pass

class RecurringExpenseUpdate(BaseModel):
    name: Optional[str] = None
    amount: Optional[float] = None
    category: Optional[str] = None
    frequency: Optional[str] = None
    due_month: Optional[int] = None
    due_day: Optional[int] = None
    account_id: Optional[int] = None
    auto_debit: Optional[bool] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None

class RecurringExpenseResponse(RecurringExpenseBase):
    id: int
    monthly_amortized_amount: float = 0.0 # 月平攤預備金
    is_due_this_month: bool = True       # 本月是否為應扣款月份
    last_charged_month: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class RecurringExpenseSummary(BaseModel):
    total_monthly_amount: float = 0.0     # 每月固定開銷總額 (含年繳月平攤)
    total_yearly_amount: float = 0.0      # 年繳項目年度總金額
    monthly_count: int = 0                # 月繳項目筆數
    yearly_count: int = 0                 # 年繳項目筆數
    items: List[RecurringExpenseResponse] = []


# ================= Webhook (Apple Pay / iOS 捷徑) Schema =================
class ApplePayWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="allow")
    amount: Optional[Any] = None  # 支援數值 (150)、帶幣別字串 ("NT$ 150") 或倒置容錯
    merchant: Optional[str] = None  # 商家名稱 (例如：全家、星巴克、高鐵)
    card_name: Optional[str] = None  # 信用卡/帳戶名稱 (例如：國泰世華 CUBE、台新、玉山)
    category: Optional[str] = None  # 分類 (可選，未填時系統依商家自動智能推導)
    note: Optional[str] = None  # 自訂備註
    date: Optional[str] = None  # 交易時間 (ISO 8601 或自訂日期格式)
    token: Optional[str] = None  # 可選：若不想放在 Query 或 Header，亦可置於 JSON body
    text: Optional[str] = None  # 推播通知或簡訊原始文字 (例如 "LINE Pay 付款成功 NT$85")
    app: Optional[str] = None  # 發送通知之應用程式名稱 (例如 "LINE Pay", "國泰世華 CUBE")
    title: Optional[str] = None  # 通知標題
    body: Optional[str] = None  # 通知內文

class ApplePayWebhookResponse(BaseModel):
    status: str = "success"
    message: str
    transaction_id: int
    amount: float
    category: str
    account_name: str
    account_balance: float

class WebhookTokenResponse(BaseModel):
    webhook_token: str
    webhook_url: str



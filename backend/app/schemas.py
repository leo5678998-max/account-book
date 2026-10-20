from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, date

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
    tx_type: str = "EXPENSE" # EXPENSE, INCOME, TRANSFER
    account_id: int
    target_account_id: Optional[int] = None
    category: str = "其他"
    description: Optional[str] = None
    date: Optional[datetime] = None

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

    class Config:
        from_attributes = True

class BillResponse(BaseModel):
    id: int
    bank_name: str
    statement_month: Optional[str] = None
    statement_date: Optional[date] = None
    due_date: date
    total_amount: float
    minimum_amount: float
    status: str
    email_message_id: Optional[str] = None
    pdf_filename: Optional[str] = None
    debit_account_id: Optional[int] = None
    paid_date: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True

class SettingsUpdate(BaseModel):
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    google_redirect_uri: Optional[str] = None
    dbs_pdf_password: Optional[str] = None
    default_debit_account_id: Optional[int] = None
    monthly_salary: Optional[float] = None

class SettingsStatus(BaseModel):
    is_google_connected: bool
    has_pdf_password: bool
    google_client_id_configured: bool
    default_debit_account_name: Optional[str] = None
    monthly_salary: float = 50000.0


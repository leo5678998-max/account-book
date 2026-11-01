from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .core.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    display_name = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    name = Column(String(100), nullable=False) # 例如：台新 Richart、玉山台幣活存、星展信用卡
    account_type = Column(String(50), default="SAVINGS") # SAVINGS, CREDIT, CASH, INVESTMENT
    balance = Column(Float, default=0.0) # 當前餘額
    currency = Column(String(10), default="TWD")
    account_number = Column(String(50), nullable=True) # 帳號後四碼或卡號後四碼
    is_dbs_default_debit = Column(Boolean, default=False) # 是否為星展信用卡指定扣款帳戶
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    transactions = relationship("Transaction", back_populates="account", foreign_keys="Transaction.account_id")
    bills_to_debit = relationship("Bill", back_populates="debit_account", foreign_keys="Bill.debit_account_id")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    date = Column(DateTime, default=datetime.utcnow)
    amount = Column(Float, nullable=False)
    tx_type = Column(String(20), nullable=False) # EXPENSE, INCOME, TRANSFER, REFUND
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    target_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True) # 轉帳目標帳戶
    category = Column(String(50), default="其他") # 餐飲, 交通, 信用卡費, 薪資...
    description = Column(String(255), nullable=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=True)
    related_transaction_id = Column(Integer, ForeignKey("transactions.id"), nullable=True) # 退款關聯原消費紀錄
    is_reconciled = Column(Boolean, default=False, nullable=False) # 月底帳單是否已對帳核對
    reconciled_at = Column(DateTime, nullable=True) # 對帳時間
    affects_balance = Column(Boolean, default=True, nullable=False)
    installment_plan_id = Column(Integer, ForeignKey("installment_plans.id"), nullable=True) # 分期付款計畫 ID
    installment_period = Column(Integer, nullable=True) # 當前為第幾期 (例如 3)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id], back_populates="transactions")
    target_account = relationship("Account", foreign_keys=[target_account_id])
    bill = relationship("Bill", foreign_keys=[bill_id])
    related_transaction = relationship("Transaction", remote_side=[id], foreign_keys=[related_transaction_id])
    installment_plan = relationship("InstallmentPlan", foreign_keys=[installment_plan_id], back_populates="transactions")

class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    bank_name = Column(String(100), default="星展銀行")
    statement_month = Column(String(20), nullable=True) # e.g. "2026-10"
    statement_date = Column(Date, nullable=True) # 結帳日
    statement_start_date = Column(Date, nullable=True) # 帳單週期起始日
    due_date = Column(Date, nullable=False) # 繳款截止日 / 自動扣款日
    total_amount = Column(Float, nullable=False) # 本期應繳總額
    minimum_amount = Column(Float, default=0.0) # 最低應繳金額
    status = Column(String(20), default="PENDING") # PENDING (待扣款), PAID (已扣款), SKIPPED (忽略)
    email_message_id = Column(String(255), unique=True, nullable=True) # Gmail/IMAP Message ID 防重複抓取
    pdf_filename = Column(String(255), nullable=True)
    debit_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    credit_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True) # 關聯信用卡帳戶
    paid_date = Column(DateTime, nullable=True)
    paid_transaction_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    debit_account = relationship("Account", foreign_keys=[debit_account_id], back_populates="bills_to_debit")
    credit_account = relationship("Account", foreign_keys=[credit_account_id])

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)



class StockHolding(Base):
    __tablename__ = "stock_holdings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    symbol = Column(String(50), nullable=False, index=True) # 例如：2330.TW, 0050.TW, NVDA
    name = Column(String(100), nullable=True) # 股票標的名稱，例如：台積電、元大台灣50、NVIDIA
    shares = Column(Float, nullable=False, default=0.0) # 持有股數 (支援零股如 100 股，或整張 1000 股)
    cost_price = Column(Float, nullable=False, default=0.0) # 買入每股均價成本
    current_price = Column(Float, nullable=True, default=0.0) # 最新現價
    currency = Column(String(10), default="TWD") # TWD 或 USD
    notes = Column(String(255), nullable=True) # 自訂備註
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RecurringExpense(Base):
    __tablename__ = "recurring_expenses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    name = Column(String(100), nullable=False) # 項目名稱，例如：房租、光世代網路、Netflix、保險
    amount = Column(Float, nullable=False, default=0.0) # 每期固定金額 (月繳為每月金額，年繳為整年金額)
    frequency = Column(String(20), default="MONTHLY") # 繳費週期: "MONTHLY" (月繳) 或 "YEARLY" (年繳)
    due_month = Column(Integer, nullable=True) # 若為年繳，指定扣款月份 (1~12)
    due_day = Column(Integer, nullable=True) # 預定繳款/扣款日 (1~31)
    category = Column(String(50), default="其他") # 居住, 電信網路, 娛樂, 交通, 保險, 醫療, 孝親, 其他
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True) # 預設扣款帳戶
    auto_debit = Column(Boolean, default=False, nullable=True) # 是否到達扣款日自動扣除帳戶存款
    is_active = Column(Boolean, default=True) # 是否啟用此固定花費
    notes = Column(String(255), nullable=True) # 備註
    last_charged_month = Column(String(20), nullable=True) # 最近一次扣款月份 (e.g. "2026-10") 防重複扣款
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id])


class InstallmentPlan(Base):
    __tablename__ = "installment_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    name = Column(String(100), nullable=False) # 例如：iPhone 16 Pro Max、長榮日本機票
    total_amount = Column(Float, nullable=False) # 總金額 (例如 36,000)
    total_periods = Column(Integer, nullable=False) # 總期數 (例如 12)
    current_period = Column(Integer, default=0, nullable=False) # 目前已繳/已扣期數 (例如 3)
    monthly_amount = Column(Float, nullable=False) # 每期本金 (通常為 total_amount / total_periods)
    first_amount = Column(Float, nullable=True) # 首期金額 (若除不盡由首期吸收差額)
    interest_rate = Column(Float, default=0.0) # 年利率 % (零利率則為 0.0)
    monthly_fee = Column(Float, default=0.0) # 每期手續費或利息
    category = Column(String(50), default="其他") # 分類 (例如 購物, 數位3C)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True) # 關聯扣款信用卡或銀行帳戶
    start_date = Column(Date, nullable=False) # 首期入帳/起算日
    billing_day = Column(Integer, default=1) # 每月入帳日 (1-31)
    status = Column(String(20), default="ACTIVE") # ACTIVE (進行中), COMPLETED (已結清), CANCELLED (終止)
    notes = Column(String(255), nullable=True) # 備註
    auto_record = Column(Boolean, default=True) # 是否到期自動記帳
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id])
    transactions = relationship("Transaction", back_populates="installment_plan")

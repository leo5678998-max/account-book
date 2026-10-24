from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base


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
    bills_to_debit = relationship("Bill", back_populates="debit_account")

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    date = Column(DateTime, default=datetime.utcnow)
    amount = Column(Float, nullable=False)
    tx_type = Column(String(20), nullable=False) # EXPENSE, INCOME, TRANSFER
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    target_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True) # 轉帳目標帳戶
    category = Column(String(50), default="其他") # 餐飲, 交通, 信用卡費, 薪資...
    description = Column(String(255), nullable=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=True)
    affects_balance = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id], back_populates="transactions")
    target_account = relationship("Account", foreign_keys=[target_account_id])
    bill = relationship("Bill", foreign_keys=[bill_id])

class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), default=1, index=True, nullable=True)
    bank_name = Column(String(100), default="星展銀行")
    statement_month = Column(String(20), nullable=True) # e.g. "2026-10"
    statement_date = Column(Date, nullable=True) # 結帳日
    due_date = Column(Date, nullable=False) # 繳款截止日 / 自動扣款日
    total_amount = Column(Float, nullable=False) # 本期應繳總額
    minimum_amount = Column(Float, default=0.0) # 最低應繳金額
    status = Column(String(20), default="PENDING") # PENDING (待扣款), PAID (已扣款), SKIPPED (忽略)
    email_message_id = Column(String(255), unique=True, nullable=True) # Gmail/IMAP Message ID 防重複抓取
    pdf_filename = Column(String(255), nullable=True)
    debit_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    paid_date = Column(DateTime, nullable=True)
    paid_transaction_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    debit_account = relationship("Account", back_populates="bills_to_debit")

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
    is_active = Column(Boolean, default=True) # 是否啟用此固定花費
    notes = Column(String(255), nullable=True) # 備註
    last_charged_month = Column(String(20), nullable=True) # 最近一次扣款月份 (e.g. "2026-10") 防重複扣款
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id])

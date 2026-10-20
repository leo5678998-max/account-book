from sqlalchemy import Column, Integer, String, Float, DateTime, Date, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from .database import Base

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
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
    date = Column(DateTime, default=datetime.utcnow)
    amount = Column(Float, nullable=False)
    tx_type = Column(String(20), nullable=False) # EXPENSE, INCOME, TRANSFER
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False)
    target_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True) # 轉帳目標帳戶
    category = Column(String(50), default="其他") # 餐飲, 交通, 信用卡費, 薪資...
    description = Column(String(255), nullable=True)
    bill_id = Column(Integer, ForeignKey("bills.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    account = relationship("Account", foreign_keys=[account_id], back_populates="transactions")
    target_account = relationship("Account", foreign_keys=[target_account_id])
    bill = relationship("Bill", foreign_keys=[bill_id])

class Bill(Base):
    __tablename__ = "bills"

    id = Column(Integer, primary_key=True, index=True)
    bank_name = Column(String(100), default="星展銀行")
    statement_month = Column(String(20), nullable=True) # e.g. "2026-10"
    statement_date = Column(Date, nullable=True) # 結帳日
    due_date = Column(Date, nullable=False) # 繳款截止日 / 自動扣款日
    total_amount = Column(Float, nullable=False) # 本期應繳總額
    minimum_amount = Column(Float, default=0.0) # 最低應繳金額
    status = Column(String(20), default="PENDING") # PENDING (待扣款), PAID (已扣款), SKIPPED (忽略)
    email_message_id = Column(String(255), unique=True, nullable=True) # Gmail Message ID 防重複抓取
    pdf_filename = Column(String(255), nullable=True)
    debit_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    paid_date = Column(DateTime, nullable=True)
    paid_transaction_id = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    debit_account = relationship("Account", back_populates="bills_to_debit")

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, index=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(String(255), nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


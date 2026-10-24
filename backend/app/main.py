import sys
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .database import engine, Base
from . import models  # 確保所有 ORM Model 均被載入註冊
from .services.auth_service import run_schema_migrations
from .services.scheduler import start_scheduler, stop_scheduler
from .routers import auth, accounts, transactions, bills, stocks, recurring, settings, analytics

# 初始化資料表與升級既有資料庫欄位
Base.metadata.create_all(bind=engine)
run_schema_migrations(engine)

app = FastAPI(
    title="Personal Finance & Auto Bill Debit",
    description="多帳戶資產記帳、AI 智能多單據辨識 (各家信用卡/薪資單) 與自動扣款系統",
    version="2.1.0"
)

# 支援跨來源存取 (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 掛載靜態資源目錄
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def serve_index():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        return FileResponse(
            index_file,
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0"
            }
        )
    return {"message": "Account Book API is running"}


@app.on_event("startup")
def on_startup():
    start_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    stop_scheduler()


# 註冊各領域模組路由 (High Cohesion, Low Coupling)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(bills.router)
app.include_router(stocks.router)
app.include_router(recurring.router)
app.include_router(settings.router)
app.include_router(analytics.router)

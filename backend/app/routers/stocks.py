from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..models import User, StockHolding
from ..schemas import (
    StockHoldingCreate,
    StockHoldingUpdate,
    StockHoldingResponse,
    StockPortfolioSummary
)
from ..services.auth_service import get_current_user
from ..services.stock_service import (
    fetch_single_quote,
    refresh_all_stock_prices,
    build_holding_response,
    build_portfolio_summary
)

router = APIRouter(prefix="/api/stocks", tags=["Stocks"])


@router.get("", response_model=StockPortfolioSummary)
def get_stock_portfolio(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """取得當前使用者所有持股清單與投資組合即時市值/損益彙總"""
    return build_portfolio_summary(db, user_id=current_user.id)


@router.post("", response_model=StockHoldingResponse)
def create_stock_holding(
    req: StockHoldingCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """新增一筆持股庫存並即時抓取現價"""
    quote = fetch_single_quote(req.symbol)
    resolved_symbol = quote.get("symbol") or req.symbol.strip().upper()
    stock_name = req.name or quote.get("name") or resolved_symbol
    price = quote.get("price") or req.cost_price
    currency = req.currency or quote.get("currency") or "TWD"

    holding = StockHolding(
        user_id=current_user.id,
        symbol=resolved_symbol,
        name=stock_name,
        shares=req.shares,
        cost_price=req.cost_price,
        current_price=price,
        currency=currency,
        notes=req.notes
    )
    db.add(holding)
    db.commit()
    db.refresh(holding)
    return build_holding_response(holding)


@router.put("/{stock_id}", response_model=StockHoldingResponse)
def update_stock_holding(
    stock_id: int,
    req: StockHoldingUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """編輯持股資料"""
    holding = db.query(StockHolding).filter(
        StockHolding.id == stock_id,
        StockHolding.user_id == current_user.id
    ).first()
    if not holding:
        raise HTTPException(status_code=404, detail="找不到該持股資料")

    if req.symbol and req.symbol != holding.symbol:
        quote = fetch_single_quote(req.symbol)
        holding.symbol = quote.get("symbol") or req.symbol
        if quote.get("price", 0) > 0:
            holding.current_price = quote["price"]
        if not req.name and quote.get("name"):
            holding.name = quote["name"]
        if quote.get("currency"):
            holding.currency = quote["currency"]

    if req.name is not None:
        holding.name = req.name
    if req.shares is not None:
        holding.shares = req.shares
    if req.cost_price is not None:
        holding.cost_price = req.cost_price
    if req.currency is not None:
        holding.currency = req.currency
    if req.notes is not None:
        holding.notes = req.notes

    holding.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(holding)
    return build_holding_response(holding)


@router.delete("/{stock_id}")
def delete_stock_holding(
    stock_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """刪除持股紀錄"""
    holding = db.query(StockHolding).filter(
        StockHolding.id == stock_id,
        StockHolding.user_id == current_user.id
    ).first()
    if not holding:
        raise HTTPException(status_code=404, detail="找不到該持股資料")
    db.delete(holding)
    db.commit()
    return {"status": "success", "message": f"已刪除 {holding.name or holding.symbol}"}


@router.post("/refresh")
def refresh_stock_quotes(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """手動觸發當前使用者所有持股市價更新"""
    count = refresh_all_stock_prices(db, user_id=current_user.id)
    return {"status": "success", "message": f"已成功更新 {count} 檔持股市價", "updated_count": count}

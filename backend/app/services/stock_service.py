import re
import sys
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

import yfinance as yf
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from datetime import datetime
from ..models import StockHolding
from ..schemas import StockHoldingResponse, StockPortfolioSummary

# 常見熱門標的中文名映射 (可免去頻繁請求 info API)
POPULAR_NAMES = {
    "2330.TW": "台積電",
    "2330.TWO": "台積電",
    "2317.TW": "鴻海",
    "2454.TW": "聯發科",
    "0050.TW": "元大台灣50",
    "0056.TW": "元大高股息",
    "00878.TW": "國泰永續高股息",
    "00919.TW": "群益台灣精選高息",
    "00929.TW": "復華台灣科技優息",
    "00981A.TW": "主動統一台股增長",
    "00981A.TWO": "主動統一台股增長",
    "2881.TW": "富邦金",
    "2882.TW": "國泰金",
    "2891.TW": "中信金",
    "NVDA": "NVIDIA (輝達)",
    "AAPL": "Apple (蘋果)",
    "TSLA": "Tesla (特斯拉)",
    "MSFT": "Microsoft (微軟)",
    "GOOGL": "Alphabet (Google)",
    "AMZN": "Amazon (亞馬遜)",
    "VOO": "Vanguard S&P 500 ETF",
    "QQQ": "Invesco QQQ Trust",
    "VT": "Vanguard 全球股票 ETF",
}

DEFAULT_FALLBACK_RATES = {
    "USD": 32.3,
    "JPY": 0.205,
    "EUR": 35.5,
    "CNY": 4.5,
    "RMB": 4.5,
    "HKD": 4.1,
    "GBP": 41.0,
    "KRW": 0.023,
    "AUD": 21.0,
    "CAD": 23.5,
    "SGD": 24.2,
}

def get_currency_rate_to_twd(currency: str) -> float:
    """取得任意主要外幣兌新台幣的即時匯率 (支援 USD, JPY, EUR, CNY 等)"""
    if not currency:
        return 1.0
    curr = currency.strip().upper()
    if curr in ("TWD", "NTD", "NT$", "NT"):
        return 1.0

    ticker_sym = f"{curr}TWD=X"
    try:
        ticker = yf.Ticker(ticker_sym)
        rate = ticker.fast_info.get("lastPrice")
        if rate and rate > 0:
            precision = 4 if curr in ("JPY", "KRW") else 2
            return round(float(rate), precision)
    except Exception as e:
        print(f"[StockService] 取得 {ticker_sym} 匯率失敗: {e}")

    return DEFAULT_FALLBACK_RATES.get(curr, 1.0)

def get_usd_to_twd_rate() -> float:
    """取得即時美金兌台幣匯率"""
    return get_currency_rate_to_twd("USD")

def resolve_symbol(raw_symbol: str) -> str:
    """自動規範化股票代號，台股 (含純數字代號、特別股與主動式 ETF 如 00981A) 自動補上 .TW 或 .TWO，美股轉大寫"""
    sym = raw_symbol.strip().upper()
    if "." in sym:
        return sym
    
    # 台股特徵判斷：4~6 碼純數字 (如 2330, 0050)，或 4~5 碼數字加上 1~2 碼英文字母後綴 (如 00981A, 2882A, 00632R)
    if re.match(r"^\d{4,6}[A-Z]{0,2}$", sym):
        return f"{sym}.TW"
    
    return sym

def fetch_single_quote(raw_symbol: str) -> Dict[str, Any]:
    """
    抓取單一股票的即時市價、幣別與名稱
    """
    target_symbol = resolve_symbol(raw_symbol)
    price = 0.0
    name = POPULAR_NAMES.get(target_symbol, "")
    currency = "USD" if not (target_symbol.endswith(".TW") or target_symbol.endswith(".TWO")) else "TWD"

    try:
        ticker = yf.Ticker(target_symbol)
        last_price = ticker.fast_info.get("lastPrice")
        
        # 若以 .TW 找不到且原本是純數字，嘗試櫃買市場 .TWO
        if (last_price is None or last_price == 0) and target_symbol.endswith(".TW"):
            alt_symbol = target_symbol.replace(".TW", ".TWO")
            alt_ticker = yf.Ticker(alt_symbol)
            alt_price = alt_ticker.fast_info.get("lastPrice")
            if alt_price and alt_price > 0:
                target_symbol = alt_symbol
                last_price = alt_price

        if last_price and last_price > 0:
            price = round(float(last_price), 2)

        # 若無中文快取名，嘗試取得簡稱
        if not name:
            try:
                name = ticker.fast_info.get("symbol", "") or target_symbol
            except Exception:
                name = target_symbol

    except Exception as e:
        print(f"[StockService] 抓取 {target_symbol} 報價失敗: {e}")

    return {
        "symbol": target_symbol,
        "name": name,
        "price": price,
        "currency": currency
    }

def refresh_all_stock_prices(db: Session, user_id: Optional[int] = None) -> int:
    """更新資料庫中持股的最新價格 (可針對特定使用者或全部使用者)"""
    query = db.query(StockHolding)
    if user_id is not None:
        query = query.filter(StockHolding.user_id == user_id)
    holdings = query.all()
    updated_count = 0
    for h in holdings:
        quote = fetch_single_quote(h.symbol)
        if quote.get("price", 0) > 0:
            h.current_price = quote["price"]
            h.currency = quote.get("currency", h.currency)
            if quote.get("symbol") and quote["symbol"] != h.symbol:
                h.symbol = quote["symbol"]
            if (not h.name or h.name == h.symbol or h.name == "00981A") and quote.get("name"):
                h.name = quote["name"]
            h.updated_at = datetime.utcnow()
            updated_count += 1
    db.commit()
    return updated_count


def build_holding_response(h: StockHolding, usd_rate: Optional[float] = None) -> StockHoldingResponse:
    """計算單一持股之成本、現值、未實現損益與台幣折算"""
    if usd_rate is None:
        usd_rate = get_usd_to_twd_rate()

    cost = round(h.shares * h.cost_price, 2)
    price = h.current_price if (h.current_price and h.current_price > 0) else h.cost_price
    mv = round(h.shares * price, 2)
    pnl = round(mv - cost, 2)
    ret = round((pnl / cost * 100), 2) if cost > 0 else 0.0
    rate = usd_rate if h.currency == "USD" else 1.0

    return StockHoldingResponse(
        id=h.id,
        symbol=h.symbol,
        name=h.name or h.symbol,
        shares=h.shares,
        cost_price=h.cost_price,
        current_price=price or 0.0,
        currency=h.currency,
        notes=h.notes,
        total_cost=cost,
        market_value=mv,
        unrealized_pnl=pnl,
        return_rate=ret,
        market_value_twd=round(mv * rate, 2),
        unrealized_pnl_twd=round(pnl * rate, 2),
        created_at=h.created_at,
        updated_at=h.updated_at
    )


def build_portfolio_summary(db: Session, user_id: int = 1) -> StockPortfolioSummary:
    """彙整指定使用者的所有持股清單與投資組合總市值、總損益"""
    holdings = db.query(StockHolding).filter(
        StockHolding.user_id == user_id
    ).order_by(StockHolding.id.desc()).all()
    usd_rate = get_usd_to_twd_rate()

    total_market_value_twd = 0.0
    total_cost_twd = 0.0
    holding_responses = []

    for h in holdings:
        res = build_holding_response(h, usd_rate)
        rate = usd_rate if h.currency == "USD" else 1.0
        total_market_value_twd += res.total_cost * rate + res.unrealized_pnl * rate
        total_cost_twd += res.total_cost * rate
        holding_responses.append(res)

    total_unrealized_pnl_twd = total_market_value_twd - total_cost_twd
    total_return_rate = round((total_unrealized_pnl_twd / total_cost_twd * 100), 2) if total_cost_twd > 0 else 0.0

    return StockPortfolioSummary(
        total_market_value_twd=round(total_market_value_twd, 2),
        total_cost_twd=round(total_cost_twd, 2),
        total_unrealized_pnl_twd=round(total_unrealized_pnl_twd, 2),
        total_return_rate=total_return_rate,
        usd_to_twd_rate=usd_rate,
        holdings=holding_responses
    )


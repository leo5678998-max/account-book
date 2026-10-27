import unittest
import os
import sys

# Set up module path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from datetime import datetime
from app.services.stock_service import resolve_symbol, build_holding_response
from app.models import StockHolding


class TestStockService(unittest.TestCase):
    def test_resolve_symbol_taiwan_stocks(self):
        # 1. 傳統 4 碼台股
        self.assertEqual(resolve_symbol("2330"), "2330.TW")
        self.assertEqual(resolve_symbol("2454"), "2454.TW")

        # 2. 5~6 碼 ETF
        self.assertEqual(resolve_symbol("0050"), "0050.TW")
        self.assertEqual(resolve_symbol("00878"), "00878.TW")
        self.assertEqual(resolve_symbol("00919"), "00919.TW")

        # 3. 主動式 ETF 與帶英文字母後綴之標的 (如 00981A)
        self.assertEqual(resolve_symbol("00981A"), "00981A.TW")
        self.assertEqual(resolve_symbol("00981a"), "00981A.TW")

        # 4. 特別股 (如 2882A, 2881A)
        self.assertEqual(resolve_symbol("2882A"), "2882A.TW")

        # 5. 槓桿/反向型 ETF (如 00632R, 00637L)
        self.assertEqual(resolve_symbol("00632R"), "00632R.TW")
        self.assertEqual(resolve_symbol("00637L"), "00637L.TW")

    def test_resolve_symbol_us_stocks(self):
        # 美股標的保持原代號
        self.assertEqual(resolve_symbol("AAPL"), "AAPL")
        self.assertEqual(resolve_symbol("aapl"), "AAPL")
        self.assertEqual(resolve_symbol("NVDA"), "NVDA")
        self.assertEqual(resolve_symbol("VOO"), "VOO")

    def test_resolve_symbol_already_qualified(self):
        # 已有後綴者保持不變
        self.assertEqual(resolve_symbol("2330.TW"), "2330.TW")
        self.assertEqual(resolve_symbol("00981A.TW"), "00981A.TW")
        self.assertEqual(resolve_symbol("6547.TWO"), "6547.TWO")

    def test_build_holding_response_calculations(self):
        # 測試台股持股計算
        now = datetime.utcnow()
        holding_twd = StockHolding(
            id=1,
            symbol="00981A.TW",
            name="主動統一台股增長",
            shares=2000.0,
            cost_price=28.81,
            current_price=27.4,
            currency="TWD",
            created_at=now,
            updated_at=now
        )
        resp = build_holding_response(holding_twd)
        self.assertEqual(resp.total_cost, 57620.0)  # 2000 * 28.81
        self.assertEqual(resp.market_value, 54800.0)  # 2000 * 27.4
        self.assertEqual(resp.unrealized_pnl, -2820.0)  # 54800 - 57620
        self.assertEqual(resp.currency, "TWD")


if __name__ == "__main__":
    unittest.main()

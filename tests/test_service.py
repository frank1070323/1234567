import unittest
from datetime import date, timedelta

from stock_app.data_sources import DailyPrice, DataSourceUnavailableError
from stock_app.service import (
    InvalidSymbolError,
    SourceUnavailableError,
    StockAnalysisService,
    _detect_kd_signal,
    _is_valid_symbol,
)
from stock_app.supplemental_sources import (
    CompanyProfile,
    InstitutionalMetrics,
    NewsMetrics,
    RevenueMetrics,
    ValuationMetrics,
)


def build_prices(start_close=100, days=40, last_bump=0):
    base = date(2026, 2, 1)
    prices = []
    close = start_close
    for idx in range(days):
        if idx > days - 5:
            close += 2 + last_bump
        else:
            close += 0.4
        prices.append(
            DailyPrice(
                trade_date=base + timedelta(days=idx),
                open_price=close - 1,
                high_price=close + 2,
                low_price=close - 2,
                close_price=round(close, 2),
                volume=5000 + idx,
            )
        )
    return prices


def build_strong_breakout_prices(days=160):
    prices = []
    base = date(2025, 9, 1)
    close = 80.0
    for idx in range(days):
        if idx < 120:
            close += 0.6
            volume = 3000 + (idx % 7) * 40
        elif idx < 155:
            close += 1.1
            volume = 4200 + (idx % 5) * 60
        else:
            close += 2.8
            volume = 10500 + idx * 30
        prices.append(
            DailyPrice(
                trade_date=base + timedelta(days=idx),
                open_price=round(close - 1.2, 2),
                high_price=round(close + 2.5, 2),
                low_price=round(close - 2.0, 2),
                close_price=round(close, 2),
                volume=volume,
            )
        )
    return prices


class FakeClient:
    def __init__(self, responses=None, error=None):
        self.responses = responses or []
        self.error = error
        self.calls = 0

    def fetch_month(self, symbol, target_date):
        if self.error:
            raise self.error
        index = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[index]


class FakeSupplemental:
    def fetch_company_profile(self, symbol, market, fallback_name):
        return CompanyProfile(symbol=symbol, name=fallback_name, industry="通信網路業", market_type="sii")

    def fetch_revenue_metrics(self, symbol, market):
        return RevenueMetrics(
            month_label="2026-04",
            revenue=123456789,
            previous_revenue=117300000,
            last_year_revenue=104100000,
            yoy=18.6,
            mom=5.2,
            cumulative_revenue=456700000,
            cumulative_last_year_revenue=410500000,
            cumulative_yoy=11.3,
            note="測試資料",
        )

    def fetch_valuation_metrics(self, symbol, market):
        return ValuationMetrics(pe=15.2, pb=2.1, dividend_yield=3.4)

    def fetch_institutional_metrics(self, symbol, market):
        return InstitutionalMetrics(
            recent_days=[],
            foreign_5d=1200,
            investment_5d=300,
            dealer_5d=-200,
            total_5d=1300,
            total_10d=2100,
            total_20d=3600,
            streak="連2日回補",
        )

    def fetch_news_metrics(self, symbol, name):
        return NewsMetrics(heat="中", sentiment="偏多", score=2, items=[])

    def infer_themes(self, symbol, name, industry):
        return "CPO / 光通訊", ["CPO", "光通訊"]

    def peer_symbols(self, symbol, group_name):
        return []


class ServiceTests(unittest.TestCase):
    def test_collect_market_history_keeps_going_when_one_month_fails(self):
        partial = FakeClient(
            responses=[
                ("光聖", build_strong_breakout_prices()),
                ("光聖", build_strong_breakout_prices()),
            ]
        )
        calls = {"count": 0}
        original_fetch_month = partial.fetch_month

        def flaky_fetch_month(symbol, target_date):
            calls["count"] += 1
            if calls["count"] == 2:
                raise DataSourceUnavailableError("temporary")
            return original_fetch_month(symbol, target_date)

        partial.fetch_month = flaky_fetch_month
        service = StockAnalysisService(
            twse_client=partial,
            tpex_client=FakeClient(responses=[(None, [])] * 3),
            supplemental_service=FakeSupplemental(),
            months_to_scan=3,
        )

        result = service.analyze("6442")

        self.assertEqual(result["symbol"], "6442")
        self.assertEqual(result["market"], "上市")

    def test_switches_to_tpex_when_twse_has_no_rows(self):
        twse = FakeClient(responses=[(None, [])] * 3)
        tpex = FakeClient(responses=[("世紀", build_strong_breakout_prices())] * 3)
        service = StockAnalysisService(
            twse_client=twse,
            tpex_client=tpex,
            supplemental_service=FakeSupplemental(),
            months_to_scan=3,
        )

        result = service.analyze("6442")

        self.assertEqual(result["market"], "上櫃")
        self.assertEqual(result["symbol"], "6442")

    def test_invalid_symbol_returns_clear_error(self):
        service = StockAnalysisService(
            twse_client=FakeClient(responses=[(None, [])]),
            tpex_client=FakeClient(responses=[(None, [])]),
            supplemental_service=FakeSupplemental(),
            months_to_scan=1,
        )

        with self.assertRaises(InvalidSymbolError):
            service.analyze("ABCD")

    def test_alphanumeric_symbol_is_allowed(self):
        service = StockAnalysisService(
            twse_client=FakeClient(responses=[("測試ETF", build_strong_breakout_prices())] * 3),
            tpex_client=FakeClient(responses=[(None, [])] * 3),
            supplemental_service=FakeSupplemental(),
            months_to_scan=3,
        )

        result = service.analyze("00981a")

        self.assertEqual(result["symbol"], "00981A")

    def test_symbol_validation_rules(self):
        self.assertTrue(_is_valid_symbol("6442"))
        self.assertTrue(_is_valid_symbol("00981A"))
        self.assertFalse(_is_valid_symbol("ABCD"))
        self.assertFalse(_is_valid_symbol("00-981A"))

    def test_source_failure_is_reported(self):
        service = StockAnalysisService(
            twse_client=FakeClient(error=DataSourceUnavailableError("boom")),
            tpex_client=FakeClient(error=DataSourceUnavailableError("boom")),
            supplemental_service=FakeSupplemental(),
            months_to_scan=1,
        )

        with self.assertRaises(SourceUnavailableError):
            service.analyze("6442")

    def test_golden_cross_signal_is_exposed(self):
        tpex = FakeClient(responses=[("世紀", build_strong_breakout_prices())] * 3)
        service = StockAnalysisService(
            twse_client=FakeClient(responses=[(None, [])] * 3),
            tpex_client=tpex,
            supplemental_service=FakeSupplemental(),
            months_to_scan=3,
        )

        result = service.analyze("6442")

        self.assertIn(result["kdSignal"], {"黃金交叉", "無", "死亡交叉"})
        self.assertIn(result["macdZeroAxis"], {"零上", "零下"})
        self.assertIn(result["decision"]["recommendation"], {"建議進場", "進入觀察", "暫不進場"})
        self.assertIn("ma5", result)
        self.assertIn("vma20", result)

    def test_kd_signal_scenarios(self):
        self.assertEqual(_detect_kd_signal(20, 22, 25, 23), "黃金交叉")
        self.assertEqual(_detect_kd_signal(24, 21, 19, 20), "死亡交叉")
        self.assertEqual(_detect_kd_signal(24, 21, 25, 22), "無")

    def test_breakout_scoring_fields_are_returned(self):
        service = StockAnalysisService(
            twse_client=FakeClient(responses=[(None, [])] * 3),
            tpex_client=FakeClient(responses=[("世紀", build_strong_breakout_prices())] * 3),
            supplemental_service=FakeSupplemental(),
            months_to_scan=3,
        )

        result = service.analyze("6442")

        self.assertGreaterEqual(result["volumeAnalysis"]["volumeRatio5"], 1.0)
        self.assertLessEqual(result["decision"]["score"], result["decision"]["maxScore"])
        self.assertIn("綜合評分", result["tradeNarrative"])
        self.assertEqual(result["revenue"]["monthLabel"], "2026-04")
        self.assertEqual(result["valuation"]["pe"], 15.2)
        self.assertEqual(result["themeGroup"], "CPO / 光通訊")
        self.assertEqual(result["costAnalysis"]["status"], "未輸入成本價")

    def test_cost_basis_analysis_is_returned(self):
        service = StockAnalysisService(
            twse_client=FakeClient(responses=[(None, [])] * 3),
            tpex_client=FakeClient(responses=[("世紀", build_strong_breakout_prices())] * 3),
            supplemental_service=FakeSupplemental(),
            months_to_scan=3,
        )

        result = service.analyze("6442", cost_basis=120.0)

        self.assertEqual(result["costAnalysis"]["costBasis"], 120.0)
        self.assertIsNotNone(result["costAnalysis"]["pnl"])
        self.assertTrue(result["costAnalysis"]["status"])

    def test_risk_analysis_fields_are_returned(self):
        service = StockAnalysisService(
            twse_client=FakeClient(responses=[(None, [])] * 3),
            tpex_client=FakeClient(responses=[("世紀", build_strong_breakout_prices())] * 3),
            supplemental_service=FakeSupplemental(),
            months_to_scan=3,
        )

        result = service.analyze("6442", cost_basis=120.0, target_price=180.0, stop_price=100.0)

        self.assertIn("riskAnalysis", result)
        self.assertIsNotNone(result["riskAnalysis"]["atr14"])
        self.assertIsNotNone(result["riskAnalysis"]["primarySupport"])
        self.assertIsNotNone(result["riskAnalysis"]["resistance"])
        self.assertGreater(result["riskAnalysis"]["rewardRiskRatio"], 0)


if __name__ == "__main__":
    unittest.main()

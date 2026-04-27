import unittest
from datetime import date, timedelta

from stock_app.data_sources import DailyPrice
from stock_app.indicators import calculate_indicators


def make_prices(closes):
    base = date(2026, 1, 1)
    prices = []
    for idx, close in enumerate(closes):
        prices.append(
            DailyPrice(
                trade_date=base + timedelta(days=idx),
                open_price=close - 1,
                high_price=close + 2,
                low_price=close - 2,
                close_price=close,
                volume=1000 + idx,
            )
        )
    return prices


class IndicatorTests(unittest.TestCase):
    def test_kd_and_macd_are_stable_for_fixed_history(self):
        closes = [
            100, 102, 101, 104, 106, 108, 110, 109, 111, 115,
            117, 116, 118, 121, 125, 123, 122, 126, 128, 127,
            131, 134, 133, 136, 138, 141, 140, 144, 147, 149,
        ]
        indicators = calculate_indicators(make_prices(closes))

        self.assertAlmostEqual(indicators.k_values[-1], 89.0199, places=4)
        self.assertAlmostEqual(indicators.d_values[-1], 87.9854, places=4)
        self.assertAlmostEqual(indicators.dif_values[-1], 9.5737, places=4)
        self.assertAlmostEqual(indicators.dea_values[-1], 8.3171, places=4)
        self.assertAlmostEqual(indicators.osc_values[-1], 1.2566, places=4)


if __name__ == "__main__":
    unittest.main()

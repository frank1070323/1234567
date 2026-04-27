import unittest

from stock_app.supplemental_sources import RevenueMetrics, SupplementalDataService, _normalize_revenue_month


class RevenueFallbackService(SupplementalDataService):
    def __init__(self):
        super().__init__(http_client=None)

    def _fetch_revenue_metrics(self, symbol, market_type):
        if market_type == "otc":
            return None
        return RevenueMetrics(
            month_label="2026-03",
            revenue=1012955,
            previous_revenue=738625,
            last_year_revenue=576987,
            yoy=75.56,
            mom=37.14,
            cumulative_revenue=2706089,
            cumulative_last_year_revenue=2104723,
            cumulative_yoy=28.57,
            note="市場需求增加",
        )


class SupplementalSourcesTests(unittest.TestCase):
    def test_normalize_revenue_month_supports_roc_format(self):
        self.assertEqual(_normalize_revenue_month("11503"), "2026-03")

    def test_revenue_metrics_fall_back_to_other_market_when_primary_is_empty(self):
        service = RevenueFallbackService()

        metrics = service.fetch_revenue_metrics("6442", "上櫃")

        self.assertEqual(metrics.month_label, "2026-03")
        self.assertEqual(metrics.revenue, 1012955)


if __name__ == "__main__":
    unittest.main()

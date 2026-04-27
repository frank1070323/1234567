import json
import unittest
from datetime import date

from stock_app.data_sources import HttpJsonClient, TpexClient


class CaptureTpexHttpClient(HttpJsonClient):
    def __init__(self):
        super().__init__(timeout=1)
        self.calls = []

    def post_text(self, url, params, headers=None):
        self.calls.append(("post", url, params))
        return json.dumps(
            {
                "stat": "ok",
                "tables": [
                    {
                        "title": "個股日成交資訊",
                        "date": "20260401",
                        "data": [
                            ["115/04/01", "1,101", "241,438", "219.50", "223.00", "215.00", "217.00", "8.50", "1,456"]
                        ],
                    }
                ],
            }
        )


class DataSourcesTests(unittest.TestCase):
    def test_tpex_client_posts_gregorian_month_start_date(self):
        http = CaptureTpexHttpClient()
        client = TpexClient(http_client=http)

        name, rows = client.fetch_month("6568", date(2026, 4, 1))

        self.assertEqual(http.calls[0][2]["date"], "2026/04/01")
        self.assertEqual(len(rows), 1)
        self.assertIsNone(name)


if __name__ == "__main__":
    unittest.main()

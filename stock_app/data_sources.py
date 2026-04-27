from __future__ import annotations

import http.client
import json
import socket
import time
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import Iterable
from urllib import error, parse, request


class DataFetchError(Exception):
    pass


class DataSourceUnavailableError(DataFetchError):
    pass


@dataclass(frozen=True)
class DailyPrice:
    trade_date: date
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int


class HttpJsonClient:
    def __init__(self, timeout: int = 20, retries: int = 2, retry_delay: float = 0.35):
        self.timeout = timeout
        self.retries = retries
        self.retry_delay = retry_delay

    def get_json(self, url: str, params: dict[str, str]) -> dict:
        full_url = f"{url}?{parse.urlencode(params)}"
        def load() -> dict:
            req = self._build_request(full_url)
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))

        return self._with_retries(load)

    def post_text(self, url: str, params: dict[str, str], headers: dict[str, str] | None = None) -> str:
        def load() -> str:
            req = self._build_request(url, parse.urlencode(params).encode("utf-8"), headers=headers)
            req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")

        return self._with_retries(load)

    def get_text(self, url: str, params: dict[str, str] | None = None, headers: dict[str, str] | None = None) -> str:
        full_url = f"{url}?{parse.urlencode(params)}" if params else url
        def load() -> str:
            req = self._build_request(full_url, headers=headers)
            with request.urlopen(req, timeout=self.timeout) as response:
                return response.read().decode("utf-8")

        return self._with_retries(load)

    def _with_retries(self, fn):
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                return fn()
            except error.HTTPError as exc:
                raise DataSourceUnavailableError(f"來源回應異常：HTTP {exc.code}") from exc
            except json.JSONDecodeError as exc:
                raise DataSourceUnavailableError("來源資料格式異常") from exc
            except (error.URLError, TimeoutError, socket.timeout, http.client.IncompleteRead) as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                time.sleep(self.retry_delay * (attempt + 1))
        raise DataSourceUnavailableError("來源暫時不可用") from last_error

    def _build_request(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> request.Request:
        base_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept": "application/json, text/plain, */*",
            "Connection": "close",
        }
        if headers:
            base_headers.update(headers)
        return request.Request(
            url,
            data=data,
            headers=base_headers,
        )


class TwseClient:
    BASE_URL = "https://www.twse.com.tw/exchangeReport/STOCK_DAY"

    def __init__(self, http_client: HttpJsonClient | None = None):
        self.http_client = http_client or HttpJsonClient()

    def fetch_month(self, symbol: str, target_date: date) -> tuple[str | None, list[DailyPrice]]:
        payload = self.http_client.get_json(
            self.BASE_URL,
            {
                "response": "json",
                "date": target_date.strftime("%Y%m01"),
                "stockNo": symbol,
            },
        )

        stat = str(payload.get("stat", ""))
        if "很抱歉" in stat or "沒有符合條件" in stat:
            return None, []
        if stat and stat != "OK":
            raise DataSourceUnavailableError(stat)

        title = str(payload.get("title", ""))
        name = _extract_name_from_title(title, symbol)
        rows = payload.get("data") or []
        return name, _parse_twse_rows(rows)


class TpexClient:
    HTML_ENDPOINT = "https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
    ENDPOINTS = (
        (
            "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyTrading",
            lambda symbol, target_date: {
                "code": symbol,
                "date": target_date.strftime("%Y/%m/01"),
                "response": "json",
            },
        ),
        (
            "https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_info/st43_result.php",
            lambda symbol, target_date: {
                "l": "zh-tw",
                "d": f"{target_date.year - 1911}/{target_date.month:02d}",
                "stkno": symbol,
            },
        ),
    )

    def __init__(self, http_client: HttpJsonClient | None = None):
        self.http_client = http_client or HttpJsonClient()

    def fetch_month(self, symbol: str, target_date: date) -> tuple[str | None, list[DailyPrice]]:
        try:
            html = self.http_client.post_text(
                self.HTML_ENDPOINT,
                {
                    "code": symbol,
                    "date": target_date.strftime("%Y/%m/01"),
                    "response": "json",
                },
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Origin": "https://www.tpex.org.tw",
                    "Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/stock-pricing.html",
                    "X-Requested-With": "XMLHttpRequest",
                },
            )
            payload = json.loads(html)
            name, rows = self._parse_payload(symbol, payload)
            if rows:
                return name, rows
        except (DataSourceUnavailableError, json.JSONDecodeError):
            pass

        last_error: Exception | None = None

        for endpoint, build_params in self.ENDPOINTS:
            try:
                payload = self.http_client.get_json(endpoint, build_params(symbol, target_date))
                return self._parse_payload(symbol, payload)
            except DataSourceUnavailableError as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise DataSourceUnavailableError("來源暫時不可用")

    def _parse_html_payload(self, symbol: str, html: str) -> tuple[str | None, list[DailyPrice]]:
        if "請輸入股票代碼或關鍵字查詢" in html or "參數輸入錯誤" in html:
            return None, []
        parser = TpexHtmlParser()
        parser.feed(html)
        return _extract_name_from_title(parser.title, symbol), _parse_tpex_rows(parser.rows)

    def _parse_payload(self, symbol: str, payload: dict) -> tuple[str | None, list[DailyPrice]]:
        if not payload:
            return None, []

        if payload.get("iTotalRecords") == 0:
            return None, []

        if "tables" in payload:
            tables = payload.get("tables") or []
            if not tables:
                return None, []
            table = tables[0]
            title = str(table.get("title", ""))
            rows = table.get("data") or []
            return _extract_name_from_title(title, symbol), _parse_tpex_rows(rows)

        if "aaData" in payload:
            title = str(payload.get("title", ""))
            return _extract_name_from_title(title, symbol), _parse_tpex_rows(payload.get("aaData") or [])

        stat = str(payload.get("stat", ""))
        if "沒有符合條件" in stat:
            return None, []
        raise DataSourceUnavailableError("來源資料格式異常")


class TpexHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_heading = False
        self.capture_title = False
        self.title_parts: list[str] = []
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.rows: list[list[str]] = []

    @property
    def title(self) -> str:
        return " ".join(self.title_parts).strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]):
        if tag == "h2":
            self.in_heading = True
            return
        if self.in_heading and tag == "div":
            self.capture_title = True
            return
        if tag == "table":
            self.in_table = True
            return
        if self.in_table and tag == "tr":
            self.in_row = True
            self.current_row = []
            return
        if self.in_row and tag in {"td", "th"}:
            self.in_cell = True
            self.current_cell = []

    def handle_endtag(self, tag: str):
        if tag == "h2":
            self.in_heading = False
        elif tag == "div" and self.capture_title:
            self.capture_title = False
        elif tag == "table":
            self.in_table = False
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.current_row and self.current_row[0] not in {"日 期", "日期"}:
                self.rows.append(self.current_row)
        elif tag in {"td", "th"} and self.in_cell:
            self.in_cell = False
            self.current_row.append("".join(self.current_cell).strip())

    def handle_data(self, data: str):
        text = data.strip()
        if not text:
            return
        if self.capture_title:
            self.title_parts.append(text)
        if self.in_cell:
            self.current_cell.append(text)


def _extract_name_from_title(title: str, symbol: str) -> str | None:
    if symbol not in title:
        return None
    suffix = title.split(symbol, 1)[1].strip(" -：:()（）")
    if not suffix:
        return None
    for token in ("個股日成交資訊", "各日成交資訊", "月", "年"):
        suffix = suffix.replace(token, " ")
    cleaned = " ".join(suffix.split()).strip()
    return cleaned or None


def _parse_twse_rows(rows: Iterable[list[str]]) -> list[DailyPrice]:
    prices: list[DailyPrice] = []
    for row in rows:
        if len(row) < 9:
            continue
        try:
            prices.append(
                DailyPrice(
                    trade_date=_parse_roc_date(row[0]),
                    volume=_parse_int(row[1]),
                    open_price=_parse_float(row[3]),
                    high_price=_parse_float(row[4]),
                    low_price=_parse_float(row[5]),
                    close_price=_parse_float(row[6]),
                )
            )
        except ValueError:
            continue
    return prices


def _parse_tpex_rows(rows: Iterable[list[str]]) -> list[DailyPrice]:
    prices: list[DailyPrice] = []
    for row in rows:
        if len(row) < 9:
            continue
        try:
            prices.append(
                DailyPrice(
                    trade_date=_parse_roc_date(row[0]),
                    volume=_parse_int(row[1]),
                    open_price=_parse_float(row[3]),
                    high_price=_parse_float(row[4]),
                    low_price=_parse_float(row[5]),
                    close_price=_parse_float(row[6]),
                )
            )
        except ValueError:
            continue
    return prices


def _parse_roc_date(value: str) -> date:
    year_str, month_str, day_str = value.strip().split("/")
    return date(int(year_str) + 1911, int(month_str), int(day_str))


def _parse_float(value: str) -> float:
    cleaned = value.replace(",", "").replace("X", "").strip()
    if cleaned in {"--", "---", ""}:
        raise ValueError("empty float")
    return float(cleaned)


def _parse_int(value: str) -> int:
    cleaned = value.replace(",", "").strip()
    if cleaned in {"--", "---", ""}:
        raise ValueError("empty int")
    return int(float(cleaned))

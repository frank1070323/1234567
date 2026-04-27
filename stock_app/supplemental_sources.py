from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from html.parser import HTMLParser
from urllib import parse

from .data_sources import DataSourceUnavailableError, HttpJsonClient
from .taxonomy import MANUAL_THEME_OVERRIDES, NEWS_NEGATIVE_WORDS, NEWS_POSITIVE_WORDS, THEME_KEYWORDS


@dataclass(frozen=True)
class CompanyProfile:
    symbol: str
    name: str
    industry: str | None
    market_type: str


@dataclass(frozen=True)
class RevenueMetrics:
    month_label: str | None
    revenue: float | None
    previous_revenue: float | None
    last_year_revenue: float | None
    yoy: float | None
    mom: float | None
    cumulative_revenue: float | None
    cumulative_last_year_revenue: float | None
    cumulative_yoy: float | None
    note: str | None


@dataclass(frozen=True)
class ValuationMetrics:
    pe: float | None
    pb: float | None
    dividend_yield: float | None


@dataclass(frozen=True)
class InstitutionalDay:
    trade_date: str
    foreign_net: int | None
    investment_net: int | None
    dealer_net: int | None
    total_net: int | None


@dataclass(frozen=True)
class InstitutionalMetrics:
    recent_days: list[InstitutionalDay]
    foreign_5d: int
    investment_5d: int
    dealer_5d: int
    total_5d: int
    total_10d: int
    total_20d: int
    streak: str


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str
    source: str
    published: str


@dataclass(frozen=True)
class NewsMetrics:
    heat: str
    sentiment: str
    score: int
    items: list[NewsItem]


class HtmlTableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._cell: list[str] = []
        self._row: list[str] = []
        self._table: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs):
        if tag == "table":
            self._in_table = True
            self._table = []
        elif self._in_table and tag == "tr":
            self._in_row = True
            self._row = []
        elif self._in_row and tag in {"td", "th"}:
            self._in_cell = True
            self._cell = []

    def handle_endtag(self, tag: str):
        if tag == "table" and self._in_table:
            self._in_table = False
            if self._table:
                self.tables.append(self._table)
        elif tag == "tr" and self._in_row:
            self._in_row = False
            if self._row:
                self._table.append(self._row)
        elif tag in {"td", "th"} and self._in_cell:
            self._in_cell = False
            self._row.append("".join(self._cell).strip())

    def handle_data(self, data: str):
        text = data.strip()
        if self._in_cell and text:
            self._cell.append(text)


class SupplementalDataService:
    def __init__(self, http_client: HttpJsonClient | None = None):
        self.http = http_client or HttpJsonClient(timeout=18)

    def fetch_company_profile(self, symbol: str, market: str, fallback_name: str) -> CompanyProfile:
        manual = MANUAL_THEME_OVERRIDES.get(symbol, {})
        market_type = "sii" if market == "上市" else "otc"
        industry = manual.get("industry")
        name = fallback_name
        resolved_market_type = market_type
        for candidate in _market_candidates(market_type):
            try:
                parsed = self._fetch_company_profile_row(symbol, candidate)
            except DataSourceUnavailableError:
                continue
            if parsed["name"] or parsed["industry"]:
                resolved_market_type = candidate
                if parsed["name"]:
                    name = parsed["name"]
                if parsed["industry"]:
                    industry = parsed["industry"]
                break
        return CompanyProfile(symbol=symbol, name=name, industry=industry, market_type=resolved_market_type)

    def fetch_revenue_metrics(self, symbol: str, market: str) -> RevenueMetrics:
        market_type = "sii" if market == "上市" else "otc"
        for candidate in _market_candidates(market_type):
            try:
                metrics = self._fetch_revenue_metrics(symbol, candidate)
                if metrics:
                    return metrics
            except DataSourceUnavailableError:
                continue
        return RevenueMetrics(
            month_label=None,
            revenue=None,
            previous_revenue=None,
            last_year_revenue=None,
            yoy=None,
            mom=None,
            cumulative_revenue=None,
            cumulative_last_year_revenue=None,
            cumulative_yoy=None,
            note=None,
        )

    def fetch_valuation_metrics(self, symbol: str, market: str) -> ValuationMetrics:
        fetchers = (
            (self._fetch_twse_valuation, self._fetch_tpex_valuation)
            if market == "上市"
            else (self._fetch_tpex_valuation, self._fetch_twse_valuation)
        )
        for fetcher in fetchers:
            try:
                metrics = fetcher(symbol)
            except DataSourceUnavailableError:
                continue
            if any(value is not None for value in (metrics.pe, metrics.pb, metrics.dividend_yield)):
                return metrics
        return ValuationMetrics(pe=None, pb=None, dividend_yield=None)

    def fetch_institutional_metrics(self, symbol: str, market: str) -> InstitutionalMetrics:
        market_order = (market, "上櫃" if market == "上市" else "上市")
        recent_days: list[InstitutionalDay] = []
        for candidate_market in market_order:
            recent_days = []
            cursor = date.today()
            attempts = 0
            while len(recent_days) < 20 and attempts < 32:
                attempts += 1
                try:
                    day = self._fetch_institutional_day(symbol, candidate_market, cursor)
                    if day:
                        recent_days.append(day)
                except DataSourceUnavailableError:
                    pass
                cursor -= timedelta(days=1)
            if recent_days:
                break

        foreign_5d = sum(item.foreign_net or 0 for item in recent_days[:5])
        investment_5d = sum(item.investment_net or 0 for item in recent_days[:5])
        dealer_5d = sum(item.dealer_net or 0 for item in recent_days[:5])
        total_5d = sum(item.total_net or 0 for item in recent_days[:5])
        total_10d = sum(item.total_net or 0 for item in recent_days[:10])
        total_20d = sum(item.total_net or 0 for item in recent_days[:20])
        positive_streak = 0
        for item in recent_days:
            if (item.total_net or 0) > 0:
                positive_streak += 1
            else:
                break
        streak = f"連{positive_streak}日回補" if positive_streak >= 2 else "無明顯連續回補"
        return InstitutionalMetrics(
            recent_days=recent_days[:5],
            foreign_5d=foreign_5d,
            investment_5d=investment_5d,
            dealer_5d=dealer_5d,
            total_5d=total_5d,
            total_10d=total_10d,
            total_20d=total_20d,
            streak=streak,
        )

    def fetch_news_metrics(self, symbol: str, name: str) -> NewsMetrics:
        query = f"{symbol} {name} 台股"
        url = (
            "https://news.google.com/rss/search?"
            + parse.urlencode(
                {
                    "q": query,
                    "hl": "zh-TW",
                    "gl": "TW",
                    "ceid": "TW:zh-Hant",
                }
            )
        )
        try:
            root = ET.fromstring(self.http.get_text(url))
        except Exception:
            return NewsMetrics(heat="無資料", sentiment="中性", score=0, items=[])

        items: list[NewsItem] = []
        score = 0
        for item in root.findall(".//item")[:5]:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            source = (item.findtext("source") or "Google News").strip()
            published = (item.findtext("pubDate") or "").strip()
            score += _headline_sentiment_score(title)
            items.append(NewsItem(title=title, link=link, source=source, published=published))

        heat = "高" if len(items) >= 5 else "中" if len(items) >= 3 else "低" if items else "無資料"
        sentiment = "偏多" if score >= 2 else "偏空" if score <= -2 else "中性"
        return NewsMetrics(heat=heat, sentiment=sentiment, score=score, items=items)

    def infer_themes(self, symbol: str, name: str, industry: str | None) -> tuple[str | None, list[str]]:
        manual = MANUAL_THEME_OVERRIDES.get(symbol)
        if manual:
            return manual.get("group"), manual.get("themes", [])

        haystack = " ".join(filter(None, [name, industry]))
        matched = [theme for theme, keywords in THEME_KEYWORDS.items() if any(word in haystack for word in keywords)]
        group = matched[0] if matched else industry
        return group, matched[:5]

    def peer_symbols(self, symbol: str, group_name: str | None) -> list[str]:
        manual = MANUAL_THEME_OVERRIDES.get(symbol)
        if manual:
            return manual.get("peers", [])[:3]
        if not group_name:
            return []
        peers: list[str] = []
        for key, value in MANUAL_THEME_OVERRIDES.items():
            if value.get("group") == group_name and key != symbol:
                peers.append(key)
        return peers[:3]

    @lru_cache(maxsize=8)
    def _fetch_company_profile_row(self, symbol: str, market_type: str) -> dict[str, str | None]:
        for row in self._load_mops_csv_rows("t187ap03", market_type):
            if row.get("公司代號", "").strip() == symbol:
                industry = row.get("產業別")
                if industry and industry.isdigit():
                    manual = MANUAL_THEME_OVERRIDES.get(symbol, {})
                    industry = manual.get("industry") or self._lookup_revenue_industry(symbol, market_type)
                return {
                    "name": row.get("公司簡稱") or row.get("公司名稱"),
                    "industry": industry,
                }
        return {"name": None, "industry": None}

    @lru_cache(maxsize=8)
    def _fetch_revenue_metrics(self, symbol: str, market_type: str) -> RevenueMetrics | None:
        latest: dict[str, str] | None = None
        latest_key = ""
        for row in self._load_mops_csv_rows("t187ap05", market_type):
            if row.get("公司代號", "").strip() != symbol:
                continue
            month_key = row.get("資料年月", "").strip()
            if month_key and month_key > latest_key:
                latest_key = month_key
                latest = row
        if latest:
            month_label = _normalize_revenue_month(latest.get("資料年月"))
            return RevenueMetrics(
                month_label=month_label,
                revenue=_safe_float(latest.get("營業收入-當月營收")),
                previous_revenue=_safe_float(latest.get("營業收入-上月營收")),
                last_year_revenue=_safe_float(latest.get("營業收入-去年當月營收")),
                mom=_safe_float(latest.get("營業收入-上月比較增減(%)")),
                yoy=_safe_float(latest.get("營業收入-去年同月增減(%)")),
                cumulative_revenue=_safe_float(latest.get("累計營業收入-當月累計營收")),
                cumulative_last_year_revenue=_safe_float(latest.get("累計營業收入-去年累計營收")),
                cumulative_yoy=_safe_float(latest.get("累計營業收入-前期比較增減(%)")),
                note=(latest.get("備註") or "").strip() or None,
            )
        return None

    @lru_cache(maxsize=8)
    def _lookup_revenue_industry(self, symbol: str, market_type: str) -> str | None:
        for row in self._load_mops_csv_rows("t187ap05", market_type):
            if row.get("公司代號", "").strip() == symbol:
                return row.get("產業別") or None
        return None

    @lru_cache(maxsize=8)
    def _load_mops_csv_rows(self, dataset: str, market_type: str) -> tuple[dict[str, str], ...]:
        suffix = "L" if market_type == "sii" else "O"
        text = self.http.get_text(f"https://mopsfin.twse.com.tw/opendata/{dataset}_{suffix}.csv")
        cleaned = text.lstrip("\ufeff").strip()
        if not cleaned:
            return ()
        reader = csv.DictReader(io.StringIO(cleaned))
        return tuple({(key or "").strip(): (value or "").strip() for key, value in row.items()} for row in reader)

    def _fetch_twse_valuation(self, symbol: str) -> ValuationMetrics:
        for offset in range(0, 10):
            target_day = date.today() - timedelta(days=offset)
            payload = self.http.get_json(
                "https://www.twse.com.tw/exchangeReport/BWIBBU_d",
                {
                    "response": "json",
                    "date": target_day.strftime("%Y%m%d"),
                    "selectType": "ALL",
                },
            )
            fields = payload.get("fields", [])
            for row in payload.get("data", []):
                if row and row[0] == symbol:
                    mapped = _map_row(fields, row)
                    return ValuationMetrics(
                        pe=_safe_float(mapped.get("本益比")),
                        pb=_safe_float(mapped.get("股價淨值比")),
                        dividend_yield=_safe_float(mapped.get("殖利率(%)")),
                    )
        return ValuationMetrics(pe=None, pb=None, dividend_yield=None)

    def _fetch_tpex_valuation(self, symbol: str) -> ValuationMetrics:
        for offset in range(0, 10):
            target_day = date.today() - timedelta(days=offset)
            with_value = self.http.get_text(
                "https://www.tpex.org.tw/web/stock/aftertrading/peratio_analysis/pera_result.php",
                params={
                    "l": "zh-tw",
                    "o": "htm",
                    "d": _roc_day_string(target_day),
                    "c": "",
                    "s": "0,asc",
                },
                headers={"Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/info/daily-pe.html"},
            )
            tables = _parse_html_tables(with_value)
            for table in tables:
                parsed = _lookup_row_by_headers(
                    table,
                    symbol,
                    code_headers=["股票代號", "代號"],
                    mapping={
                        "pe": ["本益比"],
                        "yield": ["殖利率(%)"],
                        "pb": ["股價淨值比"],
                    },
                )
                if parsed:
                    return ValuationMetrics(
                        pe=_safe_float(parsed.get("pe")),
                        pb=_safe_float(parsed.get("pb")),
                        dividend_yield=_safe_float(parsed.get("yield")),
                    )
        return ValuationMetrics(pe=None, pb=None, dividend_yield=None)

    def _fetch_institutional_day(self, symbol: str, market: str, trade_date: date) -> InstitutionalDay | None:
        return self._fetch_twse_institutional_day(symbol, trade_date) if market == "上市" else self._fetch_tpex_institutional_day(symbol, trade_date)

    def _fetch_twse_institutional_day(self, symbol: str, trade_date: date) -> InstitutionalDay | None:
        payload = self.http.get_json(
            "https://www.twse.com.tw/fund/T86",
            {
                "response": "json",
                "date": trade_date.strftime("%Y%m%d"),
                "selectType": "ALLBUT0999",
            },
        )
        fields = payload.get("fields", [])
        for row in payload.get("data", []):
            if row and row[0] == symbol:
                mapped = _map_row(fields, row)
                return InstitutionalDay(
                    trade_date=trade_date.isoformat(),
                    foreign_net=_safe_int(mapped.get("外陸資買賣超股數(不含外資自營商)")),
                    investment_net=_safe_int(mapped.get("投信買賣超股數")),
                    dealer_net=_safe_int(mapped.get("自營商買賣超股數")),
                    total_net=_safe_int(mapped.get("三大法人買賣超股數")),
                )
        return None

    def _fetch_tpex_institutional_day(self, symbol: str, trade_date: date) -> InstitutionalDay | None:
        html = self.http.get_text(
            "https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php",
            params={"l": "zh-tw", "o": "htm", "d": _roc_day_string(trade_date)},
            headers={"Referer": "https://www.tpex.org.tw/zh-tw/mainboard/trading/major-institutional/detail/day.html"},
        )
        tables = _parse_html_tables(html)
        for table in tables:
            parsed = _lookup_row_by_headers(
                table,
                symbol,
                code_headers=["代號", "股票代號"],
                mapping={
                    "foreign": ["外資及陸資淨買股數", "外資及陸資買賣超股數"],
                    "investment": ["投信淨買股數", "投信買賣超股數"],
                    "dealer": ["自營商淨買股數", "自營商買賣超股數"],
                    "total": ["三大法人買賣超股數", "三大法人買賣超"],
                },
            )
            if parsed:
                return InstitutionalDay(
                    trade_date=trade_date.isoformat(),
                    foreign_net=_safe_int(parsed.get("foreign")),
                    investment_net=_safe_int(parsed.get("investment")),
                    dealer_net=_safe_int(parsed.get("dealer")),
                    total_net=_safe_int(parsed.get("total")),
                )
        return None


def _headline_sentiment_score(title: str) -> int:
    score = 0
    for word in NEWS_POSITIVE_WORDS:
        if word in title:
            score += 1
    for word in NEWS_NEGATIVE_WORDS:
        if word in title:
            score -= 1
    return score


def _map_row(fields: list[str], row: list[str]) -> dict[str, str]:
    return {field: row[idx] for idx, field in enumerate(fields) if idx < len(row)}


def _lookup_row_by_headers(
    table: list[list[str]],
    symbol: str,
    *,
    code_headers: list[str],
    mapping: dict[str, list[str]],
) -> dict[str, str] | None:
    if len(table) < 2:
        return None
    header_index = None
    for idx, row in enumerate(table[:3]):
        if any(header in row for header in code_headers):
            header_index = idx
            break
    if header_index is None:
        return None

    headers = table[header_index]
    code_col = _find_header_index(headers, code_headers)
    if code_col is None:
        return None

    field_cols = {key: _find_header_index(headers, choices) for key, choices in mapping.items()}
    for row in table[header_index + 1 :]:
        if code_col < len(row) and row[code_col].strip() == symbol:
            result: dict[str, str] = {}
            for key, col in field_cols.items():
                result[key] = row[col].strip() if col is not None and col < len(row) else ""
            if "name" in result or "industry" in result or "revenue" in result or "pe" in result or "foreign" in result:
                return result
    return None


def _find_header_index(headers: list[str], choices: list[str]) -> int | None:
    for choice in choices:
        for idx, header in enumerate(headers):
            if choice in header:
                return idx
    return None


def _parse_html_tables(html: str) -> list[list[list[str]]]:
    parser = HtmlTableParser()
    parser.feed(html)
    return parser.tables


def _safe_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("%", "").strip()
    if cleaned in {"", "N/A", "--", "---"}:
        return None
    return float(cleaned)


def _safe_int(value: str | None) -> int | None:
    if value is None:
        return None
    cleaned = value.replace(",", "").replace("+", "").strip()
    if cleaned in {"", "N/A", "--", "---"}:
        return None
    return int(float(cleaned))


def _previous_month(value: date) -> date:
    if value.month == 1:
        return value.replace(year=value.year - 1, month=12)
    return value.replace(month=value.month - 1)


def _roc_day_string(value: date) -> str:
    return f"{value.year - 1911}/{value.month:02d}/{value.day:02d}"


def _normalize_revenue_month(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    if cleaned.isdigit():
        if len(cleaned) == 5:
            year = int(cleaned[:3]) + 1911
            return f"{year}-{cleaned[3:]}"
        if len(cleaned) == 6:
            return f"{cleaned[:4]}-{cleaned[4:]}"
    return cleaned


def _market_candidates(primary_market_type: str) -> tuple[str, str]:
    alternate = "otc" if primary_market_type == "sii" else "sii"
    return primary_market_type, alternate

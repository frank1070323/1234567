from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re

from .data_sources import (
    DailyPrice,
    DataSourceUnavailableError,
    TpexClient,
    TwseClient,
)
from .indicators import calculate_indicators
from .supplemental_sources import SupplementalDataService
from .taxonomy import TAG_COLORS


class InvalidSymbolError(Exception):
    pass


class NoDataError(Exception):
    pass


class SourceUnavailableError(Exception):
    pass


@dataclass(frozen=True)
class MarketHistory:
    market: str
    name: str
    prices: list[DailyPrice]


class StockAnalysisService:
    def __init__(
        self,
        twse_client: TwseClient | None = None,
        tpex_client: TpexClient | None = None,
        supplemental_service: SupplementalDataService | None = None,
        months_to_scan: int = 8,
    ):
        self.twse_client = twse_client or TwseClient()
        self.tpex_client = tpex_client or TpexClient()
        self.supplemental_service = supplemental_service or SupplementalDataService()
        self.months_to_scan = months_to_scan

    def analyze(
        self,
        symbol: str,
        cost_basis: float | None = None,
        target_price: float | None = None,
        stop_price: float | None = None,
    ) -> dict:
        symbol = symbol.strip().upper()
        if not _is_valid_symbol(symbol):
            raise InvalidSymbolError("股票代號不存在")

        history = self._load_history(symbol)
        if len(history.prices) < 130:
            raise NoDataError("當月無資料或可用日線不足，無法計算指標")

        indicators = calculate_indicators(history.prices)
        latest = history.prices[-1]
        prev = history.prices[-2]
        closes = [price.close_price for price in history.prices]
        volumes = [price.volume for price in history.prices]

        ma5 = _sma(closes, 5)
        ma10 = _sma(closes, 10)
        ma20 = _sma(closes, 20)
        ma60 = _sma(closes, 60)
        ma120 = _sma(closes, 120)
        vma5 = _sma(volumes, 5)
        vma20 = _sma(volumes, 20)
        atr14 = _atr(history.prices, 14)
        latest_atr = atr14[-1]
        support_resistance = _build_support_resistance(history.prices, latest.close_price)

        latest_k = indicators.k_values[-1]
        latest_d = indicators.d_values[-1]
        latest_dif = indicators.dif_values[-1]
        latest_dea = indicators.dea_values[-1]
        latest_osc = indicators.osc_values[-1]
        prev_osc = indicators.osc_values[-2]

        kd_signal = _detect_kd_signal(
            indicators.k_values[-2],
            indicators.d_values[-2],
            latest_k,
            latest_d,
        )
        macd_signal = _detect_macd_signal(
            indicators.dif_values[-2],
            indicators.dea_values[-2],
            latest_dif,
            latest_dea,
        )
        osc_sign = "正柱體" if latest_osc > 0 else "負柱體" if latest_osc < 0 else "零柱體"
        ma_alignment = ma5 > ma10 > ma20
        price_above_ma5 = latest.close_price > ma5[-1]
        ma60_trend = _direction(ma60[-1] - ma60[-2])
        ma120_trend = _direction(ma120[-1] - ma120[-2])
        kd_low_zone = latest_k < 30
        kd_turn_up = latest_k > indicators.k_values[-2]
        osc_flip_positive = prev_osc <= 0 < latest_osc
        osc_negative_shrinking = latest_osc < 0 and prev_osc < 0 and abs(latest_osc) < abs(prev_osc)
        dif_above_zero = latest_dif > 0
        volume_ratio_5 = latest.volume / vma5[-1] if vma5[-1] else 0
        volume_above_vma20 = latest.volume > vma20[-1]
        rolling_volume_up = len(volumes) >= 3 and volumes[-1] > volumes[-2] > volumes[-3]
        recent_high_20 = max(closes[-20:])
        no_volume_high = latest.close_price >= recent_high_20 and latest.volume < vma20[-1]
        volume_score = _volume_score(
            volume_ratio_5=volume_ratio_5,
            volume_above_vma20=volume_above_vma20,
            rolling_volume_up=rolling_volume_up,
        )
        volume_breakout = volume_score >= 2

        score_items = {
            "ma": (2 if price_above_ma5 else 0) + (2 if ma5[-1] > ma10[-1] else 0),
            "indicator": 3 if kd_signal == "黃金交叉" or osc_flip_positive or macd_signal == "黃金交叉" else 0,
            "volume": volume_score,
        }
        total_score = sum(score_items.values())
        recommendation = _recommendation(total_score)
        profile = self.supplemental_service.fetch_company_profile(symbol, history.market, history.name)
        revenue = self.supplemental_service.fetch_revenue_metrics(symbol, history.market)
        valuation = self.supplemental_service.fetch_valuation_metrics(symbol, history.market)
        institutional = self.supplemental_service.fetch_institutional_metrics(symbol, history.market)
        news = self.supplemental_service.fetch_news_metrics(symbol, profile.name)
        group_name, themes = self.supplemental_service.infer_themes(symbol, profile.name, profile.industry)
        peer_comparison = self._build_peer_comparison(symbol, group_name)
        cost_analysis = _build_cost_analysis(cost_basis, latest.close_price, ma5[-1], ma20[-1])
        risk_analysis = _build_risk_analysis(
            latest_close=latest.close_price,
            cost_basis=cost_basis,
            target_price=target_price,
            stop_price=stop_price,
            atr=latest_atr,
            support_resistance=support_resistance,
            ma5=ma5[-1],
            price_above_ma5=price_above_ma5,
        )
        color_tags = _build_color_tags(
            themes=themes,
            recommendation=recommendation,
            news_heat=news.heat,
            sentiment=news.sentiment,
            total_5d=institutional.total_5d,
            yoy=revenue.yoy,
            cost_analysis=cost_analysis,
            risk_analysis=risk_analysis,
        )
        narrative = _build_trade_narrative(
            latest_close=latest.close_price,
            price_above_ma5=price_above_ma5,
            ma_alignment=ma_alignment,
            ma60_trend=ma60_trend,
            ma120_trend=ma120_trend,
            latest_k=latest_k,
            kd_turn_up=kd_turn_up,
            kd_signal=kd_signal,
            latest_osc=latest_osc,
            prev_osc=prev_osc,
            macd_signal=macd_signal,
            latest_dif=latest_dif,
            volume_ratio_5=volume_ratio_5,
            volume_above_vma20=volume_above_vma20,
            rolling_volume_up=rolling_volume_up,
            no_volume_high=no_volume_high,
            total_score=total_score,
            recommendation=recommendation,
            revenue_yoy=revenue.yoy,
            chip_streak=institutional.streak,
            sentiment=news.sentiment,
        )

        return {
            "symbol": symbol,
            "name": profile.name,
            "market": history.market,
            "dataDate": latest.trade_date.isoformat(),
            "industry": profile.industry,
            "themeGroup": group_name,
            "themeTags": themes,
            "latestClose": round(latest.close_price, 2),
            "latestVolume": latest.volume,
            "k": round(latest_k, 2),
            "d": round(latest_d, 2),
            "dif": round(latest_dif, 2),
            "dea": round(latest_dea, 2),
            "osc": round(latest_osc, 2),
            "ma5": round(ma5[-1], 2),
            "ma10": round(ma10[-1], 2),
            "ma20": round(ma20[-1], 2),
            "ma60": round(ma60[-1], 2),
            "ma120": round(ma120[-1], 2),
            "vma5": round(vma5[-1], 2),
            "vma20": round(vma20[-1], 2),
            "kdDirection": _direction(latest_k - indicators.k_values[-2]),
            "kdCurve": _curve(indicators.k_values),
            "kdSignal": kd_signal,
            "macdDirection": _direction(latest_dif - indicators.dif_values[-2]),
            "macdCurve": _curve(indicators.dif_values),
            "macdZeroAxis": "零上" if latest_dif >= 0 else "零下",
            "macdSignal": macd_signal,
            "oscSign": osc_sign,
            "signalSummary": _build_signal_summary(kd_signal, latest_dif, latest_osc, prev.close_price, latest.close_price),
            "maAnalysis": {
                "priceAboveMa5": price_above_ma5,
                "bullishAlignment": ma_alignment,
                "ma60Trend": ma60_trend,
                "ma120Trend": ma120_trend,
                "score": score_items["ma"],
            },
            "kdAnalysis": {
                "isLowZone": kd_low_zone,
                "isTurningUp": kd_turn_up,
                "score": 3 if kd_signal == "黃金交叉" else 0,
            },
            "macdAnalysis": {
                "oscFlipPositive": osc_flip_positive,
                "oscNegativeShrinking": osc_negative_shrinking,
                "difAboveZero": dif_above_zero,
                "score": 3 if osc_flip_positive or macd_signal == "黃金交叉" else 0,
            },
            "volumeAnalysis": {
                "volumeRatio5": round(volume_ratio_5, 2),
                "volumeAboveVma20": volume_above_vma20,
                "isBreakout": volume_breakout,
                "rollingUp3d": rolling_volume_up,
                "noVolumeHigh": no_volume_high,
                "score": score_items["volume"],
            },
            "valuation": {
                "pe": valuation.pe,
                "pb": valuation.pb,
                "dividendYield": valuation.dividend_yield,
            },
            "revenue": {
                "monthLabel": revenue.month_label,
                "revenue": revenue.revenue,
                "previousRevenue": revenue.previous_revenue,
                "lastYearRevenue": revenue.last_year_revenue,
                "yoy": revenue.yoy,
                "mom": revenue.mom,
                "cumulativeRevenue": revenue.cumulative_revenue,
                "cumulativeLastYearRevenue": revenue.cumulative_last_year_revenue,
                "cumulativeYoy": revenue.cumulative_yoy,
                "note": revenue.note,
            },
            "institutional": {
                "foreign5d": institutional.foreign_5d,
                "investment5d": institutional.investment_5d,
                "dealer5d": institutional.dealer_5d,
                "total5d": institutional.total_5d,
                "total10d": institutional.total_10d,
                "total20d": institutional.total_20d,
                "streak": institutional.streak,
                "recentDays": [
                    {
                        "tradeDate": item.trade_date,
                        "foreignNet": item.foreign_net,
                        "investmentNet": item.investment_net,
                        "dealerNet": item.dealer_net,
                        "totalNet": item.total_net,
                    }
                    for item in institutional.recent_days
                ],
            },
            "news": {
                "heat": news.heat,
                "sentiment": news.sentiment,
                "score": news.score,
                "items": [
                    {
                        "title": item.title,
                        "link": item.link,
                        "source": item.source,
                        "published": item.published,
                    }
                    for item in news.items
                ],
            },
            "costAnalysis": cost_analysis,
            "riskAnalysis": risk_analysis,
            "chipFocus": _build_chip_focus(
                market=history.market,
                volumes=volumes,
                institutional=institutional,
            ),
            "peerComparison": peer_comparison,
            "colorTags": color_tags,
            "decision": {
                "score": total_score,
                "maxScore": 10,
                "recommendation": recommendation,
                "watchThreshold": 5,
                "entryThreshold": 7,
            },
            "chartSeries": _build_chart_series(history.prices, indicators, ma5, ma10, ma20, ma60, ma120, vma5, vma20),
            "tradeNarrative": narrative,
        }

    def _load_history(self, symbol: str) -> MarketHistory:
        errors: list[Exception] = []

        for market_name, client in (("上市", self.twse_client), ("上櫃", self.tpex_client)):
            try:
                history = self._collect_market_history(symbol, market_name, client)
            except DataSourceUnavailableError as exc:
                errors.append(exc)
                continue

            if history.prices:
                return history

        if errors and len(errors) == 2:
            raise SourceUnavailableError("來源暫時不可用")
        raise InvalidSymbolError("股票代號不存在")

    def _collect_market_history(self, symbol: str, market_name: str, client) -> MarketHistory:
        all_prices: dict[date, DailyPrice] = {}
        stock_name = ""
        saw_rows = False
        saw_source_error = False
        cursor = date.today().replace(day=1)

        for _ in range(self.months_to_scan):
            try:
                name, rows = client.fetch_month(symbol, cursor)
            except DataSourceUnavailableError:
                saw_source_error = True
                cursor = _previous_month(cursor)
                continue
            if name:
                stock_name = name
            if rows:
                saw_rows = True
                for row in rows:
                    all_prices[row.trade_date] = row
            cursor = _previous_month(cursor)

        ordered = sorted(all_prices.values(), key=lambda item: item.trade_date)
        if saw_source_error and not saw_rows:
            raise DataSourceUnavailableError("來源暫時不可用")
        if not saw_rows:
            return MarketHistory(market=market_name, name=stock_name or symbol, prices=[])
        return MarketHistory(market=market_name, name=stock_name or symbol, prices=ordered)

    def _build_peer_comparison(self, symbol: str, group_name: str | None) -> dict:
        peers = self.supplemental_service.peer_symbols(symbol, group_name)
        if not peers:
            return {"group": group_name, "leader": None, "members": []}

        members = []
        for peer_symbol in peers:
            try:
                history = self._load_history(peer_symbol)
                closes = [item.close_price for item in history.prices]
                score = 0
                if len(closes) >= 20:
                    score += 1 if closes[-1] > sum(closes[-5:]) / 5 else 0
                    score += 1 if closes[-1] > sum(closes[-20:]) / 20 else 0
                members.append(
                    {
                        "symbol": peer_symbol,
                        "name": history.name,
                        "market": history.market,
                        "strengthScore": score,
                        "latestClose": round(closes[-1], 2),
                    }
                )
            except Exception:
                continue

        members.sort(key=lambda item: item["strengthScore"], reverse=True)
        leader = members[0]["symbol"] if members else None
        return {"group": group_name, "leader": leader, "members": members[:4]}


def _is_valid_symbol(symbol: str) -> bool:
    return bool(re.fullmatch(r"(?=.*\d)[0-9A-Z]{4,6}", symbol))


def _previous_month(value: date) -> date:
    if value.month == 1:
        return value.replace(year=value.year - 1, month=12)
    return value.replace(month=value.month - 1)


def _direction(delta: float, epsilon: float = 0.01) -> str:
    if delta > epsilon:
        return "上行"
    if delta < -epsilon:
        return "下行"
    return "走平"


def _curve(series: list[float], epsilon: float = 0.05) -> str:
    if len(series) < 3:
        return "走平"
    slope_1 = series[-2] - series[-3]
    slope_2 = series[-1] - series[-2]
    change = slope_2 - slope_1
    if abs(change) <= epsilon and abs(slope_2) <= epsilon:
        return "走平"
    if change > epsilon:
        return "上彎"
    if change < -epsilon:
        return "下彎"
    return "走平"


def _detect_kd_signal(prev_k: float, prev_d: float, curr_k: float, curr_d: float) -> str:
    if prev_k <= prev_d and curr_k > curr_d:
        return "黃金交叉"
    if prev_k >= prev_d and curr_k < curr_d:
        return "死亡交叉"
    return "無"


def _detect_macd_signal(prev_dif: float, prev_dea: float, curr_dif: float, curr_dea: float) -> str:
    if prev_dif <= prev_dea and curr_dif > curr_dea:
        return "黃金交叉"
    if prev_dif >= prev_dea and curr_dif < curr_dea:
        return "死亡交叉"
    return "無"


def _sma(values: list[float], period: int) -> list[float]:
    result: list[float] = []
    window_sum = 0.0
    for idx, value in enumerate(values):
        window_sum += value
        if idx >= period:
            window_sum -= values[idx - period]
        divisor = min(idx + 1, period)
        result.append(window_sum / divisor)
    return result


def _volume_score(*, volume_ratio_5: float, volume_above_vma20: bool, rolling_volume_up: bool) -> int:
    if volume_ratio_5 >= 1.5 and volume_above_vma20 and rolling_volume_up:
        return 3
    if volume_ratio_5 >= 1.2 and volume_above_vma20:
        return 2
    if volume_ratio_5 >= 1.0 or volume_above_vma20:
        return 1
    return 0


def _atr(prices: list[DailyPrice], period: int) -> list[float]:
    true_ranges: list[float] = []
    for idx, price in enumerate(prices):
        if idx == 0:
            tr = price.high_price - price.low_price
        else:
            prev_close = prices[idx - 1].close_price
            tr = max(
                price.high_price - price.low_price,
                abs(price.high_price - prev_close),
                abs(price.low_price - prev_close),
            )
        true_ranges.append(tr)
    return _sma(true_ranges, period)


def _build_support_resistance(prices: list[DailyPrice], latest_close: float) -> dict:
    recent = prices[-60:]
    max_volume_candle = max(recent, key=lambda item: item.volume)
    bullish_candles = [item for item in recent if item.close_price > item.open_price]
    key_bullish = max(
        bullish_candles,
        key=lambda item: (item.close_price - item.open_price) * item.volume,
        default=max_volume_candle,
    )
    resistance = max(item.high_price for item in recent)
    supports = sorted({round(max_volume_candle.low_price, 2), round(key_bullish.low_price, 2)})
    below_close = [value for value in supports if value <= latest_close]
    primary_support = max(below_close) if below_close else min(supports, default=None)
    return {
        "primarySupport": round(primary_support, 2) if primary_support is not None else None,
        "volumeSupport": round(max_volume_candle.low_price, 2),
        "bullishCandleSupport": round(key_bullish.low_price, 2),
        "resistance": round(resistance, 2),
    }


def _suggest_entry_price(*, latest_close: float, ma5: float, primary_support: float | None, price_above_ma5: bool) -> dict:
    if price_above_ma5 and latest_close <= ma5 * 1.03:
        return {
            "price": latest_close,
            "label": "現價可觀察",
            "reason": "股價已站上 MA5，且離五日線不遠，可把現價視為第一進場參考。",
        }
    if price_above_ma5:
        return {
            "price": ma5,
            "label": "等回測 MA5",
            "reason": "股價已脫離五日線，較適合等回測 MA5 附近再評估進場。",
        }
    reference = primary_support or ma5
    return {
        "price": reference,
        "label": "待站回短撐",
        "reason": "目前尚未有效站回 MA5，建議先觀察短撐是否收復，再把該位置當進場參考。",
    }


def _recommendation(score: int) -> str:
    if score >= 7:
        return "建議進場"
    if score >= 5:
        return "進入觀察"
    return "暫不進場"


def _build_signal_summary(
    kd_signal: str,
    latest_dif: float,
    latest_osc: float,
    prev_close: float,
    latest_close: float,
) -> str:
    zero_axis = "零上" if latest_dif >= 0 else "零下"
    osc_sign = "正柱體" if latest_osc > 0 else "負柱體" if latest_osc < 0 else "零柱體"
    price_trend = "收盤走強" if latest_close > prev_close else "收盤轉弱" if latest_close < prev_close else "收盤持平"
    return f"KD {kd_signal}；MACD {zero_axis}、{osc_sign}；{price_trend}"


def _build_trade_narrative(
    *,
    latest_close: float,
    price_above_ma5: bool,
    ma_alignment: bool,
    ma60_trend: str,
    ma120_trend: str,
    latest_k: float,
    kd_turn_up: bool,
    kd_signal: str,
    latest_osc: float,
    prev_osc: float,
    macd_signal: str,
    latest_dif: float,
    volume_ratio_5: float,
    volume_above_vma20: bool,
    rolling_volume_up: bool = False,
    no_volume_high: bool = False,
    total_score: int,
    recommendation: str,
    revenue_yoy: float | None,
    chip_streak: str,
    sentiment: str,
) -> str:
    trend_part = (
        "股價站穩五日線，短中期均線維持多頭結構"
        if price_above_ma5 and ma_alignment
        else "均線結構尚未完全多頭共振"
    )

    long_part = (
        "季線與半年線同步提供長線支撐"
        if ma60_trend in {"上行", "走平"} and ma120_trend in {"上行", "走平"}
        else "長線均線保護仍不足"
    )

    if latest_k < 30 and (kd_turn_up or kd_signal == "黃金交叉"):
        kd_part = "KD 位於低檔區並完成向上轉折"
    elif kd_signal == "黃金交叉":
        kd_part = "KD 已出現黃金交叉"
    else:
        kd_part = "KD 尚未給出明確低檔攻擊訊號"

    if prev_osc <= 0 < latest_osc:
        macd_part = "MACD 柱狀體首日翻紅，動能切換明確"
    elif latest_osc < 0 and prev_osc < 0 and abs(latest_osc) < abs(prev_osc):
        macd_part = "MACD 綠柱縮短，空方力道正在衰退"
    elif macd_signal == "黃金交叉" and latest_dif > 0:
        macd_part = "DIF 在零軸上方黃金交叉，屬於強勢續攻型態"
    else:
        macd_part = "MACD 動能尚未完全翻多"

    if no_volume_high:
        volume_part = "股價雖創近期高點，但量能低於月均量，屬於無量過高，宜提防拉回"
    elif volume_ratio_5 >= 1.5 and volume_above_vma20 and rolling_volume_up:
        volume_part = f"成交量緩步放大且連三日增量，目前為五日均量的 {volume_ratio_5:.2f} 倍，屬於連續攻擊量"
    elif volume_ratio_5 >= 1.5 and volume_above_vma20:
        volume_part = f"成交量明顯放大至五日均量的 {volume_ratio_5:.2f} 倍，資金參與度充足"
    elif volume_ratio_5 >= 1.0:
        volume_part = f"成交量略高於短均量，約為五日均量的 {volume_ratio_5:.2f} 倍"
    else:
        volume_part = f"成交量仍偏保守，僅為五日均量的 {volume_ratio_5:.2f} 倍"

    revenue_part = (
        f"最新月營收年增 {revenue_yoy:.2f}%"
        if revenue_yoy is not None
        else "月營收資料暫缺"
    )

    return (
        f"目前收盤 {latest_close:.2f}。{trend_part}，{long_part}。"
        f"{kd_part}，{macd_part}。{volume_part}。"
        f"{revenue_part}；法人籌碼狀態為「{chip_streak}」；新聞情緒偏向「{sentiment}」。"
        f"綜合評分 {total_score}/10，建議判定為「{recommendation}」。"
    )


def _build_chart_series(prices, indicators, ma5, ma10, ma20, ma60, ma120, vma5, vma20):
    recent_prices = prices[-90:]
    start_idx = len(prices) - len(recent_prices)
    return {
        "dates": [item.trade_date.isoformat() for item in recent_prices],
        "opens": [round(item.open_price, 2) for item in recent_prices],
        "highs": [round(item.high_price, 2) for item in recent_prices],
        "lows": [round(item.low_price, 2) for item in recent_prices],
        "closes": [round(item.close_price, 2) for item in recent_prices],
        "volumes": [item.volume for item in recent_prices],
        "ma5": [round(value, 2) for value in ma5[start_idx:]],
        "ma10": [round(value, 2) for value in ma10[start_idx:]],
        "ma20": [round(value, 2) for value in ma20[start_idx:]],
        "ma60": [round(value, 2) for value in ma60[start_idx:]],
        "ma120": [round(value, 2) for value in ma120[start_idx:]],
        "ma5Volume": round(vma5[-1], 2),
        "ma20Volume": round(vma20[-1], 2),
        "dif": [round(value, 2) for value in indicators.dif_values[start_idx:]],
        "dea": [round(value, 2) for value in indicators.dea_values[start_idx:]],
        "osc": [round(value, 2) for value in indicators.osc_values[start_idx:]],
        "k": [round(value, 2) for value in indicators.k_values[start_idx:]],
        "d": [round(value, 2) for value in indicators.d_values[start_idx:]],
    }


def _build_cost_analysis(cost_basis: float | None, latest_close: float, ma5: float, ma20: float) -> dict:
    if cost_basis is None:
        return {
            "costBasis": None,
            "pnl": None,
            "pnlPercent": None,
            "status": "未輸入成本價",
            "suggestion": "可輸入自己的成本價，系統會補上損益與風險位置判讀。",
        }
    pnl = latest_close - cost_basis
    pnl_percent = (pnl / cost_basis) * 100 if cost_basis else None
    if latest_close > cost_basis and latest_close > ma5:
        status = "獲利且站穩短均"
        suggestion = "短線仍有優勢，可觀察五日線是否續守。"
    elif latest_close < cost_basis and latest_close < ma20:
        status = "跌破成本且弱於月線"
        suggestion = "若無量轉弱，宜控管風險並觀察月線支撐。"
    else:
        status = "成本附近震盪"
        suggestion = "可搭配量價與法人動向決定是否續抱或調節。"
    return {
        "costBasis": round(cost_basis, 2),
        "pnl": round(pnl, 2),
        "pnlPercent": round(pnl_percent, 2) if pnl_percent is not None else None,
        "status": status,
        "suggestion": suggestion,
    }


def _build_risk_analysis(
    *,
    latest_close: float,
    cost_basis: float | None,
    target_price: float | None,
    stop_price: float | None,
    atr: float,
    support_resistance: dict,
    ma5: float,
    price_above_ma5: bool,
) -> dict:
    suggested_entry = _suggest_entry_price(
        latest_close=latest_close,
        ma5=ma5,
        primary_support=support_resistance["primarySupport"],
        price_above_ma5=price_above_ma5,
    )
    entry_price = cost_basis if cost_basis is not None else suggested_entry["price"]
    atr_stop = max(entry_price - atr * 2, 0)
    reward = None
    risk = None
    ratio = None
    ratio_label = "未設定"
    note = "可輸入目標價與停損價，系統會自動估算預期損益比。"
    if target_price is not None and stop_price is not None:
        reward = target_price - entry_price
        risk = entry_price - stop_price
        if risk > 0:
            ratio = reward / risk
            ratio_label = "報酬風險比佳" if ratio >= 3 else "報酬風險比中等" if ratio >= 2 else "報酬風險比偏弱"
            note = f"以進場 {entry_price:.2f} 計，預期報酬 {reward:.2f}、風險 {risk:.2f}。"
        else:
            ratio_label = "停損價需低於進場價"
            note = "目前停損價不合理，需低於進場價才能正確計算。"
    primary_support = support_resistance["primarySupport"]
    if primary_support is not None and latest_close < primary_support:
        stance = "跌破主要支撐，風險升高"
    elif ratio is not None and ratio >= 3:
        stance = "風險報酬結構良好"
    else:
        stance = "先觀察支撐與停損距離"
    return {
        "entryReference": round(entry_price, 2),
        "suggestedEntryPrice": round(suggested_entry["price"], 2),
        "suggestedEntryLabel": suggested_entry["label"],
        "suggestedEntryReason": suggested_entry["reason"],
        "atr14": round(atr, 2),
        "atrStop": round(atr_stop, 2),
        "targetPrice": round(target_price, 2) if target_price is not None else None,
        "stopPrice": round(stop_price, 2) if stop_price is not None else None,
        "reward": round(reward, 2) if reward is not None else None,
        "risk": round(risk, 2) if risk is not None else None,
        "rewardRiskRatio": round(ratio, 2) if ratio is not None else None,
        "ratioLabel": ratio_label,
        "stance": stance,
        "note": note,
        "primarySupport": support_resistance["primarySupport"],
        "volumeSupport": support_resistance["volumeSupport"],
        "bullishCandleSupport": support_resistance["bullishCandleSupport"],
        "resistance": support_resistance["resistance"],
    }


def _build_chip_focus(*, market: str, volumes: list[int], institutional) -> dict:
    volume_5d = sum(volumes[-5:]) or 1
    volume_10d = sum(volumes[-10:]) or 1
    volume_20d = sum(volumes[-20:]) or 1
    concentration_5d = institutional.total_5d / volume_5d * 100
    concentration_10d = institutional.total_10d / volume_10d * 100
    concentration_20d = institutional.total_20d / volume_20d * 100
    broker_status = "官方分點資料需驗證碼，尚未自動串接"
    if market == "上櫃":
        broker_note = "TPEX 券商買賣頁面目前需 Turnstile 驗證，後端無法穩定自動查詢。"
    else:
        broker_note = "TWSE 買賣日報表查詢系統目前需驗證碼，後端無法穩定自動查詢。"
    if concentration_5d >= 2:
        concentration_view = "近 5 日法人集中度偏強"
    elif concentration_5d > 0:
        concentration_view = "近 5 日法人略偏回補"
    else:
        concentration_view = "近 5 日法人未見集中吸貨"
    return {
        "concentration5d": round(concentration_5d, 2),
        "concentration10d": round(concentration_10d, 2),
        "concentration20d": round(concentration_20d, 2),
        "concentrationView": concentration_view,
        "brokerStatus": broker_status,
        "brokerNote": broker_note,
    }


def _build_color_tags(*, themes, recommendation, news_heat, sentiment, total_5d, yoy, cost_analysis, risk_analysis):
    tags = []
    for theme in themes[:4]:
        tags.append({"label": theme, "tone": "violet", "category": "theme", "color": TAG_COLORS["theme"]})
    tags.append({"label": recommendation, "tone": "cyan", "category": "trend", "color": TAG_COLORS["trend"]})
    if yoy is not None:
        tags.append(
            {
                "label": f"營收YoY {yoy:.1f}%",
                "tone": "blue" if yoy >= 0 else "red",
                "category": "fundamental",
                "color": TAG_COLORS["fundamental"] if yoy >= 0 else TAG_COLORS["risk"],
            }
        )
    tags.append(
        {
            "label": f"新聞熱度 {news_heat}",
            "tone": "pink",
            "category": "news",
            "color": TAG_COLORS["news"],
        }
    )
    tags.append(
        {
            "label": f"情緒 {sentiment}",
            "tone": "green" if sentiment == "偏多" else "red" if sentiment == "偏空" else "amber",
            "category": "news",
            "color": TAG_COLORS["news"],
        }
    )
    tags.append(
        {
            "label": f"法人5日 {total_5d:+,}",
            "tone": "green" if total_5d > 0 else "red" if total_5d < 0 else "amber",
            "category": "chip",
            "color": TAG_COLORS["chip"],
        }
    )
    if cost_analysis["costBasis"] is not None:
        tags.append(
            {
                "label": cost_analysis["status"],
                "tone": "teal",
                "category": "cost",
                "color": TAG_COLORS["cost"],
            }
        )
    if risk_analysis["rewardRiskRatio"] is not None:
        tags.append(
            {
                "label": f"損益比 {risk_analysis['rewardRiskRatio']:.2f}",
                "tone": "green" if risk_analysis["rewardRiskRatio"] >= 3 else "amber" if risk_analysis["rewardRiskRatio"] >= 2 else "red",
                "category": "risk",
                "color": TAG_COLORS["risk"],
            }
        )
    return tags

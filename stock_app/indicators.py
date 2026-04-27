from __future__ import annotations

from dataclasses import dataclass

from .data_sources import DailyPrice


@dataclass(frozen=True)
class IndicatorSeries:
    k_values: list[float]
    d_values: list[float]
    dif_values: list[float]
    dea_values: list[float]
    osc_values: list[float]


def calculate_indicators(prices: list[DailyPrice]) -> IndicatorSeries:
    closes = [item.close_price for item in prices]
    k_values, d_values = _calculate_kd(prices, period=9)
    dif_values, dea_values, osc_values = _calculate_macd(closes, short_period=12, long_period=26, signal_period=9)
    return IndicatorSeries(
        k_values=k_values,
        d_values=d_values,
        dif_values=dif_values,
        dea_values=dea_values,
        osc_values=osc_values,
    )


def _calculate_kd(prices: list[DailyPrice], period: int) -> tuple[list[float], list[float]]:
    k_values: list[float] = []
    d_values: list[float] = []
    prev_k = 50.0
    prev_d = 50.0

    for idx in range(len(prices)):
        window = prices[max(0, idx - period + 1) : idx + 1]
        highest = max(item.high_price for item in window)
        lowest = min(item.low_price for item in window)
        close = prices[idx].close_price

        if highest == lowest:
            rsv = 50.0
        else:
            rsv = ((close - lowest) / (highest - lowest)) * 100

        curr_k = (2 / 3) * prev_k + (1 / 3) * rsv
        curr_d = (2 / 3) * prev_d + (1 / 3) * curr_k
        k_values.append(curr_k)
        d_values.append(curr_d)
        prev_k = curr_k
        prev_d = curr_d

    return k_values, d_values


def _calculate_macd(
    closes: list[float],
    short_period: int,
    long_period: int,
    signal_period: int,
) -> tuple[list[float], list[float], list[float]]:
    ema_short = _ema(closes, short_period)
    ema_long = _ema(closes, long_period)
    dif_values = [short - long for short, long in zip(ema_short, ema_long)]
    dea_values = _ema(dif_values, signal_period)
    osc_values = [dif - dea for dif, dea in zip(dif_values, dea_values)]
    return dif_values, dea_values, osc_values


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    multiplier = 2 / (period + 1)
    ema_values = [values[0]]
    for value in values[1:]:
        ema_values.append((value - ema_values[-1]) * multiplier + ema_values[-1])
    return ema_values

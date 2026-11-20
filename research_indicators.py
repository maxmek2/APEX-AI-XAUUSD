"""Research-only XAUUSD indicators with causal, completed-bar calculations.

These indicators are diagnostics/filters, not trade signals. Volume-weighted
calculations use broker tick-volume proxies and must not be described as
centralized exchange volume. All returned arrays align with input candles;
warm-up values are None. No future bars are read.
"""
from __future__ import annotations

from math import isfinite, log
from market_models import Candle


def _validate(candles: list[Candle], period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 2:
        raise ValueError("period must be an integer >= 2")
    previous = None
    for candle in candles:
        values = (candle.open, candle.high, candle.low, candle.close, candle.volume)
        if not all(isfinite(float(value)) for value in values):
            raise ValueError("candle values must be finite")
        if min(candle.open, candle.high, candle.low, candle.close) <= 0 or candle.volume < 0:
            raise ValueError("candle prices must be positive and volume non-negative")
        if candle.high < max(candle.open, candle.close, candle.low):
            raise ValueError("invalid candle high")
        if candle.low > min(candle.open, candle.close, candle.high):
            raise ValueError("invalid candle low")
        if previous is not None and candle.open_time <= previous:
            raise ValueError("candles must be chronological")
        previous = candle.open_time


def choppiness_index(candles: list[Candle], period: int = 14) -> list[float | None]:
    """CHOP = 100*log10(sum(TR,n)/(HH(n)-LL(n)))/log10(n)."""
    _validate(candles, period)
    out: list[float | None] = [None] * len(candles)
    tr: list[float] = []
    for i, c in enumerate(candles):
        prev_close = candles[i - 1].close if i else c.close
        tr.append(max(c.high - c.low, abs(c.high - prev_close), abs(c.low - prev_close)))
        if i + 1 < period:
            continue
        start = i + 1 - period
        total_tr = sum(tr[start:i + 1])
        highest = max(x.high for x in candles[start:i + 1])
        lowest = min(x.low for x in candles[start:i + 1])
        span = highest - lowest
        if span > 0 and total_tr > 0:
            out[i] = 100.0 * log(total_tr / span, 10) / log(period, 10)
    return out


def efficiency_ratio(candles: list[Candle], period: int = 10) -> list[float | None]:
    """Kaufman efficiency ratio, bounded [0,1], using close-to-close changes."""
    _validate(candles, period)
    out: list[float | None] = [None] * len(candles)
    for i in range(period, len(candles)):
        net = abs(candles[i].close - candles[i - period].close)
        path = sum(abs(candles[j].close - candles[j - 1].close)
                   for j in range(i - period + 1, i + 1))
        out[i] = net / path if path > 0 else 0.0
    return out


def kama(
    candles: list[Candle], er_period: int = 10,
    fast_period: int = 2, slow_period: int = 30,
) -> list[float | None]:
    """Kaufman adaptive moving average; first value seeds from close at ER warm-up."""
    _validate(candles, er_period)
    if (isinstance(fast_period, bool) or isinstance(slow_period, bool)
            or not isinstance(fast_period, int) or not isinstance(slow_period, int)
            or fast_period < 1 or slow_period <= fast_period):
        raise ValueError("require 1 <= fast_period < slow_period")
    er = efficiency_ratio(candles, er_period)
    out: list[float | None] = [None] * len(candles)
    if len(candles) <= er_period:
        return out
    fast_sc = 2.0 / (fast_period + 1)
    slow_sc = 2.0 / (slow_period + 1)
    previous = candles[er_period].close
    out[er_period] = previous
    for i in range(er_period + 1, len(candles)):
        ratio = er[i]
        assert ratio is not None
        smoothing = (ratio * (fast_sc - slow_sc) + slow_sc) ** 2
        previous += smoothing * (candles[i].close - previous)
        out[i] = previous
    return out


def realized_volatility(candles: list[Candle], period: int = 24) -> list[float | None]:
    """Rolling sample standard deviation of log returns (not annualized)."""
    _validate(candles, period)
    out: list[float | None] = [None] * len(candles)
    returns = [0.0] * len(candles)
    for i in range(1, len(candles)):
        returns[i] = log(candles[i].close / candles[i - 1].close)
    for i in range(period, len(candles)):
        window = returns[i - period + 1:i + 1]
        mean = sum(window) / period
        variance = sum((x - mean) ** 2 for x in window) / (period - 1)
        out[i] = variance ** 0.5
    return out


def session_vwap_zscore(
    candles: list[Candle], period: int = 50,
) -> tuple[list[float | None], list[float | None]]:
    """UTC-day anchored tick-volume VWAP and rolling close-minus-VWAP z-score.

    Returns (session_vwap, deviation_zscore). Zero tick volume or zero deviation
    variance produces None rather than a fabricated value.
    """
    _validate(candles, period)
    vwap: list[float | None] = [None] * len(candles)
    zscore: list[float | None] = [None] * len(candles)
    cumulative_pv = cumulative_volume = 0.0
    current_day = None
    deviations: list[float | None] = [None] * len(candles)
    for i, c in enumerate(candles):
        day = c.open_time // 86_400_000
        if day != current_day:
            current_day = day
            cumulative_pv = cumulative_volume = 0.0
        typical = (c.high + c.low + c.close) / 3.0
        cumulative_pv += typical * c.volume
        cumulative_volume += c.volume
        if cumulative_volume > 0:
            vwap[i] = cumulative_pv / cumulative_volume
            deviations[i] = c.close - vwap[i]
        if i + 1 >= period:
            window = [x for x in deviations[i + 1 - period:i + 1] if x is not None]
            if len(window) == period:
                mean = sum(window) / period
                variance = sum((x - mean) ** 2 for x in window) / period
                sd = variance ** 0.5
                if sd > 0 and deviations[i] is not None:
                    zscore[i] = (deviations[i] - mean) / sd
    return vwap, zscore


from __future__ import annotations

from collections import deque

from market_models import Candle


# ==========================================
# 1. EXPONENTIAL MOVING AVERAGE (EMA)
# ==========================================

def ema(
    values: list[float],
    period: int,
) -> list[float | None]:

    if period < 1:
        raise ValueError("EMA period must be positive")

    out: list[float | None] = [None] * len(values)

    if len(values) < period:
        return out

    previous = sum(values[:period]) / period
    out[period - 1] = previous

    alpha = 2 / (period + 1)

    for i in range(period, len(values)):
        previous = (
            alpha * values[i]
            + (1 - alpha) * previous
        )
        out[i] = previous

    return out


# ==========================================
# 2. RELATIVE STRENGTH INDEX (RSI)
# ==========================================

def rsi(
    values: list[float],
    period: int = 14,
) -> list[float | None]:

    if period < 1:
        raise ValueError("RSI period must be positive")

    out: list[float | None] = [None] * len(values)

    if len(values) <= period:
        return out

    gains = [
        max(values[i] - values[i - 1], 0.0)
        for i in range(1, len(values))
    ]

    losses = [
        max(values[i - 1] - values[i], 0.0)
        for i in range(1, len(values))
    ]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def calculate(gain: float, loss: float) -> float:

        if gain == 0 and loss == 0:
            return 50.0

        if loss == 0:
            return 100.0

        if gain == 0:
            return 0.0

        rs = gain / loss

        return 100 - (100 / (1 + rs))

    out[period] = calculate(avg_gain, avg_loss)

    for i in range(period + 1, len(values)):

        j = i - 1

        avg_gain = (
            avg_gain * (period - 1) + gains[j]
        ) / period

        avg_loss = (
            avg_loss * (period - 1) + losses[j]
        ) / period

        out[i] = calculate(avg_gain, avg_loss)

    return out


# ==========================================
# 3. AVERAGE TRUE RANGE (ATR)
# ==========================================

def atr(
    candles: list[Candle],
    period: int = 14,
) -> list[float | None]:

    if period < 1:
        raise ValueError("ATR period must be positive")

    out: list[float | None] = [None] * len(candles)

    if len(candles) <= period:
        return out

    true_ranges = []

    for i, candle in enumerate(candles):

        if i == 0:
            tr = candle.high - candle.low

        else:
            previous_close = candles[i - 1].close

            tr = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )

        true_ranges.append(tr)

    previous_atr = sum(
        true_ranges[1:period + 1]
    ) / period

    out[period] = previous_atr

    for i in range(period + 1, len(candles)):

        previous_atr = (
            previous_atr * (period - 1)
            + true_ranges[i]
        ) / period

        out[i] = previous_atr

    return out


# ==========================================
# 4. OPTIMIZED SWING HIGH / SWING LOW
# ==========================================

def swing_levels(
    candles: list[Candle],
    left: int = 3,
    right: int = 3,
):

    if left < 1 or right < 1:
        raise ValueError(
            "Swing left/right must be positive"
        )

    highs = []
    lows = []

    window_size = left + right + 1

    if len(candles) < window_size:
        return highs, lows

    max_queue = deque()
    min_queue = deque()

    # Initialize first window.
    for i in range(window_size):

        high = candles[i].high
        low = candles[i].low

        while (
            max_queue
            and candles[max_queue[-1]].high < high
        ):
            max_queue.pop()

        max_queue.append(i)

        while (
            min_queue
            and candles[min_queue[-1]].low > low
        ):
            min_queue.pop()

        min_queue.append(i)

    # Evaluate each centered swing window.
    for i in range(left, len(candles) - right):

        window_start = i - left

        # Remove indexes outside current window.
        while (
            max_queue
            and max_queue[0] < window_start
        ):
            max_queue.popleft()

        while (
            min_queue
            and min_queue[0] < window_start
        ):
            min_queue.popleft()

        current = candles[i]

        window_high = candles[max_queue[0]].high
        window_low = candles[min_queue[0]].low

        if current.high == window_high:
            highs.append((i, current.high))

        if current.low == window_low:
            lows.append((i, current.low))

        # Add next candle for next window.
        next_index = i + right + 1

        if next_index < len(candles):

            next_candle = candles[next_index]

            while (
                max_queue
                and candles[max_queue[-1]].high
                < next_candle.high
            ):
                max_queue.pop()

            max_queue.append(next_index)

            while (
                min_queue
                and candles[min_queue[-1]].low
                > next_candle.low
            ):
                min_queue.pop()

            min_queue.append(next_index)

    return highs, lows


# ==========================================
# 5. ICT LIQUIDITY SWEEP DETECTION
# ==========================================

def liquidity_sweeps(
    candles: list[Candle],
    lookback: int = 30,
    recent_bars: int = 3,
):

    if lookback < 1:
        raise ValueError("Lookback must be positive")

    if recent_bars < 1:
        raise ValueError(
            "recent_bars must be positive"
        )

    result = {
        "bullish": False,
        "bearish": False,
        "swept_high": None,
        "swept_low": None,
        "bullish_sweep_index": None,
        "bearish_sweep_index": None,
        "bullish_sweep_age": None,
        "bearish_sweep_age": None,
        "lookback": lookback,
        "recent_bars": recent_bars,
    }

    if len(candles) < lookback + 1:
        return result

    start_index = max(
        lookback,
        len(candles) - recent_bars,
    )

    # Examine only the most recent candidate candles.
    for i in range(start_index, len(candles)):

        candidate = candles[i]

        prior_start = i - lookback
        prior_end = i

        prior_high = max(
            candles[j].high
            for j in range(prior_start, prior_end)
        )

        prior_low = min(
            candles[j].low
            for j in range(prior_start, prior_end)
        )

        bearish_sweep = (
            candidate.high > prior_high
            and candidate.close < prior_high
        )

        bullish_sweep = (
            candidate.low < prior_low
            and candidate.close > prior_low
        )

        age = len(candles) - 1 - i

        if bullish_sweep:

            result["bullish"] = True
            result["swept_low"] = prior_low
            result["bullish_sweep_index"] = i
            result["bullish_sweep_age"] = age

        if bearish_sweep:

            result["bearish"] = True
            result["swept_high"] = prior_high
            result["bearish_sweep_index"] = i
            result["bearish_sweep_age"] = age

    return result


# ==========================================
# 6. OPTIMIZED FAIR VALUE GAP (FVG)
# ==========================================

def fair_value_gaps(
    candles: list[Candle],
    lookback: int = 30,
):

    result = {
        "bullish": None,
        "bearish": None,
        "bullish_details": None,
        "bearish_details": None,
        "bullish_filled": None,
        "bearish_filled": None,
    }

    if lookback < 1:
        raise ValueError(
            "FVG lookback must be positive"
        )

    if len(candles) < 3:
        return result

    length = len(candles)

    start = max(
        2,
        length - lookback,
    )

    # --------------------------------------
    # Precompute suffix minimum lows
    # and maximum highs.
    # --------------------------------------

    suffix_min_low = [0.0] * (length + 1)
    suffix_max_high = [0.0] * (length + 1)

    suffix_min_low[length] = float("inf")
    suffix_max_high[length] = float("-inf")

    for i in range(length - 1, -1, -1):

        suffix_min_low[i] = min(
            candles[i].low,
            suffix_min_low[i + 1],
        )

        suffix_max_high[i] = max(
            candles[i].high,
            suffix_max_high[i + 1],
        )

    # --------------------------------------
    # Search newest formations first.
    # --------------------------------------

    for i in range(length - 1, start - 1, -1):

        first = candles[i - 2]
        third = candles[i]

        # ----------------------------------
        # BULLISH FVG
        # ----------------------------------

        if result["bullish_details"] is None:

            if third.low > first.high:

                zone_low = first.high
                zone_high = third.low

                lowest_after = (
                    suffix_min_low[i + 1]
                    if i + 1 < length
                    else None
                )

                if lowest_after is None:
                    status = "UNTOUCHED"

                elif lowest_after <= zone_low:
                    status = "FULL"

                elif lowest_after < zone_high:
                    status = "PARTIAL"

                else:
                    status = "UNTOUCHED"

                details = {
                    "zone_low": zone_low,
                    "zone_high": zone_high,
                    "formation_index": i,
                    "status": status,
                    "mitigation_price": lowest_after,
                }

                if status == "FULL":

                    result["bullish_filled"] = details

                else:

                    result["bullish"] = (
                        zone_low,
                        zone_high,
                    )

                    result["bullish_details"] = details

        # ----------------------------------
        # BEARISH FVG
        # ----------------------------------

        if result["bearish_details"] is None:

            if third.high < first.low:

                zone_low = third.high
                zone_high = first.low

                highest_after = (
                    suffix_max_high[i + 1]
                    if i + 1 < length
                    else None
                )

                if highest_after is None:
                    status = "UNTOUCHED"

                elif highest_after >= zone_high:
                    status = "FULL"

                elif highest_after > zone_low:
                    status = "PARTIAL"

                else:
                    status = "UNTOUCHED"

                details = {
                    "zone_low": zone_low,
                    "zone_high": zone_high,
                    "formation_index": i,
                    "status": status,
                    "mitigation_price": highest_after,
                }

                if status == "FULL":

                    result["bearish_filled"] = details

                else:

                    result["bearish"] = (
                        zone_low,
                        zone_high,
                    )

                    result["bearish_details"] = details

        if (
            result["bullish_details"] is not None
            and result["bearish_details"] is not None
        ):
            break

    return result


# ==========================================
# 7. APPROXIMATE VOLUME PROFILE
# ==========================================

def volume_profile(
    candles: list[Candle],
    bins: int = 48,
    value_area: float = 0.70,
):

    if not candles:
        return {
            "poc": None,
            "vah": None,
            "val": None,
            "approximate": True,
        }

    if bins < 1:
        raise ValueError(
            "Volume Profile bins must be positive"
        )

    if not 0 < value_area <= 1:
        raise ValueError(
            "Value area must be between 0 and 1"
        )

    lowest = min(c.low for c in candles)
    highest = max(c.high for c in candles)

    if highest <= lowest:

        return {
            "poc": lowest,
            "vah": highest,
            "val": lowest,
            "approximate": True,
        }

    step = (highest - lowest) / bins

    histogram = [0.0] * bins

    for candle in candles:

        start = max(
            0,
            min(
                bins - 1,
                int((candle.low - lowest) / step),
            ),
        )

        end = max(
            0,
            min(
                bins - 1,
                int((candle.high - lowest) / step),
            ),
        )

        count = end - start + 1

        volume_per_bin = candle.volume / count

        for j in range(start, end + 1):
            histogram[j] += volume_per_bin

    poc_index = max(
        range(bins),
        key=lambda i: histogram[i],
    )

    target_volume = sum(histogram) * value_area

    total_volume = histogram[poc_index]

    left = poc_index
    right = poc_index

    while (
        total_volume < target_volume
        and (left > 0 or right < bins - 1)
    ):

        left_volume = (
            histogram[left - 1]
            if left > 0 else -1
        )

        right_volume = (
            histogram[right + 1]
            if right < bins - 1 else -1
        )

        if right_volume > left_volume:

            right += 1
            total_volume += histogram[right]

        else:

            left -= 1
            total_volume += histogram[left]

    poc = lowest + (poc_index + 0.5) * step

    val = lowest + left * step

    vah = lowest + (right + 1) * step

    return {
        "poc": poc,
        "vah": vah,
        "val": val,
        "approximate": True,
    }

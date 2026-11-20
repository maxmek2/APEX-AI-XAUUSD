
from __future__ import annotations

import math

from market_models import Candle
from indicators import (
    ema,
    rsi,
    atr,
    swing_levels,
    liquidity_sweeps,
    fair_value_gaps,
    volume_profile,
)


# ==========================================
# APEX AI STAGE 11B-3.1
# ==========================================

STRATEGY_VERSION = "STAGE_11B_3_1_ICT_SCALPING"

ATR_MULTIPLIER = 1.5
RISK_REWARD = 2.0
MIN_ATR = 0.000001

MIN_SIGNAL_SCORE = 65
MIN_DISPLACEMENT_ATR = 0.6
MIN_FVG_SIZE_ATR = 0.05
MIN_REJECTION_WICK_RATIO = 0.20

SWING_LEFT = 3
SWING_RIGHT = 3

ICT_LOOKBACK = 30
SWEEP_RECENT_BARS = 5
MAX_SWEEP_FVG_GAP = 6

SIGNAL_WEIGHTS = {
    "trend": 15,
    "liquidity": 20,
    "fvg": 20,
    "structure": 15,
    "momentum": 10,
    "price_position": 10,
    "displacement": 10,
    "rejection": 0,
}


# ==========================================
# 1. VALIDATION
# ==========================================

def valid_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


# ==========================================
# 2. DISPLACEMENT DETECTION
# ==========================================

def displacement_check(
    candle: Candle,
    atr_value: float,
    bullish: bool,
) -> dict:

    result = {
        "valid": False,
        "body_atr": 0.0,
        "body_size": 0.0,
        "direction": None,
    }

    if not valid_number(atr_value) or atr_value <= 0:
        return result

    body_size = abs(candle.close - candle.open)
    body_atr = body_size / atr_value

    is_bullish = candle.close > candle.open
    is_bearish = candle.close < candle.open

    direction_valid = (
        is_bullish if bullish else is_bearish
    )

    result.update({
        "valid": (
            direction_valid
            and body_atr >= MIN_DISPLACEMENT_ATR
        ),
        "body_atr": body_atr,
        "body_size": body_size,
        "direction": (
            "bullish" if is_bullish
            else "bearish" if is_bearish
            else "neutral"
        ),
    })

    return result


# ==========================================
# 3. SWEEP QUALITY
# ==========================================

def sweep_quality(
    candles: list[Candle],
    sweep_index: int | None,
    bullish: bool,
) -> dict:

    result = {
        "valid": False,
        "wick_ratio": 0.0,
        "candle_index": sweep_index,
    }

    if (
        not isinstance(sweep_index, int)
        or isinstance(sweep_index, bool)
        or not 0 <= sweep_index < len(candles)
    ):
        return result

    candle = candles[sweep_index]
    candle_range = candle.high - candle.low

    if candle_range <= 0:
        return result

    wick = (
        min(candle.open, candle.close) - candle.low
        if bullish
        else candle.high - max(candle.open, candle.close)
    )

    ratio = max(0.0, wick / candle_range)

    result.update({
        "valid": ratio >= MIN_REJECTION_WICK_RATIO,
        "wick_ratio": ratio,
    })

    return result


# ==========================================
# 4. FVG QUALITY
# ==========================================

def fvg_quality(
    candles: list[Candle],
    details: dict | None,
    atr_values: list[float | None],
    bullish: bool,
) -> dict:

    result = {
        "valid": False,
        "zone_size": 0.0,
        "zone_size_atr": 0.0,
        "displacement": None,
        "status": None,
        "formation_index": None,
        "displacement_index": None,
        "formation_atr": None,
    }

    if not details:
        return result

    low = details.get("zone_low")
    high = details.get("zone_high")
    idx = details.get("formation_index")

    if not (
        valid_number(low)
        and valid_number(high)
        and isinstance(idx, int)
        and not isinstance(idx, bool)
    ):
        return result

    # Three-candle FVG:
    # Candle 1 = first candle
    # Candle 2 = displacement candle
    # Candle 3 = FVG confirmation candle

    displacement_idx = idx - 1

    if (
        displacement_idx < 0
        or idx >= len(candles)
        or displacement_idx >= len(atr_values)
    ):
        return result

    atr_at_displacement = atr_values[displacement_idx]

    if (
        not valid_number(atr_at_displacement)
        or atr_at_displacement <= MIN_ATR
    ):
        return result

    size = high - low

    if size <= 0:
        return result

    size_atr = size / atr_at_displacement

    displacement = displacement_check(
        candles[displacement_idx],
        atr_at_displacement,
        bullish,
    )

    status = details.get("status")

    valid = (
        size_atr >= MIN_FVG_SIZE_ATR
        and displacement["valid"]
        and status in ("UNTOUCHED", "PARTIAL")
    )

    result.update({
        "valid": valid,
        "zone_size": size,
        "zone_size_atr": size_atr,
        "displacement": displacement,
        "status": status,
        "formation_index": idx,
        "displacement_index": displacement_idx,
        "formation_atr": atr_at_displacement,
    })

    return result


# ==========================================
# 5. MARKET STRUCTURE
# ==========================================

def market_structure(
    candles: list[Candle],
    highs: list[tuple[int, float]],
    lows: list[tuple[int, float]],
) -> dict:

    result = {
        "bullish_bos": False,
        "bearish_bos": False,
        "bullish_choch": False,
        "bearish_choch": False,
        "bullish_fresh_break": False,
        "bearish_fresh_break": False,
        "latest_swing_high": None,
        "latest_swing_low": None,
        "structure_bias": "neutral",
        "previous_structure_bias": "neutral",
        "break_level": None,
    }

    if len(candles) < 2:
        return result

    last = candles[-1]
    previous = candles[-2]

    swing_high = highs[-1][1] if highs else None
    swing_low = lows[-1][1] if lows else None

    result["latest_swing_high"] = swing_high
    result["latest_swing_low"] = swing_low

    prior_bias = "neutral"

    if len(highs) >= 2 and len(lows) >= 2:

        hh = highs[-1][1] > highs[-2][1]
        hl = lows[-1][1] > lows[-2][1]

        lh = highs[-1][1] < highs[-2][1]
        ll = lows[-1][1] < lows[-2][1]

        if hh and hl:
            prior_bias = "bullish"

        elif lh and ll:
            prior_bias = "bearish"

    result["previous_structure_bias"] = prior_bias

    bull_break = (
        swing_high is not None
        and previous.close <= swing_high
        and last.close > swing_high
    )

    bear_break = (
        swing_low is not None
        and previous.close >= swing_low
        and last.close < swing_low
    )

    result["bullish_fresh_break"] = bull_break
    result["bearish_fresh_break"] = bear_break

    if bull_break:

        result["break_level"] = swing_high

        result[
            "bullish_choch"
            if prior_bias == "bearish"
            else "bullish_bos"
        ] = True

        result["structure_bias"] = "bullish"

    elif bear_break:

        result["break_level"] = swing_low

        result[
            "bearish_choch"
            if prior_bias == "bullish"
            else "bearish_bos"
        ] = True

        result["structure_bias"] = "bearish"

    else:
        result["structure_bias"] = prior_bias

    return result


# ==========================================
# 6. SEQUENCE FVG
# ==========================================

def find_sequence_fvg(
    candles: list[Candle],
    sweep_index: int | None,
    bullish: bool,
) -> dict | None:

    if (
        not isinstance(sweep_index, int)
        or isinstance(sweep_index, bool)
        or not 0 <= sweep_index < len(candles)
    ):
        return None

    start = max(2, sweep_index + 1)

    end = min(
        len(candles) - 1,
        sweep_index + MAX_SWEEP_FVG_GAP,
    )

    found = []

    for i in range(start, end + 1):

        first = candles[i - 2]
        third = candles[i]

        if bullish:

            if third.low <= first.high:
                continue

            zone_low = first.high
            zone_high = third.low

            later = [
                c.low for c in candles[i + 1:]
            ]

            if any(v <= zone_low for v in later):
                status = "FULL"

            elif any(v < zone_high for v in later):
                status = "PARTIAL"

            else:
                status = "UNTOUCHED"

        else:

            if third.high >= first.low:
                continue

            zone_low = third.high
            zone_high = first.low

            later = [
                c.high for c in candles[i + 1:]
            ]

            if any(v >= zone_high for v in later):
                status = "FULL"

            elif any(v > zone_low for v in later):
                status = "PARTIAL"

            else:
                status = "UNTOUCHED"

        if status in ("UNTOUCHED", "PARTIAL"):

            found.append({
                "zone_low": zone_low,
                "zone_high": zone_high,
                "formation_index": i,
                "status": status,
            })

    return found[-1] if found else None


# ==========================================
# 7. SWEEP + FVG RELATIONSHIP
# ==========================================

def sweep_fvg_relationship(
    sweep_index: int | None,
    fvg_details: dict | None,
) -> dict:

    result = {
        "available": False,
        "gap_bars": None,
        "within_max_gap": False,
        "correct_sequence": False,
        "maximum_gap_bars": MAX_SWEEP_FVG_GAP,
    }

    if not fvg_details:
        return result

    idx = fvg_details.get("formation_index")

    if (
        not isinstance(sweep_index, int)
        or isinstance(sweep_index, bool)
        or not isinstance(idx, int)
        or isinstance(idx, bool)
    ):
        return result

    gap = idx - sweep_index

    result.update({
        "available": True,
        "gap_bars": gap,
        "within_max_gap": (
            1 <= gap <= MAX_SWEEP_FVG_GAP
        ),
        "correct_sequence": gap > 0,
    })

    return result


# ==========================================
# 8. FIND VALID SWEEP + FVG SETUP
# ==========================================

def find_valid_sweep_setup(
    candles: list[Candle],
    sweep_indices: list[int],
    atr_values: list[float | None],
    bullish: bool,
) -> dict:

    latest_valid_sweep = None
    latest_sweep_quality = None

    for sweep_index in reversed(sweep_indices):

        quality = sweep_quality(
            candles,
            sweep_index,
            bullish,
        )

        if not quality["valid"]:
            continue

        if latest_valid_sweep is None:
            latest_valid_sweep = sweep_index
            latest_sweep_quality = quality

        fvg = find_sequence_fvg(
            candles,
            sweep_index,
            bullish,
        )

        if not fvg:
            continue

        fvg_result = fvg_quality(
            candles,
            fvg,
            atr_values,
            bullish,
        )

        relationship = sweep_fvg_relationship(
            sweep_index,
            fvg,
        )

        if (
            fvg_result["valid"]
            and relationship["within_max_gap"]
            and relationship["correct_sequence"]
        ):

            return {
                "sweep_index": sweep_index,
                "sweep_quality": quality,
                "fvg": fvg,
                "fvg_quality": fvg_result,
                "relationship": relationship,
                "sequence_valid": True,
            }

    return {
        "sweep_index": latest_valid_sweep,
        "sweep_quality": latest_sweep_quality or {
            "valid": False,
            "wick_ratio": 0.0,
            "candle_index": None,
        },
        "fvg": None,
        "fvg_quality": fvg_quality(
            candles,
            None,
            atr_values,
            bullish,
        ),
        "relationship": sweep_fvg_relationship(
            latest_valid_sweep,
            None,
        ),
        "sequence_valid": False,
    }


# ==========================================
# 9. MAIN ANALYSIS ENGINE
# ==========================================

def analyze(
    candles: list[Candle],
    symbol: str,
    market: str,
    timeframe: str = "5m",
    include_volume_profile: bool = True,
    indicator_values: dict | None = None,
) -> dict:

    last_candle = candles[-1] if candles else None

    base = {
        "symbol": symbol,
        "market": market,
        "timeframe": timeframe,
        "candle_count": len(candles),
        "last_candle_open_time": (
            last_candle.open_time if last_candle else None
        ),
        "last_candle_close_time": (
            last_candle.close_time if last_candle else None
        ),
        "last_close": (
            last_candle.close if last_candle else None
        ),
        "execution": "DISABLED",
        "risk_status": "NOT_EVALUATED",
        "real_orders_enabled": False,
        "strategy_version": STRATEGY_VERSION,
    }

    if len(candles) < 60:
        return {
            **base,
            "status": "NO_TRADE",
            "reason": "insufficient_history",
        }

    closes = [c.close for c in candles]

    if indicator_values is None:

        e20 = ema(closes, 20)
        e50 = ema(closes, 50)

        rs = rsi(closes, 14)
        ats = atr(candles, 14)

        e20_now = e20[-1]
        e50_now = e50[-1]
        rsi_now = rs[-1]
        atr_now = ats[-1]

        atr_values = ats

    else:

        e20_now = indicator_values.get("ema20")
        e50_now = indicator_values.get("ema50")
        rsi_now = indicator_values.get("rsi14")
        atr_now = indicator_values.get("atr14")

        supplied = indicator_values.get("atr_values")

        atr_values = (
            supplied
            if isinstance(supplied, list)
            and len(supplied) == len(candles)
            else atr(candles, 14)
        )

    if any(
        not valid_number(v)
        for v in (
            e20_now,
            e50_now,
            rsi_now,
            atr_now,
        )
    ):
        return {
            **base,
            "status": "NO_TRADE",
            "reason": "indicator_data_incomplete",
        }

    if atr_now <= MIN_ATR:
        return {
            **base,
            "status": "NO_TRADE",
            "reason": "invalid_atr",
        }

    last = candles[-1]

    bias = (
        "bullish"
        if e20_now > e50_now
        else "bearish"
        if e20_now < e50_now
        else "neutral"
    )

    # Liquidity sweeps
    sweeps = liquidity_sweeps(
        candles,
        lookback=ICT_LOOKBACK,
        recent_bars=SWEEP_RECENT_BARS,
    )

    bull_setup = find_valid_sweep_setup(
        candles,
        sweeps.get("bullish_sweep_indices", []),
        atr_values,
        True,
    )

    bear_setup = find_valid_sweep_setup(
        candles,
        sweeps.get("bearish_sweep_indices", []),
        atr_values,
        False,
    )

    bull_sweep_q = bull_setup["sweep_quality"]
    bear_sweep_q = bear_setup["sweep_quality"]

    bull_sweep = bull_sweep_q["valid"]
    bear_sweep = bear_sweep_q["valid"]

    bull_seq_fvg = bull_setup["fvg"]
    bear_seq_fvg = bear_setup["fvg"]

    bull_fvg_q = bull_setup["fvg_quality"]
    bear_fvg_q = bear_setup["fvg_quality"]

    bull_fvg = bull_fvg_q["valid"]
    bear_fvg = bear_fvg_q["valid"]

    sweeps["bullish_sweep_index"] = bull_setup["sweep_index"]
    sweeps["bearish_sweep_index"] = bear_setup["sweep_index"]

    sweeps["bullish"] = bull_sweep
    sweeps["bearish"] = bear_sweep

    sweeps["bullish_sweep_age"] = (
        len(candles) - 1 - bull_setup["sweep_index"]
        if bull_setup["sweep_index"] is not None
        else None
    )

    sweeps["bearish_sweep_age"] = (
        len(candles) - 1 - bear_setup["sweep_index"]
        if bear_setup["sweep_index"] is not None
        else None
    )

    bull_pair = bull_setup["relationship"]
    bear_pair = bear_setup["relationship"]

    bull_sequence = (
        bull_sweep
        and bull_fvg
        and bull_setup["sequence_valid"]
    )

    bear_sequence = (
        bear_sweep
        and bear_fvg
        and bear_setup["sequence_valid"]
    )

    # Market structure
    highs, lows = swing_levels(
        candles,
        left=SWING_LEFT,
        right=SWING_RIGHT,
    )

    structure = market_structure(
        candles,
        highs,
        lows,
    )

    bull_structure = (
        structure["bullish_bos"]
        or structure["bullish_choch"]
    )

    bear_structure = (
        structure["bearish_bos"]
        or structure["bearish_choch"]
    )

    # Volume profile
    vp = (
        volume_profile(candles[-100:])
        if include_volume_profile
        else None
    )

    # Momentum and price position
    bull_rsi = 50 <= rsi_now <= 70
    bear_rsi = 30 <= rsi_now <= 50

    above = last.close > e20_now
    below = last.close < e20_now

    bull_disp = displacement_check(
        last,
        atr_now,
        True,
    )

    bear_disp = displacement_check(
        last,
        atr_now,
        False,
    )

    # Confirmation checks
    buy_checks = {
        "ema_bullish": bias == "bullish",
        "liquidity_sweep": bull_sweep,
        "bullish_fvg": bull_fvg,
        "ict_sweep_fvg_sequence": bull_sequence,
        "rsi_valid": bull_rsi,
        "price_above_ema20": above,
        "bullish_structure": bull_structure,
        "bullish_displacement": bull_disp["valid"],
        "bullish_rejection": bull_sweep_q["valid"],
    }

    sell_checks = {
        "ema_bearish": bias == "bearish",
        "liquidity_sweep": bear_sweep,
        "bearish_fvg": bear_fvg,
        "ict_sweep_fvg_sequence": bear_sequence,
        "rsi_valid": bear_rsi,
        "price_below_ema20": below,
        "bearish_structure": bear_structure,
        "bearish_displacement": bear_disp["valid"],
        "bearish_rejection": bear_sweep_q["valid"],
    }

    # Signal scoring
    def score(checks: dict, direction: str) -> int:

        total = 0

        if checks["ema_" + direction]:
            total += SIGNAL_WEIGHTS["trend"]

        if checks["liquidity_sweep"]:
            total += SIGNAL_WEIGHTS["liquidity"]

        fvg_key = (
            "bullish_fvg"
            if direction == "bullish"
            else "bearish_fvg"
        )

        if checks[fvg_key]:
            total += SIGNAL_WEIGHTS["fvg"]

        structure_key = (
            "bullish_structure"
            if direction == "bullish"
            else "bearish_structure"
        )

        if checks[structure_key]:
            total += SIGNAL_WEIGHTS["structure"]

        if checks["rsi_valid"]:
            total += SIGNAL_WEIGHTS["momentum"]

        position_key = (
            "price_above_ema20"
            if direction == "bullish"
            else "price_below_ema20"
        )

        if checks[position_key]:
            total += SIGNAL_WEIGHTS["price_position"]

        displacement_key = (
            "bullish_displacement"
            if direction == "bullish"
            else "bearish_displacement"
        )

        if checks[displacement_key]:
            total += SIGNAL_WEIGHTS["displacement"]

        return total

    buy_score = score(buy_checks, "bullish")
    sell_score = score(sell_checks, "bearish")

    buy_mandatory = (
        buy_checks["ema_bullish"]
        and above
        and bull_sequence
        and (
            bull_structure
            or bull_disp["valid"]
        )
    )

    sell_mandatory = (
        sell_checks["ema_bearish"]
        and below
        and bear_sequence
        and (
            bear_structure
            or bear_disp["valid"]
        )
    )

    buy = (
        buy_mandatory
        and buy_score >= MIN_SIGNAL_SCORE
    )

    sell = (
        sell_mandatory
        and sell_score >= MIN_SIGNAL_SCORE
    )

    if buy and not sell:

        signal = "BUY_CANDIDATE"
        grade = "STRONG_BUY"
        confirmations = buy_checks

    elif sell and not buy:

        signal = "SELL_CANDIDATE"
        grade = "STRONG_SELL"
        confirmations = sell_checks

    else:

        signal = "NO_TRADE"
        grade = "NO_TRADE"

        confirmations = (
            buy_checks
            if buy_score >= sell_score
            else sell_checks
        )

    # Stop loss and take profit
    entry = last.close
    stop_loss = None
    take_profit = None

    stop_distance = atr_now * ATR_MULTIPLIER

    if signal == "BUY_CANDIDATE":

        swing_low = structure["latest_swing_low"]

        stop_loss = (
            min(
                entry - stop_distance,
                swing_low - atr_now * 0.1,
            )
            if swing_low is not None
            else entry - stop_distance
        )

        risk = entry - stop_loss

        if risk > 0:
            take_profit = (
                entry + risk * RISK_REWARD
            )
        else:
            signal = "NO_TRADE"
            grade = "NO_TRADE"
            stop_loss = None

    elif signal == "SELL_CANDIDATE":

        swing_high = structure["latest_swing_high"]

        stop_loss = (
            max(
                entry + stop_distance,
                swing_high + atr_now * 0.1,
            )
            if swing_high is not None
            else entry + stop_distance
        )

        risk = stop_loss - entry

        if risk > 0:
            take_profit = (
                entry - risk * RISK_REWARD
            )
        else:
            signal = "NO_TRADE"
            grade = "NO_TRADE"
            stop_loss = None

    # Diagnostics
    diagnostics = {
        "buy": {
            "score": buy_score,
            "total": 100,
            "minimum_score": MIN_SIGNAL_SCORE,
            "passed": buy,
            "mandatory_conditions_passed": buy_mandatory,
            "checks": buy_checks,
            "failed_checks": [
                k for k, v in buy_checks.items() if not v
            ],
        },
        "sell": {
            "score": sell_score,
            "total": 100,
            "minimum_score": MIN_SIGNAL_SCORE,
            "passed": sell,
            "mandatory_conditions_passed": sell_mandatory,
            "checks": sell_checks,
            "failed_checks": [
                k for k, v in sell_checks.items() if not v
            ],
        },
    }

    return {
        **base,

        "status": signal,
        "signal_grade": grade,

        "reason": (
            "Stage 11B-3.1 ICT scalping conditions passed"
            if signal != "NO_TRADE"
            else "Stage 11B-3.1 ICT confluence conditions incomplete"
        ),

        "bias_ema20_50": bias,

        "ema20": e20_now,
        "ema50": e50_now,
        "rsi14": rsi_now,
        "atr14": atr_now,

        "liquidity_sweep": {
            **sweeps,
            "bullish_quality": bull_sweep_q,
            "bearish_quality": bear_sweep_q,
        },

        "latest_fvg": {
            "bullish_sequence_details": bull_seq_fvg,
            "bearish_sequence_details": bear_seq_fvg,
            "bullish_quality": bull_fvg_q,
            "bearish_quality": bear_fvg_q,
            "bullish_sweep_fvg_relationship": bull_pair,
            "bearish_sweep_fvg_relationship": bear_pair,
        },

        "market_structure": structure,

        "displacement": {
            "bullish": bull_disp,
            "bearish": bear_disp,
        },

        "volume_profile": vp,

        "latest_swing_high": (
            highs[-1][1] if highs else None
        ),

        "latest_swing_low": (
            lows[-1][1] if lows else None
        ),

        "confirmations": confirmations,

        "confirmation_score": max(
            buy_score,
            sell_score,
        ),

        "confirmation_total": 100,
        "minimum_signal_score": MIN_SIGNAL_SCORE,
        "signal_weights": SIGNAL_WEIGHTS,

        "signal_diagnostics": diagnostics,

        "ict_sequence": {
            "bullish_valid": bull_sequence,
            "bearish_valid": bear_sequence,
            "maximum_sweep_fvg_gap": MAX_SWEEP_FVG_GAP,
            "bullish_setup": bull_setup,
            "bearish_setup": bear_setup,
        },

        "provisional_stop_loss": stop_loss,
        "provisional_take_profit": take_profit,

        "risk_reward_target": (
            RISK_REWARD
            if signal != "NO_TRADE"
            else None
        ),

        "risk_status": "NOT_EVALUATED",
        "execution": "DISABLED",
        "real_orders_enabled": False,
    }

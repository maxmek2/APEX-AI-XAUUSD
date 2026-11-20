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
# APEX AI STAGE 11B-3.2
# ==========================================

STRATEGY_VERSION = "STAGE_3_8_BEARISH_FVG_DEEP_DIAGNOSTICS"

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
        "size_passed": False,
        "displacement_passed": False,
        "mitigation_passed": False,
        "failure_reasons": [],
    }

    if not details:
        result["failure_reasons"] = ["no_fvg_details"]
        return result

    low = details.get("zone_low")
    high = details.get("zone_high")
    idx = details.get("formation_index")

    if not (
        valid_number(low)
        and valid_number(high)
        and isinstance(idx, int)
        and not isinstance(idx, bool)
        and 0 <= idx < len(candles)
    ):
        result["failure_reasons"] = ["invalid_fvg_details"]
        return result

    # In a three-candle FVG, the middle candle is the displacement candle.
    displacement_idx = idx - 1

    if displacement_idx < 0 or displacement_idx >= len(atr_values):
        result["failure_reasons"] = ["invalid_displacement_index"]
        return result

    atr_at_displacement = atr_values[displacement_idx]

    if not valid_number(atr_at_displacement) or atr_at_displacement <= MIN_ATR:
        result["failure_reasons"] = ["invalid_atr_at_displacement"]
        return result

    size = high - low
    if size <= 0:
        result["failure_reasons"] = ["invalid_fvg_zone_size"]
        return result

    size_atr = size / atr_at_displacement
    size_passed = size_atr >= MIN_FVG_SIZE_ATR

    displacement = displacement_check(
        candles[displacement_idx],
        atr_at_displacement,
        bullish,
    )

    status = details.get("status")
    mitigation_passed = status in ("UNTOUCHED", "PARTIAL")
    displacement_passed = displacement["valid"]

    failures = []
    if not size_passed:
        failures.append("fvg_too_small")
    if not displacement_passed:
        failures.append("displacement_failed")
    if not mitigation_passed:
        failures.append("fvg_fully_mitigated")

    result.update({
        "valid": size_passed and displacement_passed and mitigation_passed,
        "zone_size": size,
        "zone_size_atr": size_atr,
        "displacement": displacement,
        "status": status,
        "formation_index": idx,
        "displacement_index": displacement_idx,
        "formation_atr": atr_at_displacement,
        "size_passed": size_passed,
        "displacement_passed": displacement_passed,
        "mitigation_passed": mitigation_passed,
        "failure_reasons": failures,
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

def find_sequence_fvgs(
    candles: list[Candle],
    sweep_index: int | None,
    bullish: bool,
) -> list[dict]:
    """Return every FVG formed after a sweep within the configured gap.

    Includes fully mitigated zones so diagnostics can explain why a
    candidate was rejected. Results are newest first.
    """

    if (
        not isinstance(sweep_index, int)
        or isinstance(sweep_index, bool)
        or not 0 <= sweep_index < len(candles)
    ):
        return []

    start = max(2, sweep_index + 1)
    end = min(len(candles) - 1, sweep_index + MAX_SWEEP_FVG_GAP)
    found = []

    for i in range(end, start - 1, -1):
        first = candles[i - 2]
        third = candles[i]

        if bullish:
            if third.low <= first.high:
                continue
            zone_low, zone_high = first.high, third.low
            later_values = [c.low for c in candles[i + 1:]]
            if any(value <= zone_low for value in later_values):
                status = "FULL"
            elif any(value < zone_high for value in later_values):
                status = "PARTIAL"
            else:
                status = "UNTOUCHED"
        else:
            if third.high >= first.low:
                continue
            zone_low, zone_high = third.high, first.low
            later_values = [c.high for c in candles[i + 1:]]
            if any(value >= zone_high for value in later_values):
                status = "FULL"
            elif any(value > zone_low for value in later_values):
                status = "PARTIAL"
            else:
                status = "UNTOUCHED"

        found.append({
            "zone_low": zone_low,
            "zone_high": zone_high,
            "formation_index": i,
            "status": status,
        })

    return found


def find_sequence_fvg(
    candles: list[Candle],
    sweep_index: int | None,
    bullish: bool,
) -> dict | None:
    """Compatibility helper returning the newest FVG after a sweep."""
    found = find_sequence_fvgs(candles, sweep_index, bullish)
    return found[0] if found else None


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

    stats = {
        "sweeps_seen": len(sweep_indices),
        "sweeps_passed_wick_quality": 0,
        "fvg_zones_found": 0,
        "fvg_fully_mitigated": 0,
        "fvg_failed_size": 0,
        "fvg_failed_displacement": 0,
        "fvg_invalid_atr": 0,
        "fvg_passed_quality": 0,
        "valid_sequences": 0,
        "fvg_candidate_stage_counts": {
            "candidate_detected": 0,
            "size_passed": 0,
            "displacement_passed": 0,
            "mitigation_passed": 0,
            "quality_passed": 0,
        },
        "fvg_failure_reason_counts": {},
    }

    candidate_samples = []
    latest_valid_sweep = None
    latest_sweep_quality = None

    for sweep_index in reversed(sweep_indices):
        quality = sweep_quality(candles, sweep_index, bullish)
        if not quality["valid"]:
            continue

        stats["sweeps_passed_wick_quality"] += 1

        if latest_valid_sweep is None:
            latest_valid_sweep = sweep_index
            latest_sweep_quality = quality

        fvgs = find_sequence_fvgs(candles, sweep_index, bullish)
        stats["fvg_zones_found"] += len(fvgs)

        for fvg in fvgs:
            fvg_result = fvg_quality(candles, fvg, atr_values, bullish)
            relationship = sweep_fvg_relationship(sweep_index, fvg)
            stages = stats["fvg_candidate_stage_counts"]
            stages["candidate_detected"] += 1
            if fvg_result.get("size_passed"):
                stages["size_passed"] += 1
            if fvg_result.get("displacement_passed"):
                stages["displacement_passed"] += 1
            if fvg_result.get("mitigation_passed"):
                stages["mitigation_passed"] += 1
            if fvg_result.get("valid"):
                stages["quality_passed"] += 1
            for failure_reason in fvg_result.get("failure_reasons", []):
                _increment = stats["fvg_failure_reason_counts"]
                _increment[failure_reason] = _increment.get(failure_reason, 0) + 1
            if len(candidate_samples) < 100:
                candidate_samples.append({
                    "sweep_index": sweep_index,
                    "sweep_quality": quality,
                    "fvg": dict(fvg),
                    "fvg_quality": fvg_result,
                    "relationship": relationship,
                })

            if fvg_result["status"] == "FULL":
                stats["fvg_fully_mitigated"] += 1
            if "fvg_too_small" in fvg_result["failure_reasons"]:
                stats["fvg_failed_size"] += 1
            if "displacement_failed" in fvg_result["failure_reasons"]:
                stats["fvg_failed_displacement"] += 1
            if any(reason.startswith("invalid_") for reason in fvg_result["failure_reasons"]):
                stats["fvg_invalid_atr"] += 1

            if (
                fvg_result["valid"]
                and relationship["within_max_gap"]
                and relationship["correct_sequence"]
            ):
                stats["fvg_passed_quality"] += 1
                stats["valid_sequences"] += 1
                return {
                    "sweep_index": sweep_index,
                    "sweep_quality": quality,
                    "fvg": fvg,
                    "fvg_quality": fvg_result,
                    "relationship": relationship,
                    "sequence_valid": True,
                    "diagnostics": stats,
                    "fvg_candidate_samples": candidate_samples,
                }

    return {
        "sweep_index": latest_valid_sweep,
        "sweep_quality": latest_sweep_quality or {
            "valid": False,
            "wick_ratio": 0.0,
            "candle_index": None,
        },
        "fvg": None,
        "fvg_quality": fvg_quality(candles, None, atr_values, bullish),
        "relationship": sweep_fvg_relationship(latest_valid_sweep, None),
        "sequence_valid": False,
        "diagnostics": stats,
        "fvg_candidate_samples": candidate_samples,
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
        not valid_number(value)
        for value in (
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

    # Liquidity sweeps.
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

    # Market structure.
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

    # Volume profile.
    vp = (
        volume_profile(candles[-100:])
        if include_volume_profile
        else None
    )

    # Momentum and price position.
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

    # Confirmation checks.
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

    # Signal scoring.
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

    # Stop loss and take profit.
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

    # Stage 3.9: explain each mandatory gate without changing signal rules.
    buy_mandatory_components = {
        "ema_bullish": bool(buy_checks["ema_bullish"]),
        "price_above_ema20": bool(above),
        "valid_sweep_fvg_sequence": bool(bull_sequence),
        "structure_or_latest_displacement": bool(
            bull_structure or bull_disp["valid"]
        ),
        "structure_component": bool(bull_structure),
        "latest_candle_displacement_component": bool(bull_disp["valid"]),
    }
    sell_mandatory_components = {
        "ema_bearish": bool(sell_checks["ema_bearish"]),
        "price_below_ema20": bool(below),
        "valid_sweep_fvg_sequence": bool(bear_sequence),
        "structure_or_latest_displacement": bool(
            bear_structure or bear_disp["valid"]
        ),
        "structure_component": bool(bear_structure),
        "latest_candle_displacement_component": bool(bear_disp["valid"]),
    }

    def mandatory_gate_status(components: dict) -> dict:
        failed = [key for key, value in components.items() if not value]
        return {
            "passed": not failed,
            "components": components,
            "failed_components": failed,
            "logic": "EMA AND price_position AND valid_sweep_FVG_sequence AND (structure OR latest_candle_displacement)",
            "diagnostic_only": True,
        }

    market_context = {
        "ema20": e20_now,
        "ema50": e50_now,
        "ema_bias": bias,
        "last_close": last.close,
        "rsi14": rsi_now,
        "atr14": atr_now,
        "structure_bias": structure.get("structure_bias"),
        "previous_structure_bias": structure.get("previous_structure_bias"),
        "latest_swing_high": structure.get("latest_swing_high"),
        "latest_swing_low": structure.get("latest_swing_low"),
        "break_level": structure.get("break_level"),
        "bullish_fresh_break": structure.get("bullish_fresh_break"),
        "bearish_fresh_break": structure.get("bearish_fresh_break"),
        "above_ema20": bool(above),
        "below_ema20": bool(below),
    }

    # Diagnostics.
    diagnostics = {
        "buy": {
            "score": buy_score,
            "total": 100,
            "minimum_score": MIN_SIGNAL_SCORE,
            "passed": buy,
            "mandatory_conditions_passed": buy_mandatory,
            "checks": buy_checks,
            "failed_checks": [
                key for key, value in buy_checks.items() if not value
            ],
            "mandatory_gate_detail": mandatory_gate_status(buy_mandatory_components),
            "market_context": market_context,
            "latest_candle_displacement": bull_disp,
            "fvg_displacement": bull_fvg_q.get("displacement"),
        },
        "sell": {
            "score": sell_score,
            "total": 100,
            "minimum_score": MIN_SIGNAL_SCORE,
            "passed": sell,
            "mandatory_conditions_passed": sell_mandatory,
            "checks": sell_checks,
            "failed_checks": [
                key for key, value in sell_checks.items() if not value
            ],
            "mandatory_gate_detail": mandatory_gate_status(sell_mandatory_components),
            "market_context": market_context,
            "latest_candle_displacement": bear_disp,
            "fvg_displacement": bear_fvg_q.get("displacement"),
        },
    }

    return {
        **base,

        "status": signal,
        "signal_grade": grade,

        "reason": (
            "Stage 11B-3.3 ICT scalping conditions passed"
            if signal != "NO_TRADE"
            else "Stage 11B-3.3 ICT confluence conditions incomplete"
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

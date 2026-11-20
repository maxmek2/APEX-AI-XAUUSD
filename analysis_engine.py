from __future__ import annotations

import math

from market_models import Candle
from indicators import ema, rsi, atr, swing_levels, liquidity_sweeps, fair_value_gaps, volume_profile

# APEX AI STAGE 11B-3.1
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
    "trend": 15, "liquidity": 20, "fvg": 20, "structure": 15,
    "momentum": 10, "price_position": 10, "displacement": 10,
    "rejection": 0,
}


def valid_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def displacement_check(candle: Candle, atr_value: float, bullish: bool) -> dict:
    result = {"valid": False, "body_atr": 0.0, "body_size": 0.0, "direction": None}
    if not valid_number(atr_value) or atr_value <= 0:
        return result
    body_size = abs(candle.close - candle.open)
    body_atr = body_size / atr_value
    is_bullish = candle.close > candle.open
    is_bearish = candle.close < candle.open
    direction_valid = is_bullish if bullish else is_bearish
    result.update({
        "valid": direction_valid and body_atr >= MIN_DISPLACEMENT_ATR,
        "body_atr": body_atr,
        "body_size": body_size,
        "direction": "bullish" if is_bullish else "bearish" if is_bearish else "neutral",
    })
    return result


def sweep_quality(candles: list[Candle], sweep_index: int | None, bullish: bool) -> dict:
    result = {"valid": False, "wick_ratio": 0.0, "candle_index": sweep_index}
    if (not isinstance(sweep_index, int) or isinstance(sweep_index, bool)
            or not 0 <= sweep_index < len(candles)):
        return result
    candle = candles[sweep_index]
    candle_range = candle.high - candle.low
    if candle_range <= 0:
        return result
    wick = (min(candle.open, candle.close) - candle.low) if bullish else (
        candle.high - max(candle.open, candle.close)
    )
    ratio = max(0.0, wick / candle_range)
    result.update({"valid": ratio >= MIN_REJECTION_WICK_RATIO, "wick_ratio": ratio})
    return result


def fvg_quality(candles: list[Candle], details: dict | None,
                atr_values: list[float | None], bullish: bool) -> dict:
    result = {
        "valid": False, "zone_size": 0.0, "zone_size_atr": 0.0,
        "displacement": None, "status": None, "formation_index": None,
        "formation_atr": None,
    }
    if not details:
        return result
    low, high = details.get("zone_low"), details.get("zone_high")
    idx = details.get("formation_index")
    if not (valid_number(low) and valid_number(high)
            and isinstance(idx, int) and not isinstance(idx, bool)):
        return result
    if not 0 <= idx < len(candles) or idx >= len(atr_values):
        return result
    atr_at_formation = atr_values[idx]
    if not valid_number(atr_at_formation) or atr_at_formation <= MIN_ATR:
        return result
    size = high - low
    if size <= 0:
        return result
    size_atr = size / atr_at_formation
    displacement = displacement_check(candles[idx], atr_at_formation, bullish)
    status = details.get("status")
    valid = (size_atr >= MIN_FVG_SIZE_ATR and displacement["valid"]
             and status in ("UNTOUCHED", "PARTIAL"))
    result.update({
        "valid": valid, "zone_size": size, "zone_size_atr": size_atr,
        "displacement": displacement, "status": status,
        "formation_index": idx, "formation_atr": atr_at_formation,
    })
    return result


def market_structure(candles: list[Candle], highs: list[tuple[int, float]],
                     lows: list[tuple[int, float]]) -> dict:
    result = {
        "bullish_bos": False, "bearish_bos": False,
        "bullish_choch": False, "bearish_choch": False,
        "bullish_fresh_break": False, "bearish_fresh_break": False,
        "latest_swing_high": None, "latest_swing_low": None,
        "structure_bias": "neutral", "previous_structure_bias": "neutral",
        "break_level": None,
    }
    if len(candles) < 2:
        return result
    last, previous = candles[-1], candles[-2]
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

    bull_break = (swing_high is not None and previous.close <= swing_high
                  and last.close > swing_high)
    bear_break = (swing_low is not None and previous.close >= swing_low
                  and last.close < swing_low)
    result["bullish_fresh_break"] = bull_break
    result["bearish_fresh_break"] = bear_break
    if bull_break:
        result["break_level"] = swing_high
        result["bullish_choch" if prior_bias == "bearish" else "bullish_bos"] = True
        result["structure_bias"] = "bullish"
    elif bear_break:
        result["break_level"] = swing_low
        result["bearish_choch" if prior_bias == "bullish" else "bearish_bos"] = True
        result["structure_bias"] = "bearish"
    else:
        result["structure_bias"] = prior_bias
    return result


def find_sequence_fvg(candles: list[Candle], sweep_index: int | None,
                      bullish: bool) -> dict | None:
    """Find the latest unfilled/partially filled FVG formed 1..6 bars after sweep."""
    if (not isinstance(sweep_index, int) or isinstance(sweep_index, bool)
            or not 0 <= sweep_index < len(candles)):
        return None

    start = max(2, sweep_index + 1)
    end = min(len(candles) - 1, sweep_index + MAX_SWEEP_FVG_GAP)
    found = []
    for i in range(start, end + 1):
        first, third = candles[i - 2], candles[i]
        if bullish:
            if third.low <= first.high:
                continue
            zone_low, zone_high = first.high, third.low
            later = [c.low for c in candles[i + 1:]]
            if any(v <= zone_low for v in later):
                status = "FULL"
            elif any(v < zone_high for v in later):
                status = "PARTIAL"
            else:
                status = "UNTOUCHED"
        else:
            if third.high >= first.low:
                continue
            zone_low, zone_high = third.high, first.low
            later = [c.high for c in candles[i + 1:]]
            if any(v >= zone_high for v in later):
                status = "FULL"
            elif any(v > zone_low for v in later):
                status = "PARTIAL"
            else:
                status = "UNTOUCHED"
        if status in ("UNTOUCHED", "PARTIAL"):
            found.append({
                "zone_low": zone_low, "zone_high": zone_high,
                "formation_index": i, "status": status,
            })
    return found[-1] if found else None


def sweep_fvg_relationship(sweep_index: int | None,
                           fvg_details: dict | None) -> dict:
    result = {
        "available": False, "gap_bars": None, "within_max_gap": False,
        "correct_sequence": False, "maximum_gap_bars": MAX_SWEEP_FVG_GAP,
    }
    if not fvg_details:
        return result
    idx = fvg_details.get("formation_index")
    if (not isinstance(sweep_index, int) or isinstance(sweep_index, bool)
            or not isinstance(idx, int) or isinstance(idx, bool)):
        return result
    gap = idx - sweep_index
    result.update({
        "available": True, "gap_bars": gap,
        "within_max_gap": 1 <= gap <= MAX_SWEEP_FVG_GAP,
        "correct_sequence": gap > 0,
    })
    return result


def analyze(candles: list[Candle], symbol: str, market: str,
            timeframe: str = "5m", include_volume_profile: bool = True,
            indicator_values: dict | None = None) -> dict:
    last_candle = candles[-1] if candles else None
    base = {
        "symbol": symbol, "market": market, "timeframe": timeframe,
        "candle_count": len(candles),
        "last_candle_open_time": last_candle.open_time if last_candle else None,
        "last_candle_close_time": last_candle.close_time if last_candle else None,
        "last_close": last_candle.close if last_candle else None,
        "execution": "DISABLED", "risk_status": "NOT_EVALUATED",
        "real_orders_enabled": False, "strategy_version": STRATEGY_VERSION,
    }
    if len(candles) < 60:
        return {**base, "status": "NO_TRADE", "reason": "insufficient_history"}

    closes = [c.close for c in candles]
    if indicator_values is None:
        e20, e50 = ema(closes, 20), ema(closes, 50)
        rs, ats = rsi(closes, 14), atr(candles, 14)
        e20_now, e50_now, rsi_now, atr_now = e20[-1], e50[-1], rs[-1], ats[-1]
        atr_values = ats
    else:
        e20_now = indicator_values.get("ema20")
        e50_now = indicator_values.get("ema50")
        rsi_now = indicator_values.get("rsi14")
        atr_now = indicator_values.get("atr14")
        supplied = indicator_values.get("atr_values")
        atr_values = supplied if isinstance(supplied, list) and len(supplied) == len(candles) else atr(candles, 14)

    if any(not valid_number(v) for v in (e20_now, e50_now, rsi_now, atr_now)):
        return {**base, "status": "NO_TRADE", "reason": "indicator_data_incomplete"}
    if atr_now <= MIN_ATR:
        return {**base, "status": "NO_TRADE", "reason": "invalid_atr"}

    last = candles[-1]
    bias = "bullish" if e20_now > e50_now else "bearish" if e20_now < e50_now else "neutral"

    sweeps = liquidity_sweeps(candles, lookback=ICT_LOOKBACK,
                              recent_bars=SWEEP_RECENT_BARS)
    bull_sweep_q = sweep_quality(candles, sweeps.get("bullish_sweep_index"), True)
    bear_sweep_q = sweep_quality(candles, sweeps.get("bearish_sweep_index"), False)
    bull_sweep = bool(sweeps.get("bullish")) and bull_sweep_q["valid"]
    bear_sweep = bool(sweeps.get("bearish")) and bear_sweep_q["valid"]

    gaps = fair_value_gaps(candles, lookback=ICT_LOOKBACK)
    bull_seq_fvg = find_sequence_fvg(candles, sweeps.get("bullish_sweep_index"), True)
    bear_seq_fvg = find_sequence_fvg(candles, sweeps.get("bearish_sweep_index"), False)
    bull_fvg_q = fvg_quality(candles, bull_seq_fvg, atr_values, True)
    bear_fvg_q = fvg_quality(candles, bear_seq_fvg, atr_values, False)
    bull_fvg, bear_fvg = bull_fvg_q["valid"], bear_fvg_q["valid"]

    highs, lows = swing_levels(candles, left=SWING_LEFT, right=SWING_RIGHT)
    structure = market_structure(candles, highs, lows)
    bull_structure = structure["bullish_bos"] or structure["bullish_choch"]
    bear_structure = structure["bearish_bos"] or structure["bearish_choch"]

    vp = volume_profile(candles[-100:]) if include_volume_profile else None
    bull_rsi, bear_rsi = 50 <= rsi_now <= 70, 30 <= rsi_now <= 50
    above, below = last.close > e20_now, last.close < e20_now
    bull_disp = displacement_check(last, atr_now, True)
    bear_disp = displacement_check(last, atr_now, False)

    bull_pair = sweep_fvg_relationship(sweeps.get("bullish_sweep_index"), bull_seq_fvg)
    bear_pair = sweep_fvg_relationship(sweeps.get("bearish_sweep_index"), bear_seq_fvg)
    bull_sequence = bull_sweep and bull_fvg and bull_pair["within_max_gap"] and bull_pair["correct_sequence"]
    bear_sequence = bear_sweep and bear_fvg and bear_pair["within_max_gap"] and bear_pair["correct_sequence"]

    buy_checks = {
        "ema_bullish": bias == "bullish", "liquidity_sweep": bull_sweep,
        "bullish_fvg": bull_fvg, "ict_sweep_fvg_sequence": bull_sequence,
        "rsi_valid": bull_rsi, "price_above_ema20": above,
        "bullish_structure": bull_structure, "bullish_displacement": bull_disp["valid"],
        "bullish_rejection": bull_sweep_q["valid"],
    }
    sell_checks = {
        "ema_bearish": bias == "bearish", "liquidity_sweep": bear_sweep,
        "bearish_fvg": bear_fvg, "ict_sweep_fvg_sequence": bear_sequence,
        "rsi_valid": bear_rsi, "price_below_ema20": below,
        "bearish_structure": bear_structure, "bearish_displacement": bear_disp["valid"],
        "bearish_rejection": bear_sweep_q["valid"],
    }

    def score(checks: dict, direction: str) -> int:
        total = 0
        if checks["ema_" + direction]:
            total += SIGNAL_WEIGHTS["trend"]
        if checks["liquidity_sweep"]:
            total += SIGNAL_WEIGHTS["liquidity"]
        if checks["bullish_fvg" if direction == "bullish" else "bearish_fvg"]:
            total += SIGNAL_WEIGHTS["fvg"]
        if checks["bullish_structure" if direction == "bullish" else "bearish_structure"]:
            total += SIGNAL_WEIGHTS["structure"]
        if checks["rsi_valid"]:
            total += SIGNAL_WEIGHTS["momentum"]
        if checks["price_above_ema20" if direction == "bullish" else "price_below_ema20"]:
            total += SIGNAL_WEIGHTS["price_position"]
        if checks["bullish_displacement" if direction == "bullish" else "bearish_displacement"]:
            total += SIGNAL_WEIGHTS["displacement"]
        return total

    buy_score, sell_score = score(buy_checks, "bullish"), score(sell_checks, "bearish")
    buy_mandatory = (buy_checks["ema_bullish"] and above and bull_sequence
                     and (bull_structure or bull_disp["valid"]))
    sell_mandatory = (sell_checks["ema_bearish"] and below and bear_sequence
                      and (bear_structure or bear_disp["valid"]))
    buy, sell = buy_mandatory and buy_score >= MIN_SIGNAL_SCORE, sell_mandatory and sell_score >= MIN_SIGNAL_SCORE

    if buy and not sell:
        signal, grade, confirmations = "BUY_CANDIDATE", "STRONG_BUY", buy_checks
    elif sell and not buy:
        signal, grade, confirmations = "SELL_CANDIDATE", "STRONG_SELL", sell_checks
    else:
        signal, grade = "NO_TRADE", "NO_TRADE"
        confirmations = buy_checks if buy_score >= sell_score else sell_checks

    entry, stop_loss, take_profit = last.close, None, None
    stop_distance = atr_now * ATR_MULTIPLIER
    if signal == "BUY_CANDIDATE":
        swing_low = structure["latest_swing_low"]
        stop_loss = min(entry - stop_distance, swing_low - atr_now * 0.1) if swing_low is not None else entry - stop_distance
        risk = entry - stop_loss
        if risk > 0:
            take_profit = entry + risk * RISK_REWARD
        else:
            signal, grade, stop_loss = "NO_TRADE", "NO_TRADE", None
    elif signal == "SELL_CANDIDATE":
        swing_high = structure["latest_swing_high"]
        stop_loss = max(entry + stop_distance, swing_high + atr_now * 0.1) if swing_high is not None else entry + stop_distance
        risk = stop_loss - entry
        if risk > 0:
            take_profit = entry - risk * RISK_REWARD
        else:
            signal, grade, stop_loss = "NO_TRADE", "NO_TRADE", None

    diagnostics = {
        "buy": {
            "score": buy_score, "total": 100, "minimum_score": MIN_SIGNAL_SCORE,
            "passed": buy, "mandatory_conditions_passed": buy_mandatory,
            "checks": buy_checks,
            "failed_checks": [k for k, v in buy_checks.items() if not v],
        },
        "sell": {
            "score": sell_score, "total": 100, "minimum_score": MIN_SIGNAL_SCORE,
            "passed": sell, "mandatory_conditions_passed": sell_mandatory,
            "checks": sell_checks,
            "failed_checks": [k for k, v in sell_checks.items() if not v],
        },
    }

    return {
        **base,
        "status": signal,
        "signal_grade": grade,
        "reason": "Stage 11B-3.1 ICT scalping conditions passed" if signal != "NO_TRADE" else "Stage 11B-3.1 ICT confluence conditions incomplete",
        "bias_ema20_50": bias,
        "ema20": e20_now, "ema50": e50_now, "rsi14": rsi_now, "atr14": atr_now,
        "liquidity_sweep": {**sweeps, "bullish_quality": bull_sweep_q, "bearish_quality": bear_sweep_q},
        "latest_fvg": {
            **gaps,
            "bullish_sequence_details": bull_seq_fvg,
            "bearish_sequence_details": bear_seq_fvg,
            "bullish_quality": bull_fvg_q,
            "bearish_quality": bear_fvg_q,
            "bullish_sweep_fvg_relationship": bull_pair,
            "bearish_sweep_fvg_relationship": bear_pair,
        },
        "market_structure": structure,
        "displacement": {"bullish": bull_disp, "bearish": bear_disp},
        "volume_profile": vp,
        "latest_swing_high": highs[-1][1] if highs else None,
        "latest_swing_low": lows[-1][1] if lows else None,
        "confirmations": confirmations,
        "confirmation_score": max(buy_score, sell_score),
        "confirmation_total": 100,
        "minimum_signal_score": MIN_SIGNAL_SCORE,
        "signal_weights": SIGNAL_WEIGHTS,
        "signal_diagnostics": diagnostics,
        "ict_sequence": {
            "bullish_valid": bull_sequence, "bearish_valid": bear_sequence,
            "maximum_sweep_fvg_gap": MAX_SWEEP_FVG_GAP,
        },
        "provisional_stop_loss": stop_loss,
        "provisional_take_profit": take_profit,
        "risk_reward_target": RISK_REWARD if signal != "NO_TRADE" else None,
        "risk_status": "NOT_EVALUATED",
        "execution": "DISABLED",
        "real_orders_enabled": False,
    }

"""APEX AI XAUUSD ICT + FRVP confluence analysis. Analysis only."""
from __future__ import annotations
from analysis_engine import analyze
from tickfeed_market_data import fetch_xauusd_klines
from frvp import calculate_frvp


def _near(price: float, level: float, tolerance: float) -> bool:
    return abs(price - level) <= tolerance


def analyze_xauusd(limit: int = 500) -> dict:
    m5 = fetch_xauusd_klines("5m", limit)
    m15 = fetch_xauusd_klines("15m", max(120, min(500, limit // 3)))
    h1 = fetch_xauusd_klines("1h", 120)
    m5_report = analyze(m5, "XAUUSD", "spot_gold", "5m")
    m15_report = analyze(m15, "XAUUSD", "spot_gold", "15m")
    h1_report = analyze(h1, "XAUUSD", "spot_gold", "1h")
    profile_start = max(0, len(m5) - 96)
    profile = calculate_frvp(m5, start_index=profile_start, end_index=len(m5)-1,
                             rows=48, value_area_percent=70)
    close = m5[-1].close
    atr_value = m5_report.get("atr14") or 0.0
    tolerance = max(atr_value * 0.25, close * 0.0001)
    side = m5_report.get("status")
    m15_bias, h1_bias = m15_report.get("bias_ema20_50"), h1_report.get("bias_ema20_50")
    if side == "BUY_CANDIDATE":
        mtf_ok = m15_bias == "bullish" and h1_bias == "bullish"
        frvp_ok = _near(close, profile["val"], tolerance) or _near(close, profile["poc"], tolerance) or any(_near(close, x["price"], tolerance) for x in profile["hvn"])
        direction = "BUY"
    elif side == "SELL_CANDIDATE":
        mtf_ok = m15_bias == "bearish" and h1_bias == "bearish"
        frvp_ok = _near(close, profile["vah"], tolerance) or _near(close, profile["poc"], tolerance) or any(_near(close, x["price"], tolerance) for x in profile["hvn"])
        direction = "SELL"
    else:
        mtf_ok = frvp_ok = False
        direction = "NO_TRADE"
    accepted = direction != "NO_TRADE" and mtf_ok and frvp_ok
    return {
        "symbol": "XAUUSD", "provider": "TICKFEED",
        "volume_type": "TICKFEED_TICK_VOLUME_PROXY_NOT_CENTRALIZED_SPOT_VOLUME",
        "status": direction if accepted else "NO_TRADE",
        "candidate_before_filters": side, "m15_bias": m15_bias, "h1_bias": h1_bias,
        "mtf_confirmation": mtf_ok, "frvp_confirmation": frvp_ok,
        "frvp": profile, "last_price": close, "atr14_m5": atr_value,
        "provisional_stop_loss": m5_report.get("provisional_stop_loss") if accepted else None,
        "provisional_take_profit": m5_report.get("provisional_take_profit") if accepted else None,
        "m5_analysis": m5_report, "m15_analysis": m15_report, "h1_analysis": h1_report,
        "execution": "ANALYSIS_ONLY", "real_trading_enabled": False,
        "real_orders_enabled": False,
    }

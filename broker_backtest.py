"""Broker-aware, no-lookahead XAUUSD backtest. Simulation only; never routes orders."""
from __future__ import annotations

from bisect import bisect_right
from math import isfinite
from datetime import datetime, timezone

from analysis_engine import analyze
from broker_execution import calculate_position_size
from frvp import calculate_frvp
from market_models import Candle
from gold_backtest import _resample
from risk_controls import evaluate_risk_limits

M5_INTERVAL_MS = 5 * 60 * 1000


def _utc_day(timestamp_ms: int) -> str:
    """Return the UTC calendar day for a millisecond candle timestamp."""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).date().isoformat()


def _is_data_gap(previous, current) -> bool:
    """True when consecutive supplied candles are not exactly 5 minutes apart."""
    return current.open_time - previous.open_time != M5_INTERVAL_MS


def _validate(candles, starting_balance, risk_percent, spread_usd,
              slippage_usd_per_side, commission_rate_per_side,
              max_holding_bars):
    if len(candles) < 800:
        raise ValueError("At least 800 M5 candles are required")
    vals = (starting_balance, risk_percent, spread_usd,
            slippage_usd_per_side, commission_rate_per_side)
    if not all(isfinite(float(x)) for x in vals):
        raise ValueError("Backtest inputs must be finite")
    if starting_balance <= 0 or not 0 < risk_percent <= 0.02:
        raise ValueError("starting_balance must be positive and risk_percent in (0, 0.02]")
    if min(spread_usd, slippage_usd_per_side, commission_rate_per_side) < 0:
        raise ValueError("Execution costs cannot be negative")
    if commission_rate_per_side >= 0.01:
        raise ValueError("commission_rate_per_side must be below 1%")
    if isinstance(max_holding_bars, bool) or not isinstance(max_holding_bars, int) or max_holding_bars < 1:
        raise ValueError("max_holding_bars must be a positive integer")


def _closed_htf_at(bars, close_times, timestamp, max_bars):
    end = bisect_right(close_times, timestamp)
    return bars[max(0, end - max_bars):end]


def run_broker_backtest(
    candles: list[Candle],
    starting_balance: float = 100.0,
    risk_percent: float = 0.02,
    spread_usd: float = 0.26,
    slippage_usd_per_side: float = 0.02,
    commission_rate_per_side: float = 0.0,
    max_holding_bars: int = 24,
    contract_size: float = 100.0,
    min_lot: float = 0.01,
    lot_step: float = 0.01,
) -> dict:
    """Run existing APEX ICT+FRVP rules with broker lot constraints.

    Signal is evaluated on a completed M5 candle; entry is next M5 open.
    Higher-timeframe candles are precomputed once and only closed bars are used.
    Spread is modeled as half-spread on each side. Commission is explicit and
    defaults to zero until the account's actual commission schedule is verified.
    """
    _validate(candles, starting_balance, risk_percent, spread_usd,
              slippage_usd_per_side, commission_rate_per_side,
              max_holding_bars)

    # Reject malformed or unsorted data rather than silently reordering it.
    for i, c in enumerate(candles):
        if not all(isfinite(float(v)) for v in
                   (c.open, c.high, c.low, c.close, c.volume)):
            raise ValueError("Candle data contains non-finite values")
        if min(c.open, c.high, c.low, c.close) <= 0 or c.volume < 0:
            raise ValueError("Candle data contains invalid prices or volume")
        if c.high < max(c.open, c.close, c.low) or c.low > min(c.open, c.close, c.high):
            raise ValueError("Candle OHLC values are inconsistent")
        if i and c.open_time <= candles[i-1].open_time:
            raise ValueError("Candles must be strictly chronological")

    m15_bars = _resample(candles, 3)
    h1_bars = _resample(candles, 12)
    m15_close_times = [x.close_time for x in m15_bars]
    h1_close_times = [x.close_time for x in h1_bars]

    balance = float(starting_balance)
    equity_peak = balance
    max_drawdown = 0.0
    trades = []
    position = None
    counts = {
        "bars_evaluated": 0, "ict_candidates": 0,
        "rejected_mtf": 0, "rejected_frvp": 0,
        "rejected_invalid_stops": 0, "rejected_minimum_lot": 0,
        "accepted_entries": 0,
    }
    spread_half = spread_usd / 2.0

    def close_position(exit_reference, reason, bar, index):
        nonlocal balance, position, equity_peak, max_drawdown
        p = position
        direction = 1 if p["side"] == "BUY" else -1
        exit_fill = exit_reference - direction * (spread_half + slippage_usd_per_side)
        gross = (exit_fill - p["entry_fill"]) * p["quantity_xau"] * direction
        exit_commission = exit_fill * p["quantity_xau"] * commission_rate_per_side
        net = gross - p["entry_commission"] - exit_commission
        balance += gross - exit_commission
        trade = {
            "side": p["side"], "entry_time": p["entry_time"],
            "exit_time": bar.close_time, "entry": round(p["entry_fill"], 3),
            "exit": round(exit_fill, 3), "lots": p["lots"],
            "quantity_xau": p["quantity_xau"], "net_pnl": round(net, 4),
            "reason": reason, "bars_held": index - p["entry_index"],
            "risk_budget_usd": round(p["risk_budget"], 4),
            "estimated_risk_usd": round(p["estimated_risk"], 4),
        }
        trades.append(trade)
        equity_peak = max(equity_peak, balance)
        if equity_peak > 0:
            max_drawdown = max(max_drawdown, (equity_peak - balance) / equity_peak)
        position = None

    for i in range(720, len(candles) - 1):
        bar = candles[i]
        if position:
            age = i - position["entry_index"]
            if position["side"] == "BUY":
                hit_sl = bar.low <= position["sl"]
                hit_tp = bar.high >= position["tp"]
                if hit_sl:
                    # Gap-through stop: use worse opening price; otherwise stop price.
                    ref = min(position["sl"], bar.open)
                    close_position(ref, "SL", bar, i)
                elif hit_tp:
                    close_position(position["tp"], "TP", bar, i)
                elif age >= max_holding_bars:
                    close_position(bar.close, "TIME", bar, i)
            else:
                hit_sl = bar.high >= position["sl"]
                hit_tp = bar.low <= position["tp"]
                if hit_sl:
                    ref = max(position["sl"], bar.open)
                    close_position(ref, "SL", bar, i)
                elif hit_tp:
                    close_position(position["tp"], "TP", bar, i)
                elif age >= max_holding_bars:
                    close_position(bar.close, "TIME", bar, i)
            continue

        history = candles[max(0, i - 299):i + 1]
        m15 = _closed_htf_at(m15_bars, m15_close_times, bar.close_time, 160)
        h1 = _closed_htf_at(h1_bars, h1_close_times, bar.close_time, 100)
        if len(m15) < 60 or len(h1) < 60:
            continue

        counts["bars_evaluated"] += 1
        report = analyze(history, "XAUUSD", "spot_gold", "5m")
        side = report.get("status")
        if side not in ("BUY_CANDIDATE", "SELL_CANDIDATE"):
            continue
        counts["ict_candidates"] += 1
        direction = 1 if side == "BUY_CANDIDATE" else -1
        bias = "bullish" if direction == 1 else "bearish"

        m15_report = analyze(m15[-160:], "XAUUSD", "spot_gold", "15m")
        h1_report = analyze(h1[-100:], "XAUUSD", "spot_gold", "1h")
        if (m15_report.get("bias_ema20_50") != bias
                or h1_report.get("bias_ema20_50") != bias):
            counts["rejected_mtf"] += 1
            continue

        profile = calculate_frvp(
            history, start_index=max(0, len(history) - 96),
            end_index=len(history) - 1, rows=48, value_area_percent=70,
        )
        price = bar.close
        atr_value = report.get("atr14") or 0.0
        tolerance = max(atr_value * 0.25, price * 0.0001)
        levels = [profile["poc"], profile["val"] if direction == 1 else profile["vah"]]
        levels.extend(x["price"] for x in profile["hvn"])
        if not any(abs(price - level) <= tolerance for level in levels):
            counts["rejected_frvp"] += 1
            continue

        stop = report.get("provisional_stop_loss")
        target = report.get("provisional_take_profit")
        entry_reference = candles[i + 1].open
        if stop is None or target is None:
            counts["rejected_invalid_stops"] += 1
            continue
        if (direction == 1 and not stop < entry_reference < target) or (
            direction == -1 and not target < entry_reference < stop
        ):
            counts["rejected_invalid_stops"] += 1
            continue

        size = calculate_position_size(
            balance=balance, risk_percent=risk_percent,
            entry_price=entry_reference, stop_price=stop,
            spread_usd=spread_usd,
            slippage_usd_per_side=slippage_usd_per_side,
            commission_rate_per_side=commission_rate_per_side,
            contract_size=contract_size, min_lot=min_lot, lot_step=lot_step,
        )
        if not size.accepted:
            counts["rejected_minimum_lot"] += 1
            continue

        portfolio_gate = evaluate_risk_limits(
            current_equity=balance,
            day_start_equity=utc_day_start_balance,
            open_positions=0,
            open_risk_usd=0.0,
            proposed_risk_usd=size.estimated_risk_usd,
            max_positions=1,
            daily_loss_fraction=daily_loss_limit_fraction,
            max_total_risk_fraction=0.02,
        )
        if not portfolio_gate.accepted:
            counts["rejected_portfolio_risk"] += 1
            continue

        entry_fill = entry_reference + direction * (spread_half + slippage_usd_per_side)
        entry_commission = entry_fill * size.quantity_xau * commission_rate_per_side
        if entry_commission >= balance:
            counts["rejected_minimum_lot"] += 1
            continue
        balance -= entry_commission
        position = {
            "side": "BUY" if direction == 1 else "SELL",
            "entry_index": i + 1, "entry_time": candles[i + 1].open_time,
            "entry_fill": entry_fill, "quantity_xau": size.quantity_xau,
            "lots": size.lots, "sl": stop, "tp": target,
            "risk_budget": size.risk_budget_usd,
            "estimated_risk": size.estimated_risk_usd,
            "entry_commission": entry_commission,
        }
        counts["accepted_entries"] += 1

    if position:
        last = candles[-1]
        close_position(last.close, "END_OF_DATA", last, len(candles) - 1)

    wins = [t for t in trades if t["net_pnl"] > 0]
    losses = [t for t in trades if t["net_pnl"] < 0]
    gross_profit = sum(t["net_pnl"] for t in wins)
    gross_loss = abs(sum(t["net_pnl"] for t in losses))
    return {
        "symbol": "XAUUSD", "strategy": "ICT+FRVP_M5_M15_H1",
        "engine": "BROKER_AWARE_V1", "starting_balance": starting_balance,
        "ending_balance": round(balance, 4), "net_pnl": round(balance - starting_balance, 4),
        "return_percent": round((balance / starting_balance - 1) * 100, 3),
        "trades": len(trades), "wins": len(wins), "losses": len(losses),
        "win_rate_percent": round(len(wins) / len(trades) * 100, 2) if trades else 0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "max_drawdown_percent": round(max_drawdown * 100, 3),
        "risk_percent_per_trade": risk_percent,\n        "daily_loss_limit_percent": 3.0,\n        "data_gap_policy": "CLOSE_AT_PRE_GAP_CLOSE_AND_SKIP_GAP_BAR",
        "broker_model": {
            "broker": "JustMarkets", "account": "Standard",
            "contract_size_xau_per_lot": contract_size,
            "minimum_lot": min_lot, "lot_step": lot_step,
            "spread_usd_assumption": spread_usd,
            "slippage_usd_per_side_assumption": slippage_usd_per_side,
            "commission_rate_per_side_assumption": commission_rate_per_side,
            "volume_note": "FRVP uses candle tick-volume proxy, not centralized exchange volume",
        },
        "diagnostics": counts, "trade_history": trades,
        "execution": "BACKTEST_ONLY", "real_orders_enabled": False,
    }

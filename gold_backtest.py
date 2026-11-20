"""Conservative XAUUSD ICT + FRVP historical simulation; no order routing."""

from __future__ import annotations

from analysis_engine import analyze
from market_models import Candle
from frvp import calculate_frvp


def _resample(candles: list[Candle], factor: int) -> list[Candle]:
    """Build aligned higher-timeframe bars; discard incomplete/gapped groups."""
    if factor < 1:
        raise ValueError("factor must be positive")

    base_ms = 300_000
    target_ms = base_ms * factor
    grouped: dict[int, list[Candle]] = {}

    for candle in candles:
        bucket = (candle.open_time // target_ms) * target_ms
        grouped.setdefault(bucket, []).append(candle)

    out = []
    for bucket, chunk in sorted(grouped.items()):
        by_time = {x.open_time: x for x in chunk}
        expected = [bucket + n * base_ms for n in range(factor)]
        if any(ts not in by_time for ts in expected):
            continue

        ordered = [by_time[ts] for ts in expected]
        out.append(Candle(
            open_time=bucket,
            open=ordered[0].open,
            high=max(x.high for x in ordered),
            low=min(x.low for x in ordered),
            close=ordered[-1].close,
            volume=sum(x.volume for x in ordered),
            close_time=bucket + target_ms - 1,
            quote_volume=sum(x.quote_volume for x in ordered),
            trades=sum(x.trades for x in ordered),
            taker_buy_base=0.0,
            taker_buy_quote=0.0,
        ))
    return out


def _new_sequence_gate_stats() -> dict:
    return {
        "bars_with_valid_sequence": 0,
        "mandatory_passed": 0,
        "mandatory_failed": 0,
        "score_passed": 0,
        "score_failed": 0,
        "signal_passed": 0,
        "failed_checks_when_sequence_valid": {},
        "mandatory_failure_reasons": {
            "trend_ema": 0,
            "price_position": 0,
            "structure_and_displacement": 0,
        },
    }


def _increment(counter: dict, key: str) -> None:
    counter[key] = counter.get(key, 0) + 1


def _safe_number(value):
    """Keep diagnostic JSON values finite and serializable."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value if value == value and abs(value) != float("inf") else None
    return value


def run_xauusd_backtest(
    candles: list[Candle],
    starting_balance: float = 100.0,
    risk_percent: float = 0.01,
    fee_rate: float = 0.0005,
    slippage_bps: float = 2.0,
    max_holding_bars: int = 24,
) -> dict:

    if len(candles) < 800:
        raise ValueError("At least 800 M5 candles are required for M15/H1 confirmation warm-up")

    if (
        starting_balance <= 0
        or not 0 < risk_percent <= .02
        or not 0 <= fee_rate < .01
        or not 0 <= slippage_bps < 100
        or max_holding_bars < 1
    ):
        raise ValueError("Invalid backtest parameters")

    balance = starting_balance
    peak = balance
    max_dd = 0.0
    trades = []
    position = None

    evaluated = 0
    ict_candidates = 0
    rejected_mtf = 0
    rejected_frvp = 0

    candidate_counts = {
        "BUY_CANDIDATE": 0,
        "SELL_CANDIDATE": 0,
        "NO_TRADE": 0,
        "OTHER": 0,
    }

    ict_checks = {
        direction: {
            "bars_checked": 0,
            "score_total": 0.0,
            "max_score": 0.0,
            "mandatory_passed": 0,
            "mandatory_failed": 0,
            "failed_checks": {},
        }
        for direction in ("buy", "sell")
    }

    setup_diagnostics = {
        direction: {
            "sweeps_seen": 0,
            "sweeps_passed_wick_quality": 0,
            "fvg_zones_found": 0,
            "fvg_fully_mitigated": 0,
            "fvg_failed_size": 0,
            "fvg_failed_displacement": 0,
            "fvg_invalid_atr": 0,
            "fvg_passed_quality": 0,
            "valid_sequences": 0,
        }
        for direction in ("buy", "sell")
    }

    sequence_gate_diagnostics = {
        "buy": _new_sequence_gate_stats(),
        "sell": _new_sequence_gate_stats(),
    }

    # Detailed Stage 3.4 evidence for every bar with a valid ICT sequence.
    # This is diagnostic output only; it does not change entry decisions.
    sequence_gate_samples = []

    slip = slippage_bps / 10000

    for i in range(720, len(candles) - 1):
        bar = candles[i]

        if position:
            age = i - position["entry_index"]
            hit_sl = (
                bar.low <= position["sl"]
                if position["side"] == "BUY"
                else bar.high >= position["sl"]
            )
            hit_tp = (
                bar.high >= position["tp"]
                if position["side"] == "BUY"
                else bar.low <= position["tp"]
            )

            exit_price = None
            reason = None
            if hit_sl:
                exit_price, reason = position["sl"], "SL"
            elif hit_tp:
                exit_price, reason = position["tp"], "TP"
            elif age >= max_holding_bars:
                exit_price, reason = bar.close, "TIME"

            if exit_price is not None:
                direction = 1 if position["side"] == "BUY" else -1
                exit_fill = exit_price * (1 - direction * slip)
                gross = (
                    (exit_fill - position["entry_fill"])
                    * position["qty"] * direction
                )
                fees = (
                    position["entry_fill"] * position["qty"]
                    + exit_fill * position["qty"]
                ) * fee_rate
                net = gross - fees
                balance += net

                trades.append({
                    "side": position["side"],
                    "entry_time": position["entry_time"],
                    "exit_time": bar.close_time,
                    "entry": round(position["entry_fill"], 3),
                    "exit": round(exit_fill, 3),
                    "qty": round(position["qty"], 5),
                    "net_pnl": round(net, 4),
                    "reason": reason,
                    "bars_held": age,
                })

                peak = max(peak, balance)
                max_dd = max(max_dd, (peak - balance) / peak if peak else 0)
                position = None
            continue

        history = candles[max(0, i - 299):i + 1]
        m15 = _resample(candles[:i + 1], 3)[-160:]
        h1 = _resample(candles[:i + 1], 12)[-100:]

        if len(m15) < 60 or len(h1) < 60:
            continue

        evaluated += 1
        report = analyze(history, "XAUUSD", "spot_gold", "5m")
        side = report.get("status", "OTHER")

        if side in candidate_counts:
            candidate_counts[side] += 1
        else:
            candidate_counts["OTHER"] += 1

        signal_diag = report.get("signal_diagnostics") or {}
        for direction_name in ("buy", "sell"):
            detail = signal_diag.get(direction_name) or {}
            checks = detail.get("checks") or {}
            stats = ict_checks[direction_name]

            if checks:
                stats["bars_checked"] += 1
                score = detail.get("score", 0)
                if isinstance(score, (int, float)):
                    stats["score_total"] += score
                    stats["max_score"] = max(stats["max_score"], score)
                for check_name, passed in checks.items():
                    if not passed:
                        _increment(stats["failed_checks"], check_name)

            mandatory = detail.get("mandatory_conditions_passed")
            if mandatory is True:
                stats["mandatory_passed"] += 1
            elif mandatory is False:
                stats["mandatory_failed"] += 1

        sequence = report.get("ict_sequence") or {}

        for direction_name, valid_key, setup_key in (
            ("buy", "bullish_valid", "bullish_setup"),
            ("sell", "bearish_valid", "bearish_setup"),
        ):
            if not sequence.get(valid_key, False):
                continue

            stats = sequence_gate_diagnostics[direction_name]
            stats["bars_with_valid_sequence"] += 1

            detail = signal_diag.get(direction_name) or {}
            checks = detail.get("checks") or {}
            score = detail.get("score", 0)
            minimum_score = detail.get(
                "minimum_score",
                report.get("minimum_signal_score", 65),
            )
            mandatory = detail.get("mandatory_conditions_passed") is True

            if mandatory:
                stats["mandatory_passed"] += 1
            else:
                stats["mandatory_failed"] += 1

            score_is_valid = (
                isinstance(score, (int, float))
                and isinstance(minimum_score, (int, float))
            )
            if score_is_valid and score >= minimum_score:
                stats["score_passed"] += 1
            else:
                stats["score_failed"] += 1

            if detail.get("passed") is True:
                stats["signal_passed"] += 1

            for check_name, passed in checks.items():
                if not passed:
                    _increment(
                        stats["failed_checks_when_sequence_valid"],
                        check_name,
                    )

            trend_key = "ema_bullish" if direction_name == "buy" else "ema_bearish"
            position_key = "price_above_ema20" if direction_name == "buy" else "price_below_ema20"
            structure_key = "bullish_structure" if direction_name == "buy" else "bearish_structure"
            displacement_key = "bullish_displacement" if direction_name == "buy" else "bearish_displacement"

            if checks and not checks.get(trend_key, False):
                stats["mandatory_failure_reasons"]["trend_ema"] += 1
            if checks and not checks.get(position_key, False):
                stats["mandatory_failure_reasons"]["price_position"] += 1
            if checks and not (
                checks.get(structure_key, False)
                or checks.get(displacement_key, False)
            ):
                stats["mandatory_failure_reasons"]["structure_and_displacement"] += 1

            # Stage 3.4 nested diagnostics are generated by analysis_engine.py.
            # Include them verbatim when present, with useful candle/setup context.
            gate_detail = detail.get("sequence_gate") or {}
            setup = sequence.get(setup_key) or {}
            sample = {
                "bar_index": i,
                "bar_open_time": bar.open_time,
                "bar_close_time": bar.close_time,
                "direction": direction_name,
                "sequence_valid": True,
                "sweep_index": setup.get("sweep_index"),
                "sweep_quality": setup.get("sweep_quality"),
                "fvg": setup.get("fvg"),
                "fvg_quality": setup.get("fvg_quality"),
                "relationship": setup.get("relationship"),
                "signal_score": detail.get("score"),
                "minimum_signal_score": minimum_score,
                "mandatory_conditions_passed": mandatory,
                "signal_passed": detail.get("passed"),
                "checks": checks,
                "sequence_gate": gate_detail,
            }
            sequence_gate_samples.append(sample)

        for direction_name, setup_key in (
            ("buy", "bullish_setup"),
            ("sell", "bearish_setup"),
        ):
            setup = sequence.get(setup_key) or {}
            details = setup.get("diagnostics") or {}
            for key in setup_diagnostics[direction_name]:
                setup_diagnostics[direction_name][key] += int(details.get(key, 0) or 0)

        if side not in ("BUY_CANDIDATE", "SELL_CANDIDATE"):
            continue

        ict_candidates += 1

        m15r = analyze(m15, "XAUUSD", "spot_gold", "15m")
        h1r = analyze(h1, "XAUUSD", "spot_gold", "1h")
        bias = "bullish" if side == "BUY_CANDIDATE" else "bearish"

        if (
            m15r.get("bias_ema20_50") != bias
            or h1r.get("bias_ema20_50") != bias
        ):
            rejected_mtf += 1
            continue

        profile = calculate_frvp(
            history,
            start_index=max(0, len(history) - 96),
            end_index=len(history) - 1,
            rows=48,
            value_area_percent=70,
        )

        price = bar.close
        atr_value = report.get("atr14") or 0.0
        tol = max(atr_value * 0.25, price * 0.0001)

        levels = [profile["poc"]]
        levels.append(profile["val"] if bias == "bullish" else profile["vah"])
        levels.extend(x["price"] for x in profile["hvn"])

        if not any(abs(price - level) <= tol for level in levels):
            rejected_frvp += 1
            continue

        sl = report.get("provisional_stop_loss")
        tp = report.get("provisional_take_profit")
        if sl is None or tp is None:
            continue

        entry = candles[i + 1].open
        direction = 1 if bias == "bullish" else -1
        risk = abs(entry - sl)
        if risk <= 0:
            continue

        qty = (balance * risk_percent) / risk
        entry_fill = entry * (1 + direction * slip)

        position = {
            "side": "BUY" if direction == 1 else "SELL",
            "entry_index": i + 1,
            "entry_time": candles[i + 1].open_time,
            "entry_fill": entry_fill,
            "qty": qty,
            "sl": sl,
            "tp": tp,
        }

    if position:
        last = candles[-1]
        direction = 1 if position["side"] == "BUY" else -1
        exit_fill = last.close * (1 - direction * slip)
        gross = (
            (exit_fill - position["entry_fill"])
            * position["qty"] * direction
        )
        fees = (
            position["entry_fill"] + exit_fill
        ) * position["qty"] * fee_rate
        net = gross - fees
        balance += net

        trades.append({
            "side": position["side"],
            "entry_time": position["entry_time"],
            "exit_time": last.close_time,
            "entry": round(position["entry_fill"], 3),
            "exit": round(exit_fill, 3),
            "qty": round(position["qty"], 5),
            "net_pnl": round(net, 4),
            "reason": "END_OF_DATA",
            "bars_held": len(candles) - 1 - position["entry_index"],
        })

    wins = sum(1 for trade in trades if trade["net_pnl"] > 0)
    losses = sum(1 for trade in trades if trade["net_pnl"] < 0)
    gross_profit = sum(trade["net_pnl"] for trade in trades if trade["net_pnl"] > 0)
    gross_loss = abs(sum(trade["net_pnl"] for trade in trades if trade["net_pnl"] < 0))

    ict_checks_result = {}
    for direction_name, stats in ict_checks.items():
        count = stats["bars_checked"]
        ict_checks_result[direction_name] = {
            **stats,
            "average_score": round(stats["score_total"] / count, 2) if count else 0,
        }

    return {
        "symbol": "XAUUSD",
        "strategy": "ICT+FRVP_M5_M15_H1",
        "provider": "TICKFEED_STORED_HISTORY",
        "volume_type": "TICKFEED_TICK_VOLUME_PROXY_NOT_CENTRALIZED_SPOT_VOLUME",
        "starting_balance": starting_balance,
        "ending_balance": round(balance, 4),
        "net_pnl": round(balance - starting_balance, 4),
        "return_percent": round((balance / starting_balance - 1) * 100, 3),
        "trades": len(trades),
        "wins": wins,
        "losses": losses,
        "win_rate_percent": round(wins / len(trades) * 100, 2) if trades else 0,
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss else None,
        "max_drawdown_percent": round(max_dd * 100, 3),
        "diagnostics": {
            "evaluated": evaluated,
            "ict_candidates": ict_candidates,
            "rejected_mtf": rejected_mtf,
            "rejected_frvp": rejected_frvp,
            "candidate_counts": candidate_counts,
            "ict_checks": ict_checks_result,
            "setup_diagnostics": setup_diagnostics,
            "sequence_gate_diagnostics": sequence_gate_diagnostics,
            "sequence_gate_samples": sequence_gate_samples,
        },
        "trade_history": trades,
        "execution": "BACKTEST_ONLY",
        "real_orders_enabled": False,
    }

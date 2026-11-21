"""Portfolio-level risk gates for the APEX XAUUSD paper/backtest engine.

This module is deliberately execution-agnostic: it never places orders.
All monetary inputs are USD. Defaults preserve the $100 account and the
project's conservative portfolio limits.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class RiskDecision:
    accepted: bool
    reason: str
    daily_loss_usd: float
    daily_loss_limit_usd: float
    projected_total_risk_usd: float
    total_risk_limit_usd: float


def evaluate_risk_limits(
    *,
    current_equity: float,
    day_start_equity: float,
    open_positions: int,
    open_risk_usd: float,
    proposed_risk_usd: float,
    max_positions: int = 3,
    daily_loss_fraction: float = 0.03,
    max_total_risk_fraction: float = 0.02,
) -> RiskDecision:
    """Accept a proposed paper trade only when all portfolio limits pass.

    Daily loss is measured from day-start equity to current equity. The
    proposed trade's risk is also checked against the remaining daily-loss
    allowance and aggregate open-risk allowance. Callers should pass equity
    (not balance) so floating P/L is reflected in the daily lock.
    """
    numeric = (
        current_equity, day_start_equity, open_risk_usd, proposed_risk_usd,
        daily_loss_fraction, max_total_risk_fraction,
    )
    if not all(isfinite(float(value)) for value in numeric):
        raise ValueError("Risk inputs must be finite")
    if current_equity <= 0 or day_start_equity <= 0:
        raise ValueError("Equity values must be positive")
    if open_positions < 0 or max_positions < 1:
        raise ValueError("Position counts are invalid")
    if open_risk_usd < 0 or proposed_risk_usd <= 0:
        raise ValueError("Risk amounts are invalid")
    if not 0 < daily_loss_fraction <= 1:
        raise ValueError("daily_loss_fraction must be in (0, 1]")
    if not 0 < max_total_risk_fraction <= 1:
        raise ValueError("max_total_risk_fraction must be in (0, 1]")

    daily_limit = day_start_equity * daily_loss_fraction
    daily_loss = max(0.0, day_start_equity - current_equity)
    total_limit = current_equity * max_total_risk_fraction
    projected_risk = open_risk_usd + proposed_risk_usd

    if open_positions >= max_positions:
        reason = "MAX_OPEN_POSITIONS_REACHED"
    elif daily_loss >= daily_limit:
        reason = "DAILY_LOSS_LIMIT_REACHED"
    elif daily_loss + proposed_risk_usd > daily_limit + 1e-9:
        reason = "TRADE_RISK_EXCEEDS_REMAINING_DAILY_LOSS"
    elif projected_risk > total_limit + 1e-9:
        reason = "MAX_TOTAL_OPEN_RISK_EXCEEDED"
    else:
        reason = "OK"

    return RiskDecision(
        accepted=reason == "OK",
        reason=reason,
        daily_loss_usd=round(daily_loss, 6),
        daily_loss_limit_usd=round(daily_limit, 6),
        projected_total_risk_usd=round(projected_risk, 6),
        total_risk_limit_usd=round(total_limit, 6),
    )

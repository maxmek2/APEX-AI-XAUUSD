"""Broker-aware position sizing for JustMarkets XAUUSD Standard.

All prices are USD per troy ounce. Quantity returned is XAU units, not lots.
This module is research/backtest-only and does not submit orders.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite


@dataclass(frozen=True)
class PositionSize:
    accepted: bool
    lots: float
    quantity_xau: float
    risk_budget_usd: float
    estimated_risk_usd: float
    estimated_cost_usd: float
    reason: str


def calculate_position_size(
    *,
    balance: float,
    risk_percent: float,
    entry_price: float,
    stop_price: float,
    spread_usd: float,
    slippage_usd_per_side: float = 0.0,
    commission_rate_per_side: float = 0.0,
    contract_size: float = 100.0,
    min_lot: float = 0.01,
    lot_step: float = 0.01,
) -> PositionSize:
    """Floor size to broker lot step and reject if minimum lot breaches risk.

    Risk estimate includes stop distance, full spread, two-sided slippage and
    two-sided notional commission. Commission is an explicit assumption; set
    it to zero for a spread-only account model unless broker terms confirm it.
    """
    values = (
        balance, risk_percent, entry_price, stop_price, spread_usd,
        slippage_usd_per_side, commission_rate_per_side, contract_size,
        min_lot, lot_step,
    )
    if not all(isfinite(float(x)) for x in values):
        raise ValueError("All sizing inputs must be finite")
    if balance <= 0 or not 0 < risk_percent <= 0.10:
        raise ValueError("balance must be positive and risk_percent in (0, 0.10]")
    if entry_price <= 0 or stop_price <= 0 or entry_price == stop_price:
        raise ValueError("entry and stop must be positive and different")
    if min(spread_usd, slippage_usd_per_side, commission_rate_per_side) < 0:
        raise ValueError("cost inputs cannot be negative")
    if contract_size <= 0 or min_lot <= 0 or lot_step <= 0:
        raise ValueError("broker contract and lot constraints must be positive")

    budget = balance * risk_percent
    stop_distance = abs(entry_price - stop_price)
    commission_per_xau = (entry_price + stop_price) * commission_rate_per_side
    risk_per_xau = (
        stop_distance + spread_usd + 2 * slippage_usd_per_side
        + commission_per_xau
    )
    raw_lots = budget / (risk_per_xau * contract_size)
    lots = floor((raw_lots + 1e-12) / lot_step) * lot_step
    lots = round(lots, 8)

    if lots + 1e-12 < min_lot:
        min_risk = risk_per_xau * contract_size * min_lot
        return PositionSize(
            False, 0.0, 0.0, budget, round(min_risk, 6),
            round((spread_usd + 2 * slippage_usd_per_side + commission_per_xau)
                  * contract_size * min_lot, 6),
            "MINIMUM_LOT_EXCEEDS_RISK_BUDGET",
        )

    qty = lots * contract_size
    risk = risk_per_xau * qty
    cost_per_xau = spread_usd + 2 * slippage_usd_per_side + commission_per_xau
    cost = cost_per_xau * qty
    if risk > budget + 1e-8:
        return PositionSize(
            False, 0.0, 0.0, budget, round(risk, 6), round(cost, 6),
            "ROUNDED_SIZE_EXCEEDS_RISK_BUDGET",
        )
    return PositionSize(
        True, lots, qty, budget, round(risk, 6), round(cost, 6), "OK"
    )

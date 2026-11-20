
"""APEX AI paper portfolio and risk engine.
Simulation only. No exchange credentials or real order routing.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from threading import RLock
from time import time, localtime, strftime


@dataclass
class PaperPosition:
    id: int
    symbol: str
    side: str
    quantity: float
    entry_price: float
    stop_loss: float
    take_profit: float
    opened_at: float
    risk_cash: float
    entry_fee: float


class PaperEngine:

    def __init__(
        self,
        starting_balance: float = 100.0,
        risk_fraction: float = 0.01,
        max_positions: int = 3,
        max_total_risk_fraction: float = 0.02,
        daily_loss_fraction: float = 0.03,
        fee_rate: float = 0.001,
    ):

        if starting_balance <= 0:
            raise ValueError("Starting balance must be positive")

        if not 0 < risk_fraction <= 0.02:
            raise ValueError("Risk per trade must be between 0 and 2%")

        if not 0 < max_total_risk_fraction <= 0.05:
            raise ValueError("Maximum total risk must be between 0 and 5%")

        if not 0 < daily_loss_fraction <= 0.10:
            raise ValueError("Daily loss limit must be between 0 and 10%")

        if max_positions < 1:
            raise ValueError("Maximum positions must be at least 1")

        if not 0 <= fee_rate <= 0.02:
            raise ValueError("Fee rate must be between 0 and 2%")

        self.starting_balance = float(starting_balance)
        self.balance = float(starting_balance)

        self.risk_fraction = float(risk_fraction)
        self.max_positions = int(max_positions)
        self.max_total_risk_fraction = float(max_total_risk_fraction)
        self.daily_loss_fraction = float(daily_loss_fraction)
        self.fee_rate = float(fee_rate)

        self.positions: list[PaperPosition] = []
        self.closed: list[dict] = []

        self._next_id = 1
        self._lock = RLock()

    def _today(self):
        return strftime("%Y-%m-%d", localtime())

    def _daily_realized_pnl(self):
        today = self._today()

        return sum(
            trade["pnl"]
            for trade in self.closed
            if trade.get("date") == today
        )

    def _open_risk(self):
        return sum(p.risk_cash for p in self.positions)

    def account(self) -> dict:

        with self._lock:

            daily_pnl = self._daily_realized_pnl()
            daily_limit = (
                self.starting_balance * self.daily_loss_fraction
            )

            return {
                "mode": "PAPER_ONLY",
                "starting_balance": self.starting_balance,
                "balance": round(self.balance, 2),
                "risk_fraction": self.risk_fraction,
                "max_positions": self.max_positions,
                "open_risk": round(self._open_risk(), 4),
                "daily_realized_pnl": round(daily_pnl, 4),
                "daily_loss_limit": round(daily_limit, 2),
                "daily_limit_reached": daily_pnl <= -daily_limit,
                "open_positions": [
                    asdict(p) for p in self.positions
                ],
                "closed_trades": self.closed[-50:],
                "real_orders_enabled": False,
            }

    def open_position(
        self,
        symbol: str,
        side: str,
        entry: float,
        stop: float,
        target: float,
    ) -> dict:

        side = side.upper()
        symbol = symbol.upper()

        if symbol != "XAUUSD":
            raise ValueError("APEX AI accepts XAUUSD only")

        if side not in ("BUY", "SELL"):
            raise ValueError("Side must be BUY or SELL")

        if min(entry, stop, target) <= 0:
            raise ValueError("Prices must be positive")

        if side == "BUY":
            distance = entry - stop
            reward = target - entry
        else:
            distance = stop - entry
            reward = entry - target

        if distance <= 0 or reward <= 0:
            raise ValueError(
                "Stop loss and target are on the wrong side"
            )

        with self._lock:

            if len(self.positions) >= self.max_positions:
                raise ValueError("Maximum open positions reached")

            daily_pnl = self._daily_realized_pnl()
            daily_limit = (
                self.starting_balance * self.daily_loss_fraction
            )

            if daily_pnl <= -daily_limit:
                raise ValueError("Daily loss limit reached")

            risk_cash = self.balance * self.risk_fraction

            total_risk_limit = (
                self.starting_balance
                * self.max_total_risk_fraction
            )

            remaining_risk = (
                total_risk_limit - self._open_risk()
            )

            risk_cash = min(risk_cash, remaining_risk)

            if risk_cash <= 0:
                raise ValueError("Maximum total open risk reached")

            # Risk-based position sizing.
            quantity = risk_cash / distance

            # Cash-notional cap: this basic engine does not simulate
            # leverage or futures margin.
            available_notional = max(0.0, self.balance)

            current_notional = sum(
                p.quantity * p.entry_price
                for p in self.positions
            )

            remaining_notional = max(
                0.0,
                available_notional - current_notional
            )

            quantity = min(
                quantity,
                remaining_notional / entry
            )

            if quantity <= 0:
                raise ValueError("Insufficient available paper capital")

            actual_risk = quantity * distance
            notional = quantity * entry
            entry_fee = notional * self.fee_rate

            if entry_fee >= self.balance:
                raise ValueError("Insufficient balance for entry fee")

            position = PaperPosition(
                id=self._next_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                entry_price=float(entry),
                stop_loss=float(stop),
                take_profit=float(target),
                opened_at=time(),
                risk_cash=actual_risk,
                entry_fee=entry_fee,
            )

            self._next_id += 1
            self.positions.append(position)

            # Deduct simulated entry fee.
            self.balance -= entry_fee

            return {
                "accepted": True,
                "position": asdict(position),
                "risk_cash": round(actual_risk, 4),
                "notional": round(notional, 4),
                "risk_reward": round(reward / distance, 2),
                "entry_fee": round(entry_fee, 4),
                "mode": "PAPER_ONLY",
            }

    def close_position(
        self,
        position_id: int,
        exit_price: float,
    ) -> dict:

        if exit_price <= 0:
            raise ValueError("Exit price must be positive")

        with self._lock:

            position = next(
                (
                    p for p in self.positions
                    if p.id == position_id
                ),
                None,
            )

            if position is None:
                raise ValueError("Position not found")

            direction = (
                1 if position.side == "BUY" else -1
            )

            gross_pnl = (
                (exit_price - position.entry_price)
                * position.quantity
                * direction
            )

            exit_fee = (
                exit_price * position.quantity * self.fee_rate
            )

            net_pnl = (
                gross_pnl
                - position.entry_fee
                - exit_fee
            )

            self.balance += gross_pnl - exit_fee

            self.positions.remove(position)

            closed_at = time()

            record = {
                "id": position.id,
                "symbol": position.symbol,
                "side": position.side,
                "entry": position.entry_price,
                "exit": float(exit_price),
                "quantity": position.quantity,
                "gross_pnl": round(gross_pnl, 4),
                "entry_fee": round(position.entry_fee, 4),
                "exit_fee": round(exit_fee, 4),
                "pnl": round(net_pnl, 4),
                "closed_at": closed_at,
                "date": strftime(
                    "%Y-%m-%d", localtime(closed_at)
                ),
                "mode": "PAPER_ONLY",
            }

            self.closed.append(record)

            return record

    def check_positions(
        self,
        symbol: str,
        market_price: float,
    ) -> list[dict]:
        """Close paper positions when supplied price reaches SL or TP.

        This method must be called by a market-data monitoring loop.
        It does not run automatically by itself.
        """

        if market_price <= 0:
            raise ValueError("Market price must be positive")

        symbol = symbol.upper()
        results = []

        with self._lock:

            triggered = []

            for position in self.positions:

                if position.symbol != symbol:
                    continue

                if position.side == "BUY":

                    if market_price <= position.stop_loss:
                        triggered.append(position.id)

                    elif market_price >= position.take_profit:
                        triggered.append(position.id)

                else:

                    if market_price >= position.stop_loss:
                        triggered.append(position.id)

                    elif market_price <= position.take_profit:
                        triggered.append(position.id)

            for position_id in triggered:

                results.append(
                    self.close_position(
                        position_id,
                        market_price,
                    )
                )

        return results


# Default demo account.
# Real trading is not implemented.

paper = PaperEngine(
    starting_balance=100.0,
    risk_fraction=0.01,
    max_positions=3,
    max_total_risk_fraction=0.02,
    daily_loss_fraction=0.03,
    fee_rate=0.001,
)

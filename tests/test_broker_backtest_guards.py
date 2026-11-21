"""Regression tests for conservative broker backtest guards."""
import unittest

from broker_backtest import (
    _is_data_gap, _mark_to_market_equity, _utc_day, _validate,
    _worst_intrabar_equity,
)
from market_models import Candle


class BrokerBacktestGuardTests(unittest.TestCase):
    def candle(self, open_time):
        return Candle(open_time, 2000, 2001, 1999, 2000, 100, open_time + 299999)

    def test_mark_to_market_equity_includes_unrealized_loss_and_exit_costs(self):
        position = {
            "side": "BUY",
            "entry_fill": 2001.0,
            "quantity_xau": 1.0,
        }
        equity = _mark_to_market_equity(
            99.0, position, 1999.0,
            spread_half=0.13,
            slippage_usd_per_side=0.02,
            commission_rate_per_side=0.0,
        )
        self.assertAlmostEqual(equity, 96.85)

    def test_worst_intrabar_equity_uses_adverse_candle_extreme(self):
        buy = {"side": "BUY", "entry_fill": 2001.0, "quantity_xau": 1.0}
        bar = self.candle(300000)
        # The candle low is 1999; with 0.15 exit-side costs equity is 96.85.
        self.assertAlmostEqual(
            _worst_intrabar_equity(99.0, buy, bar, 0.13, 0.02, 0.0),
            96.85,
        )

    def test_flat_mark_to_market_equity_equals_balance(self):
        self.assertEqual(
            _mark_to_market_equity(98.5, None, 2000.0, 0.13, 0.02, 0.0),
            98.5,
        )

    def test_five_minute_sequence_is_not_a_gap(self):
        self.assertFalse(_is_data_gap(self.candle(0), self.candle(300000)))

    def test_missing_five_minute_bar_is_gap(self):
        self.assertTrue(_is_data_gap(self.candle(0), self.candle(600000)))

    def test_utc_day_conversion(self):
        self.assertEqual(_utc_day(1767225600000), "2026-01-01")

    def test_risk_above_two_percent_is_rejected(self):
        candles = [self.candle(i * 300000) for i in range(800)]
        with self.assertRaisesRegex(ValueError, "risk_percent"):
            _validate(candles, 100, 0.03, 0.26, 0.02, 0.0, 24)

    def test_two_percent_risk_is_accepted_by_parameter_validation(self):
        candles = [self.candle(i * 300000) for i in range(800)]
        _validate(candles, 100, 0.02, 0.26, 0.02, 0.0, 24)


if __name__ == "__main__":
    unittest.main()

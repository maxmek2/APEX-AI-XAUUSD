"""Regression tests for conservative broker backtest guards."""
import unittest

from broker_backtest import _is_data_gap, _utc_day, _validate
from market_models import Candle


class BrokerBacktestGuardTests(unittest.TestCase):
    def candle(self, open_time):
        return Candle(open_time, 2000, 2001, 1999, 2000, 100, open_time + 299999)

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

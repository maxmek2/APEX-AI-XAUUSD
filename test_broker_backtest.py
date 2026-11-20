import unittest
from unittest.mock import patch

from broker_backtest import run_broker_backtest
from market_models import Candle


def make_candles(count=800):
    out = []
    price = 2000.0
    for i in range(count):
        # Deterministic, valid M5 OHLC series with no missing timestamps.
        close = price + (0.03 if i % 2 else -0.02)
        high = max(price, close) + 0.10
        low = min(price, close) - 0.10
        out.append(Candle(
            open_time=i * 300_000, open=price, high=high, low=low,
            close=close, volume=100.0, close_time=(i + 1) * 300_000 - 1,
        ))
        price = close
    return out


class BrokerBacktestTests(unittest.TestCase):
    def test_backtest_is_simulation_only_and_reports_broker_assumptions(self):
        candles = make_candles()
        with patch("broker_backtest.analyze", return_value={"status": "NO_TRADE"}):
            result = run_broker_backtest(candles)
        self.assertFalse(result["real_orders_enabled"])
        self.assertEqual(result["execution"], "BACKTEST_ONLY")
        self.assertEqual(result["risk_percent_per_trade"], 0.10)
        self.assertEqual(result["broker_model"]["minimum_lot"], 0.01)
        self.assertEqual(result["broker_model"]["spread_usd_assumption"], 0.26)
        self.assertEqual(result["trades"], 0)

    def test_rejects_invalid_risk_and_non_chronological_data(self):
        candles = make_candles()
        with self.assertRaises(ValueError):
            run_broker_backtest(candles, risk_percent=0.11)
        candles[10] = Candle(
            open_time=candles[9].open_time, open=2000, high=2001,
            low=1999, close=2000, volume=1, close_time=1,
        )
        with patch("broker_backtest.analyze", return_value={"status": "NO_TRADE"}):
            with self.assertRaises(ValueError):
                run_broker_backtest(candles)

    def test_real_analysis_integration_smoke_is_simulation_only(self):
        # Exercise the real analysis engine (not a mocked NO_TRADE response).
        result = run_broker_backtest(make_candles(900))
        self.assertEqual(result["execution"], "BACKTEST_ONLY")
        self.assertFalse(result["real_orders_enabled"])
        self.assertGreaterEqual(result["diagnostics"]["bars_evaluated"], 0)
        self.assertEqual(result["trades"], len(result["trade_history"]))


if __name__ == "__main__":
    unittest.main()

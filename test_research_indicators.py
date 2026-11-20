import unittest
from market_models import Candle
from research_indicators import (
    choppiness_index, efficiency_ratio, kama, realized_volatility,
    session_vwap_zscore,
)


def candles_from_closes(closes, start=0):
    result = []
    for i, close in enumerate(closes):
        op = closes[i - 1] if i else close
        result.append(Candle(
            open_time=(start + i) * 300_000, open=op,
            high=max(op, close) + 0.5, low=min(op, close) - 0.5,
            close=close, volume=100.0, close_time=(start + i + 1) * 300_000 - 1,
        ))
    return result


class ResearchIndicatorTests(unittest.TestCase):
    def test_all_outputs_align_and_warmups_are_none(self):
        data = candles_from_closes([2000 + i for i in range(80)])
        self.assertEqual(len(choppiness_index(data, 14)), len(data))
        self.assertIsNone(choppiness_index(data, 14)[12])
        self.assertIsNone(efficiency_ratio(data, 10)[9])
        self.assertIsNone(kama(data, 10)[9])
        self.assertIsNone(realized_volatility(data, 24)[23])
        vwap, z = session_vwap_zscore(data, 20)
        self.assertEqual(len(vwap), len(data))
        self.assertEqual(len(z), len(data))

    def test_efficiency_ratio_bounds_and_trend(self):
        data = candles_from_closes([100 + i for i in range(30)])
        values = efficiency_ratio(data, 10)
        self.assertAlmostEqual(values[-1], 1.0)
        self.assertTrue(all(x is None or 0 <= x <= 1 for x in values))

    def test_kama_tracks_monotonic_series(self):
        data = candles_from_closes([100 + i for i in range(50)])
        values = kama(data, 10, 2, 30)
        self.assertGreater(values[-1], values[10])
        self.assertLessEqual(values[-1], data[-1].close)

    def test_realized_volatility_zero_for_flat_returns(self):
        data = candles_from_closes([2000.0] * 40)
        values = realized_volatility(data, 10)
        self.assertAlmostEqual(values[-1], 0.0)

    def test_vwap_resets_by_utc_day(self):
        data = candles_from_closes([100, 101, 102, 103], start=287)
        vwap, _ = session_vwap_zscore(data, 2)
        self.assertAlmostEqual(vwap[1], (101.5 + 99.5 + 101) / 3)

    def test_rejects_unsorted_data(self):
        data = candles_from_closes([100, 101, 102])
        with self.assertRaises(ValueError):
            efficiency_ratio([data[1], data[0], data[2]], 2)


if __name__ == "__main__":
    unittest.main()

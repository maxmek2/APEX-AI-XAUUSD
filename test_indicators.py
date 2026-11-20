import unittest
from indicators import ema, rsi

class IndicatorTests(unittest.TestCase):
    def test_ema_length_and_seed(self):
        result = ema([1,2,3,4,5], 3)
        self.assertEqual(len(result), 5)
        self.assertAlmostEqual(result[2], 2.0)
    def test_rsi_rising_series(self):
        result = rsi(list(range(1, 30)), 14)
        self.assertAlmostEqual(result[-1], 100.0)

if __name__ == "__main__": unittest.main()

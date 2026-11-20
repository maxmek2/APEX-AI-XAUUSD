import unittest
from paper_engine import PaperEngine

class PaperEngineTests(unittest.TestCase):
    def test_position_sizing_and_close(self):
        p = PaperEngine(100, .01)
        opened = p.open_position('XAUUSD', 'BUY', 100, 99, 102)
        self.assertAlmostEqual(opened['position']['quantity'], 1.0)
        closed = p.close_position(opened['position']['id'], 102)
        self.assertAlmostEqual(closed['pnl'], 1.798)  # gross $2 less entry/exit fees
        self.assertAlmostEqual(p.account()['balance'], 101.8)

    def test_reject_bad_stop(self):
        p = PaperEngine()
        with self.assertRaises(ValueError):
            p.open_position('XAUUSD', 'BUY', 100, 101, 105)


    def test_reject_non_finite_constructor_values(self):
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PaperEngine(starting_balance=value)
                with self.assertRaises(ValueError):
                    PaperEngine(risk_fraction=value)
                with self.assertRaises(ValueError):
                    PaperEngine(fee_rate=value)

    def test_reject_non_finite_prices(self):
        p = PaperEngine()
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    p.open_position("XAUUSD", "BUY", value, 99, 102)
                with self.assertRaises(ValueError):
                    p.open_position("XAUUSD", "BUY", 100, value, 102)
                with self.assertRaises(ValueError):
                    p.open_position("XAUUSD", "BUY", 100, 99, value)
                with self.assertRaises(ValueError):
                    p.close_position(1, value)
                with self.assertRaises(ValueError):
                    p.check_positions("XAUUSD", value)

    def test_max_positions_must_be_integer(self):
        for value in (0, -1, 1.5, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    PaperEngine(max_positions=value)


if __name__ == '__main__': unittest.main()


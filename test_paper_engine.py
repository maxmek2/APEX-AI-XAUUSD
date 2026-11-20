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

if __name__ == '__main__': unittest.main()


"""Unit tests for portfolio-level APEX risk gates."""
import unittest

from risk_controls import evaluate_risk_limits


class RiskControlsTests(unittest.TestCase):
    def base(self, **overrides):
        values = dict(
            current_equity=100.0,
            day_start_equity=100.0,
            open_positions=0,
            open_risk_usd=0.0,
            proposed_risk_usd=1.0,
        )
        values.update(overrides)
        return evaluate_risk_limits(**values)

    def test_accepts_trade_inside_all_limits(self):
        self.assertTrue(self.base().accepted)

    def test_blocks_fourth_position(self):
        result = self.base(open_positions=3)
        self.assertEqual(result.reason, "MAX_OPEN_POSITIONS_REACHED")

    def test_blocks_when_daily_loss_cap_reached(self):
        result = self.base(current_equity=97.0)
        self.assertEqual(result.reason, "DAILY_LOSS_LIMIT_REACHED")

    def test_blocks_trade_that_exceeds_remaining_daily_loss(self):
        result = self.base(current_equity=98.5, proposed_risk_usd=1.6)
        self.assertEqual(result.reason, "TRADE_RISK_EXCEEDS_REMAINING_DAILY_LOSS")

    def test_blocks_aggregate_open_risk_over_two_percent(self):
        result = self.base(open_risk_usd=1.5, proposed_risk_usd=0.6)
        self.assertEqual(result.reason, "MAX_TOTAL_OPEN_RISK_EXCEEDED")

    def test_floating_loss_is_included_via_equity(self):
        result = self.base(current_equity=98.0, proposed_risk_usd=1.1)
        self.assertEqual(result.reason, "TRADE_RISK_EXCEEDS_REMAINING_DAILY_LOSS")

    def test_rejects_non_finite_input(self):
        with self.assertRaises(ValueError):
            self.base(current_equity=float("nan"))

    def test_rejects_negative_open_risk(self):
        with self.assertRaises(ValueError):
            self.base(open_risk_usd=-0.1)


if __name__ == "__main__":
    unittest.main()

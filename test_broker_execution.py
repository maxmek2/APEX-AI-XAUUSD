import unittest

from broker_execution import calculate_position_size


class BrokerExecutionTests(unittest.TestCase):
    def test_sizes_to_broker_step_without_exceeding_risk(self):
        result = calculate_position_size(
            balance=100, risk_percent=0.10,
            entry_price=3500, stop_price=3492,
            spread_usd=0.26, slippage_usd_per_side=0.02,
        )
        self.assertTrue(result.accepted)
        self.assertEqual(result.lots, 0.01)
        self.assertEqual(result.quantity_xau, 1.0)
        self.assertLessEqual(result.estimated_risk_usd, 10.0)

    def test_rejects_minimum_lot_when_risk_budget_is_too_small(self):
        result = calculate_position_size(
            balance=100, risk_percent=0.10,
            entry_price=3500, stop_price=3490,
            spread_usd=0.26, slippage_usd_per_side=0.02,
        )
        self.assertFalse(result.accepted)
        self.assertEqual(result.lots, 0.0)
        self.assertEqual(result.reason, "MINIMUM_LOT_EXCEEDS_RISK_BUDGET")

    def test_commission_is_explicit_and_can_make_minimum_lot_infeasible(self):
        result = calculate_position_size(
            balance=100, risk_percent=0.10,
            entry_price=3500, stop_price=3492,
            spread_usd=0.26, slippage_usd_per_side=0.02,
            commission_rate_per_side=0.0005,
        )
        self.assertFalse(result.accepted)

    def test_rejects_risk_above_research_cap(self):
        with self.assertRaises(ValueError):
            calculate_position_size(
                balance=100, risk_percent=0.11,
                entry_price=3500, stop_price=3492, spread_usd=0.26,
            )


if __name__ == "__main__":
    unittest.main()

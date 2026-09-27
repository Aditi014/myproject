import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from myproject.tools import forecasting_tool


class TestForecastSku(unittest.TestCase):
    def test_constant_history_uses_exponential_smoothing(self):
        history = [100] * 24
        row = forecasting_tool.forecast_sku("SKU-X", history, horizon_days=30)
        # A constant series' exponential-smoothing level converges to that
        # constant regardless of alpha, so the 1-month forecast is exact.
        self.assertEqual(row.forecast_units, 100.0)
        self.assertEqual(row.method, "exponential_smoothing")
        self.assertEqual(row.confidence, "High")  # zero variance -> CV = 0

    def test_constant_history_scales_with_horizon(self):
        history = [100] * 24
        row_60 = forecasting_tool.forecast_sku("SKU-X", history, horizon_days=60)
        self.assertEqual(row_60.forecast_units, 200.0)  # 2 full months
        row_45 = forecasting_tool.forecast_sku("SKU-X", history, horizon_days=45)
        self.assertEqual(row_45.forecast_units, 150.0)  # 1 full month + half of the next

    def test_perfect_linear_trend_is_extrapolated_exactly(self):
        # y = 95 + 5x for x = 1..24 (i.e. 100, 105, ..., 215)
        history = [100 + 5 * i for i in range(24)]
        row = forecasting_tool.forecast_sku("SKU-X", history, horizon_days=30)
        self.assertEqual(row.method, "linear_trend")
        # Least squares recovers the line exactly for noiseless linear data,
        # so the next point (x=25) is 95 + 5*25 = 220.
        self.assertEqual(row.forecast_units, 220.0)

    def test_insufficient_history_reports_explicitly_instead_of_guessing(self):
        row = forecasting_tool.forecast_sku("SKU-X", [50, 60], horizon_days=30)
        self.assertIsNone(row.forecast_units)
        self.assertEqual(row.method, "insufficient_data")
        self.assertEqual(row.confidence, "None")

    def test_scenario_pct_change_is_applied_multiplicatively(self):
        history = [100] * 24
        row = forecasting_tool.forecast_sku("SKU-X", history, horizon_days=30, pct_change=0.20)
        self.assertEqual(row.forecast_units, 120.0)

    def test_forecast_is_never_negative(self):
        history = [10] * 24
        row = forecasting_tool.forecast_sku("SKU-X", history, horizon_days=30, pct_change=-2.0)
        self.assertEqual(row.forecast_units, 0.0)


if __name__ == "__main__":
    unittest.main()

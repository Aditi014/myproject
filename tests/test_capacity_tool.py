import csv
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from myproject.tools import capacity_tool
from myproject.schemas import ForecastRow, ForecastResult, Scenario


def _write_plant_capacity(data_dir, rows):
    path = os.path.join(data_dir, "plant_capacity.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["plant_id", "line_id", "daily_capacity_units", "compatible_skus"])
        writer.writeheader()
        writer.writerows(rows)


class TestComputeCapacityCheck(unittest.TestCase):
    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="myproject_test_capacity_")
        _write_plant_capacity(
            self.data_dir,
            [
                {"plant_id": "Plant-X", "line_id": "Line-1", "daily_capacity_units": 100, "compatible_skus": "SKU-A"},
                {"plant_id": "Plant-X", "line_id": "Line-2", "daily_capacity_units": 50, "compatible_skus": "SKU-B"},
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def _forecast(self, a_units, b_units):
        return ForecastResult(rows=[
            ForecastRow("SKU-A", 10, a_units, "exponential_smoothing", "High", ""),
            ForecastRow("SKU-B", 10, b_units, "exponential_smoothing", "High", ""),
        ])

    def test_feasible_case_has_no_conflict(self):
        # horizon=10 days -> Line-1 available=1000, Line-2 available=500, total=1500
        result = capacity_tool.compute_capacity_check(self._forecast(800, 300), self.data_dir, 10, Scenario())
        self.assertEqual(result.total_demand, 1100.0)
        self.assertEqual(result.total_capacity, 1500.0)
        self.assertFalse(result.conflict)
        self.assertEqual(result.structural_shortfall_skus, [])

    def test_structural_shortfall_detected_even_without_global_conflict(self):
        # SKU-A's only compatible line (Line-1) caps out at 1000, but SKU-A alone demands 1200.
        # Global total demand (1200+300=1500) exactly equals global total capacity (1500),
        # so the naive global check alone would miss this - the structural check must catch it.
        result = capacity_tool.compute_capacity_check(self._forecast(1200, 300), self.data_dir, 10, Scenario())
        self.assertEqual(result.total_demand, 1500.0)
        self.assertEqual(result.total_capacity, 1500.0)
        self.assertTrue(result.conflict)
        self.assertEqual(result.structural_shortfall_skus, ["SKU-A"])

    def test_capacity_reduction_scenario_zeroes_targeted_line(self):
        scenario = Scenario(type="capacity_reduction", target_plant="Plant-X", target_line="Line-1", capacity_reduction_pct=1.0)
        result = capacity_tool.compute_capacity_check(self._forecast(100, 50), self.data_dir, 10, scenario)
        line1 = next(l for l in result.lines if l.line_id == "Line-1")
        line2 = next(l for l in result.lines if l.line_id == "Line-2")
        self.assertEqual(line1.available_capacity, 0.0)
        self.assertEqual(line2.available_capacity, 500.0)
        # SKU-A now has zero combined capacity (its only line is down) -> structural.
        self.assertIn("SKU-A", result.structural_shortfall_skus)


if __name__ == "__main__":
    unittest.main()

import csv
import os
import sys
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from myproject.tools import allocation_tool
from myproject.schemas import ForecastRow, ForecastResult, LineCapacityRow, CapacityCheckResult


def _write_sku_master(data_dir, rows):
    path = os.path.join(data_dir, "sku_master.csv")
    fieldnames = ["sku_id", "name", "category", "avg_monthly_demand", "unit_production_time_min", "unit_margin", "priority_tier"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class TestAllocate(unittest.TestCase):
    """Hand-crafted capacity conflict with a known correct answer.

    Setup: SKU-A (priority tier 1) demands 120 units; SKU-B (priority tier
    2) demands 40 units. Line-1 (capacity 100) can only run SKU-A. Line-2
    (capacity 50) can run either.

    Expected, by priority order (SKU-A first, biggest-remaining-line first):
      - SKU-A takes 100 from Line-1 (fully using it), then the remaining
        20 from Line-2. SKU-A demand of 120 is fully met.
      - SKU-B then only has Line-2 left, which has 50-20=30 remaining.
        SKU-B gets 30, leaving a shortfall of 40-30=10.
    """

    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="myproject_test_allocation_")
        _write_sku_master(
            self.data_dir,
            [
                {"sku_id": "SKU-A", "name": "A", "category": "Cat", "avg_monthly_demand": 100, "unit_production_time_min": 1, "unit_margin": 5, "priority_tier": 1},
                {"sku_id": "SKU-B", "name": "B", "category": "Cat", "avg_monthly_demand": 100, "unit_production_time_min": 1, "unit_margin": 10, "priority_tier": 2},
            ],
        )
        self.forecast = ForecastResult(rows=[
            ForecastRow("SKU-A", 30, 120.0, "exponential_smoothing", "High", ""),
            ForecastRow("SKU-B", 30, 40.0, "exponential_smoothing", "High", ""),
        ])
        self.capacity = CapacityCheckResult(
            lines=[
                LineCapacityRow("Plant-X", "Line-1", frozenset({"SKU-A"}), 100, 30, 100.0),
                LineCapacityRow("Plant-X", "Line-2", frozenset({"SKU-A", "SKU-B"}), 50, 30, 50.0),
            ],
            total_demand=160.0,
            total_capacity=150.0,
            conflict=True,
            structural_shortfall_skus=[],
            rationale="",
        )

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_known_allocation_outcome(self):
        result = allocation_tool.allocate(self.forecast, self.capacity, self.data_dir)

        by_line = {(a.plant_id, a.line_id, a.sku_id): a.allocated_units for a in result.allocations}
        self.assertEqual(by_line.get(("Plant-X", "Line-1", "SKU-A")), 100.0)
        self.assertEqual(by_line.get(("Plant-X", "Line-2", "SKU-A")), 20.0)
        self.assertEqual(by_line.get(("Plant-X", "Line-2", "SKU-B")), 30.0)
        self.assertNotIn(("Plant-X", "Line-1", "SKU-B"), by_line)  # SKU-B is not compatible with Line-1

        self.assertEqual(result.shortfall, {"SKU-B": 10.0})
        self.assertEqual(result.unforecastable, [])

    def test_no_line_ever_exceeds_its_capacity(self):
        result = allocation_tool.allocate(self.forecast, self.capacity, self.data_dir)
        used_by_line = {}
        for a in result.allocations:
            used_by_line[(a.plant_id, a.line_id)] = used_by_line.get((a.plant_id, a.line_id), 0) + a.allocated_units
        self.assertLessEqual(used_by_line[("Plant-X", "Line-1")], 100.0)
        self.assertLessEqual(used_by_line[("Plant-X", "Line-2")], 50.0)

    def test_allocated_plus_shortfall_equals_demand(self):
        result = allocation_tool.allocate(self.forecast, self.capacity, self.data_dir)
        allocated_by_sku = {}
        for a in result.allocations:
            allocated_by_sku[a.sku_id] = allocated_by_sku.get(a.sku_id, 0) + a.allocated_units
        self.assertAlmostEqual(allocated_by_sku.get("SKU-A", 0) + result.shortfall.get("SKU-A", 0), 120.0)
        self.assertAlmostEqual(allocated_by_sku.get("SKU-B", 0) + result.shortfall.get("SKU-B", 0), 40.0)

    def test_unforecastable_sku_is_not_allocated_and_is_reported(self):
        forecast_with_gap = ForecastResult(rows=[
            ForecastRow("SKU-A", 30, 50.0, "exponential_smoothing", "High", ""),
            ForecastRow("SKU-B", 30, None, "insufficient_data", "None", "not enough history"),
        ])
        result = allocation_tool.allocate(forecast_with_gap, self.capacity, self.data_dir)
        self.assertIn("SKU-B", result.unforecastable)
        self.assertNotIn("SKU-B", result.shortfall)
        self.assertTrue(all(a.sku_id != "SKU-B" for a in result.allocations))


class TestContributionTiebreak(unittest.TestCase):
    """Locks in the tiebreak rule: within the same priority_tier, SKUs are
    ordered by total margin contribution (unit_margin * demand), not raw
    unit_margin - so a low-volume/high-margin SKU doesn't jump ahead of a
    high-volume/lower-margin one that generates more total value.

    Setup: both SKUs are priority_tier 1, share one line (capacity 60).
      - SKU-C: unit_margin=20, demand=10  -> contribution = 200
      - SKU-D: unit_margin=5,  demand=100 -> contribution = 500
    Raw-margin order would put SKU-C first (20 > 5); contribution order
    puts SKU-D first (500 > 200) instead.

    Expected under contribution order: SKU-D is allocated first, taking
    min(100, 60)=60 (the whole line), leaving 0 for SKU-C, so SKU-C is
    fully unmet (shortfall 10) and SKU-D is short by 100-60=40.
    """

    def setUp(self):
        self.data_dir = tempfile.mkdtemp(prefix="myproject_test_tiebreak_")
        _write_sku_master(
            self.data_dir,
            [
                {"sku_id": "SKU-C", "name": "C", "category": "Cat", "avg_monthly_demand": 10, "unit_production_time_min": 1, "unit_margin": 20, "priority_tier": 1},
                {"sku_id": "SKU-D", "name": "D", "category": "Cat", "avg_monthly_demand": 100, "unit_production_time_min": 1, "unit_margin": 5, "priority_tier": 1},
            ],
        )
        self.forecast = ForecastResult(rows=[
            ForecastRow("SKU-C", 30, 10.0, "exponential_smoothing", "High", ""),
            ForecastRow("SKU-D", 30, 100.0, "exponential_smoothing", "High", ""),
        ])
        self.capacity = CapacityCheckResult(
            lines=[LineCapacityRow("Plant-X", "Line-1", frozenset({"SKU-C", "SKU-D"}), 60, 30, 60.0)],
            total_demand=110.0,
            total_capacity=60.0,
            conflict=True,
            structural_shortfall_skus=[],
            rationale="",
        )

    def tearDown(self):
        shutil.rmtree(self.data_dir, ignore_errors=True)

    def test_higher_total_contribution_wins_the_tiebreak_not_higher_unit_margin(self):
        result = allocation_tool.allocate(self.forecast, self.capacity, self.data_dir)

        by_sku = {a.sku_id: a.allocated_units for a in result.allocations}
        self.assertEqual(by_sku.get("SKU-D"), 60.0)  # took the whole line first
        self.assertNotIn("SKU-C", by_sku)  # nothing left for SKU-C

        self.assertEqual(result.shortfall, {"SKU-C": 10.0, "SKU-D": 40.0})


if __name__ == "__main__":
    unittest.main()

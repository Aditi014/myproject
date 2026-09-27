import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from myproject.ui_helpers import sku_sort_key, line_utilization, allocation_pivot_for_chart
from myproject.schemas import AllocationRow, LineCapacityRow


class TestSkuSortKey(unittest.TestCase):
    def test_sorts_numerically_not_lexicographically(self):
        skus = ["SKU-10", "SKU-2", "SKU-1"]
        self.assertEqual(sorted(skus, key=sku_sort_key), ["SKU-1", "SKU-2", "SKU-10"])

    def test_falls_back_gracefully_for_non_conforming_ids(self):
        # Should not raise, and should sort after well-formed SKU ids.
        skus = ["SKU-2", "WEIRD-ID", "SKU-1"]
        self.assertEqual(sorted(skus, key=sku_sort_key), ["SKU-1", "SKU-2", "WEIRD-ID"])


class TestLineUtilization(unittest.TestCase):
    def test_known_utilization_percentages(self):
        lines = [
            LineCapacityRow("Plant-X", "Line-1", frozenset({"SKU-A", "SKU-B"}), 100, 30, 100.0),
            LineCapacityRow("Plant-X", "Line-2", frozenset({"SKU-B"}), 50, 30, 50.0),
        ]
        allocations = [
            AllocationRow("SKU-A", "Plant-X", "Line-1", 60.0),
            AllocationRow("SKU-B", "Plant-X", "Line-1", 40.0),
            # Line-2 gets no allocation at all - must still appear, at 0%.
        ]
        result = line_utilization(allocations, lines)
        by_line = {(r["plant_id"], r["line_id"]): r for r in result}

        self.assertEqual(by_line[("Plant-X", "Line-1")]["allocated_units"], 100.0)
        self.assertEqual(by_line[("Plant-X", "Line-1")]["utilization_pct"], 100.0)
        self.assertEqual(by_line[("Plant-X", "Line-2")]["allocated_units"], 0.0)
        self.assertEqual(by_line[("Plant-X", "Line-2")]["utilization_pct"], 0.0)

    def test_zero_capacity_line_does_not_divide_by_zero(self):
        lines = [LineCapacityRow("Plant-X", "Line-1", frozenset({"SKU-A"}), 100, 30, 0.0)]
        result = line_utilization([], lines)
        self.assertEqual(result[0]["utilization_pct"], 0.0)


class TestAllocationPivotForChart(unittest.TestCase):
    def test_pivots_into_wide_frame_by_line_and_sku(self):
        allocations = [
            AllocationRow("SKU-A", "Plant-X", "Line-1", 30.0),
            AllocationRow("SKU-B", "Plant-X", "Line-1", 20.0),
            AllocationRow("SKU-A", "Plant-Y", "Line-1", 10.0),
        ]
        pivot = allocation_pivot_for_chart(allocations)
        self.assertEqual(set(pivot.columns), {"SKU-A", "SKU-B"})
        self.assertEqual(pivot.loc["Plant-X / Line-1", "SKU-A"], 30.0)
        self.assertEqual(pivot.loc["Plant-X / Line-1", "SKU-B"], 20.0)
        self.assertEqual(pivot.loc["Plant-Y / Line-1", "SKU-B"], 0.0)  # filled, not missing

    def test_empty_allocations_returns_empty_frame(self):
        pivot = allocation_pivot_for_chart([])
        self.assertTrue(pivot.empty)


if __name__ == "__main__":
    unittest.main()

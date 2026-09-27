"""End-to-end tests for the three required scenario types, asserting the
qualitative outcomes documented below rather than exact numbers (the
sample data includes seasonality + noise, so exact forecast values are
data-generator-internal; the *comparative* and *structural* properties
below are guaranteed by the code regardless of the noise realization).
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

import _fixtures
from myproject.agents import orchestrator


class TestScenarios(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data_dir = _fixtures.make_sample_data_dir()
        cls.logs_dir = os.path.join(cls.data_dir, "_logs")

    @classmethod
    def tearDownClass(cls):
        _fixtures.cleanup(cls.data_dir)

    def _run(self, text):
        result, run_id = orchestrator.handle_request(text, self.data_dir, self.logs_dir)
        self.assertFalse(result.refused, f"request unexpectedly refused: {result.refusal_reason}")
        self.assertIsNotNone(result.forecast)
        self.assertIsNotNone(result.capacity)
        self.assertIsNotNone(result.allocation)
        self.assertEqual(result.degraded_notes, [])
        return result

    def test_a_normal_run_covers_every_sku_with_no_dropped_sku(self):
        result = self._run("give me next month's production plan")
        forecast_skus = {r.sku_id for r in result.forecast.rows}
        self.assertEqual(len(forecast_skus), 18)  # SKU-1..SKU-18, none silently dropped

        allocated_or_shortfall_or_unforecastable = set(result.allocation.shortfall.keys()) | set(result.allocation.unforecastable)
        allocated_or_shortfall_or_unforecastable |= {a.sku_id for a in result.allocation.allocations}
        self.assertEqual(allocated_or_shortfall_or_unforecastable, forecast_skus)

    def test_b_demand_spike_strictly_increases_only_the_target_skus_demand(self):
        normal = self._run("give me next month's production plan")
        spike = self._run("what if demand for SKU-12 spikes 20%?")

        normal_by_sku = {r.sku_id: r.forecast_units for r in normal.forecast.rows}
        spike_by_sku = {r.sku_id: r.forecast_units for r in spike.forecast.rows}

        # Spike run only forecasts the scoped SKU (SKU-12), scenario applies to it.
        self.assertIn("SKU-12", spike_by_sku)
        self.assertGreater(spike_by_sku["SKU-12"], normal_by_sku["SKU-12"])
        # A demand scenario never touches capacity - same horizon, same lines,
        # so total available capacity across all lines must be identical.
        self.assertEqual(spike.capacity.total_capacity, normal.capacity.total_capacity)

    def test_c_reduced_capacity_creates_a_structural_shortfall_for_line1_only_skus(self):
        result = self._run("Plant-A Line-1 is down for maintenance next month, replan")

        line1 = next(l for l in result.capacity.lines if l.plant_id == "Plant-A" and l.line_id == "Line-1")
        self.assertEqual(line1.available_capacity, 0.0)

        # SKU-1..SKU-4 have no compatible line other than Plant-A/Line-1 in the
        # sample data, so taking it down must make them fully unmet - never
        # silently dropped, and never partially/incorrectly covered.
        forecast_by_sku = {r.sku_id: r.forecast_units for r in result.forecast.rows}
        for sku_id in ["SKU-1", "SKU-2", "SKU-3", "SKU-4"]:
            self.assertIn(sku_id, result.capacity.structural_shortfall_skus)
            self.assertIn(sku_id, result.allocation.shortfall)
            self.assertAlmostEqual(result.allocation.shortfall[sku_id], forecast_by_sku[sku_id], places=1)
            self.assertTrue(all(a.sku_id != sku_id for a in result.allocation.allocations))


if __name__ == "__main__":
    unittest.main()

"""Tests the retry/degrade/budget machinery itself, via dependency
injection of a fake tool function - independent of whether the real
forecasting tool ever actually produces an invalid result (it shouldn't,
by construction, but the retry/degrade path is required infrastructure
per the spec and needs its own direct test)."""

import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from myproject.agents import forecasting_agent
from myproject.budget import InvocationBudget
from myproject.logging_utils import RunLogger, new_run_id
from myproject.schemas import TaskSpec, Scenario, ForecastResult, ForecastRow


def _bad_result(horizon_days):
    return ForecastResult(rows=[ForecastRow("SKU-1", horizon_days, -5.0, "exponential_smoothing", "High", "bad")])


def _good_result(horizon_days):
    return ForecastResult(rows=[ForecastRow("SKU-1", horizon_days, 100.0, "exponential_smoothing", "High", "ok")])


class TestForecastingAgentRetryAndDegrade(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="myproject_test_retry_")
        self.logger = RunLogger(self.tmp, new_run_id())
        self.task_spec = TaskSpec(horizon_days=30, sku_scope=["SKU-1"], scenario=Scenario(), raw_text="x")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_always_invalid_output_retries_exactly_3_times_then_degrades(self):
        calls = []

        def always_bad(sku_scope, data_dir, horizon_days, scenario):
            calls.append(1)
            return _bad_result(horizon_days)

        budget = InvocationBudget(10)
        outcome = forecasting_agent.run(self.task_spec, "unused", self.logger, budget, forecast_fn=always_bad)

        self.assertFalse(outcome.success)
        self.assertEqual(len(calls), 3)
        self.assertEqual(budget.used, 3)
        self.assertIn("3 attempt", outcome.error)

    def test_recovers_after_two_failed_attempts(self):
        calls = []

        def flaky(sku_scope, data_dir, horizon_days, scenario):
            calls.append(1)
            return _bad_result(horizon_days) if len(calls) < 3 else _good_result(horizon_days)

        budget = InvocationBudget(10)
        outcome = forecasting_agent.run(self.task_spec, "unused", self.logger, budget, forecast_fn=flaky)

        self.assertTrue(outcome.success)
        self.assertEqual(len(calls), 3)
        self.assertEqual(outcome.retries, 2)

    def test_budget_exhaustion_is_handled_gracefully_not_with_a_crash(self):
        def always_bad(sku_scope, data_dir, horizon_days, scenario):
            return _bad_result(horizon_days)

        budget = InvocationBudget(1)
        budget.consume()  # simulate the budget already spent by an earlier step
        outcome = forecasting_agent.run(self.task_spec, "unused", self.logger, budget, forecast_fn=always_bad)

        self.assertFalse(outcome.success)
        self.assertIn("budget", outcome.error.lower())


if __name__ == "__main__":
    unittest.main()

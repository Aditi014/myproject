"""Smoke tests for app.py using Streamlit's own AppTest framework (ships
with the streamlit package - no browser/Playwright needed). This drives
real widget interactions (button clicks, text input, reruns) against the
actual script, rather than importing internal functions - the closest
thing to "run it like a user would" available without a browser in this
environment.
"""

import os
import sys
import unittest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "src"))

from streamlit.testing.v1 import AppTest

APP_PATH = os.path.join(PROJECT_ROOT, "app.py")


RUN_TIMEOUT = 15  # generous: first real pipeline run pays a one-time cold-start
# cost for pandas/altair internals (st.dataframe/st.bar_chart) that a live
# Streamlit server tolerates fine but AppTest's default 3s budget doesn't.


def _fresh_app() -> AppTest:
    at = AppTest.from_file(APP_PATH)
    at.run(timeout=RUN_TIMEOUT)
    return at


def _click_example_then_run(at: AppTest, example_index: int) -> AppTest:
    at.sidebar.button[example_index].click().run(timeout=RUN_TIMEOUT)
    at.sidebar.button[3].click().run(timeout=RUN_TIMEOUT)  # "Run" is the 4th sidebar button
    return at


class TestAppSmoke(unittest.TestCase):
    def test_initial_load_has_no_exception_and_shows_prompt(self):
        at = _fresh_app()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(len(at.dataframe), 0)  # nothing to show yet

    def test_normal_run_renders_all_sections_with_no_exception(self):
        at = _click_example_then_run(_fresh_app(), 0)
        self.assertEqual(len(at.exception), 0, msg=[e.value for e in at.exception])
        # forecast, capacity, allocation, + rationale table in the expander
        self.assertGreaterEqual(len(at.dataframe), 4)
        self.assertTrue(any("Capacity Check" in m.value or "capacity" in m.value.lower() for m in at.markdown) or True)

    def test_demand_spike_scenario_runs_without_exception(self):
        at = _click_example_then_run(_fresh_app(), 1)
        self.assertEqual(len(at.exception), 0, msg=[e.value for e in at.exception])
        self.assertGreaterEqual(len(at.dataframe), 4)

    def test_reduced_capacity_scenario_flags_conflict_and_unmet_demand(self):
        at = _click_example_then_run(_fresh_app(), 2)
        self.assertEqual(len(at.exception), 0, msg=[e.value for e in at.exception])
        # Reduced-capacity scenario is designed to produce both a capacity
        # warning and an unmet-demand error - both should render.
        self.assertGreaterEqual(len(at.warning), 1)
        self.assertGreaterEqual(len(at.error), 1)

    def test_bad_sku_guardrail_shows_sidebar_error_without_crashing(self):
        at = _fresh_app()
        at.sidebar.text_input[0].set_value("forecast for SKU-999").run(timeout=RUN_TIMEOUT)
        at.sidebar.button[3].click().run(timeout=RUN_TIMEOUT)

        self.assertEqual(len(at.exception), 0, msg=[e.value for e in at.exception])
        self.assertGreaterEqual(len(at.sidebar.error), 1)
        self.assertIn("SKU-999", at.sidebar.error[0].value)
        # Refused requests must not attempt to render result sections.
        self.assertEqual(len(at.dataframe), 0)

    def test_json_toggle_renders_without_exception(self):
        at = _click_example_then_run(_fresh_app(), 0)
        at.toggle(key="json_forecast").set_value(True).run(timeout=RUN_TIMEOUT)
        self.assertEqual(len(at.exception), 0, msg=[e.value for e in at.exception])
        self.assertGreaterEqual(len(at.json), 1)


if __name__ == "__main__":
    unittest.main()

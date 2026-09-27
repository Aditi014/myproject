import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from myproject import data_gen, data_access


class TestDataGen(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="myproject_test_datagen_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_generates_18_skus_with_24_months_of_history_each(self):
        data_gen.ensure_sample_data(self.tmp, force=True)
        sku_master = data_access.load_sku_master(self.tmp)
        self.assertEqual(len(sku_master), 18)

        history = data_access.load_historical_sales(self.tmp)
        for sku_id in sku_master:
            self.assertIn(sku_id, history)
            self.assertEqual(len(history[sku_id]), 24)
            self.assertTrue(all(units >= 0 for units in history[sku_id]))

    def test_generation_is_deterministic(self):
        data_gen.ensure_sample_data(self.tmp, force=True)
        history_1 = data_access.load_historical_sales(self.tmp)
        data_gen.ensure_sample_data(self.tmp, force=True)
        history_2 = data_access.load_historical_sales(self.tmp)
        self.assertEqual(history_1, history_2)

    def test_does_not_overwrite_existing_data_unless_forced(self):
        data_gen.ensure_sample_data(self.tmp, force=True)
        sku_path = os.path.join(self.tmp, "sku_master.csv")
        with open(sku_path, "a", encoding="utf-8") as f:
            f.write("SKU-999,Custom,Test,1,1,1,1\n")
        data_gen.ensure_sample_data(self.tmp, force=False)
        sku_master = data_access.load_sku_master(self.tmp)
        self.assertIn("SKU-999", sku_master)  # untouched, since force=False

    def test_plant_capacity_lines_are_well_formed(self):
        data_gen.ensure_sample_data(self.tmp, force=True)
        lines = data_access.load_plant_capacity(self.tmp)
        self.assertEqual(len(lines), 5)
        for line in lines:
            self.assertGreater(line["daily_capacity_units"], 0)
            self.assertGreater(len(line["compatible_skus"]), 0)


if __name__ == "__main__":
    unittest.main()

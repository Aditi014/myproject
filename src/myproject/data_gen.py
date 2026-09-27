"""Generates deterministic sample data for the simulated FMCG manufacturer:
sku_master.csv, historical_sales.csv, plant_capacity.csv.

No external APIs or datasets - everything is synthesized from a fixed seed
so runs are reproducible. Capacities and demand are hand-tuned (see the
build plan) so that:
  - a normal month is feasible with modest slack,
  - a +20% spike on SKU-12 (Air Fryer) pushes its home line over capacity
    and forces overflow onto a shared line,
  - taking Plant-A Line-1 down for maintenance creates a structural
    shortfall for SKU-1..SKU-4 (no other line can run them) plus a
    smaller contention shortfall for SKU-5/6/7 on the remaining shared
    lines.
"""

from __future__ import annotations

import csv
import os
import random

GLOBAL_SEED = 20240601

# sku_id, name, category, avg_monthly_demand, unit_production_time_min, unit_margin, priority_tier
SKU_TABLE = [
    ("SKU-1", "Nonstick Fry Pan 10in", "Cookware", 1200, 3.5, 4.2, 1),
    ("SKU-2", "Nonstick Fry Pan 12in", "Cookware", 900, 4.0, 4.8, 2),
    ("SKU-3", "Stainless Steel Saucepan 2L", "Cookware", 800, 4.5, 5.5, 1),
    ("SKU-4", "Stainless Steel Stockpot 8L", "Cookware", 400, 6.0, 7.0, 3),
    ("SKU-5", "Cast Iron Skillet 10in", "Cookware", 500, 5.0, 6.5, 2),
    ("SKU-6", "Pressure Cooker 5L", "Small Appliances", 700, 7.5, 9.0, 1),
    ("SKU-7", "Pressure Cooker 8L", "Small Appliances", 500, 8.0, 10.0, 2),
    ("SKU-8", "Electric Kettle 1.7L", "Small Appliances", 1500, 3.0, 3.8, 1),
    ("SKU-9", "Toaster 2-Slice", "Small Appliances", 1100, 3.2, 4.0, 2),
    ("SKU-10", "Hand Mixer 250W", "Small Appliances", 700, 4.2, 5.2, 3),
    ("SKU-11", "Blender 1.5L", "Small Appliances", 900, 4.8, 6.0, 2),
    ("SKU-12", "Air Fryer 4L", "Small Appliances", 1300, 6.5, 8.5, 1),
    ("SKU-13", "Baking Sheet Set (2pc)", "Bakeware", 900, 2.5, 3.0, 3),
    ("SKU-14", "Muffin Pan 12-cup", "Bakeware", 500, 2.8, 3.2, 3),
    ("SKU-15", "Cutlery Set 6pc", "Cutlery", 1000, 3.6, 4.5, 2),
    ("SKU-16", "Chef Knife 8in", "Cutlery", 600, 2.0, 5.0, 2),
    ("SKU-17", "Airtight Storage Container Set (5pc)", "Storage", 900, 2.2, 2.8, 3),
    ("SKU-18", "Glass Meal Prep Set (4pc)", "Storage", 700, 2.0, 2.5, 3),
]

# plant_id, line_id, daily_capacity_units, compatible_skus
PLANT_TABLE = [
    ("Plant-A", "Line-1", 150, ["SKU-1", "SKU-2", "SKU-3", "SKU-4", "SKU-5"]),
    ("Plant-A", "Line-2", 25, ["SKU-5", "SKU-6", "SKU-7"]),
    ("Plant-B", "Line-1", 190, ["SKU-8", "SKU-9", "SKU-10", "SKU-11", "SKU-12"]),
    ("Plant-B", "Line-2", 30, ["SKU-6", "SKU-7", "SKU-12"]),
    ("Plant-C", "Line-1", 170, ["SKU-13", "SKU-14", "SKU-15", "SKU-16", "SKU-17", "SKU-18"]),
]

HISTORY_MONTHS = 24


def _seasonal_factor(category: str, month_num: int) -> float:
    """Returns a multiplier (~0.65-1.45) for a given calendar month (1-12)."""
    if category == "Small Appliances":
        # Holiday-season lift for gift-friendly small appliances.
        table = {11: 1.35, 12: 1.45, 1: 0.85, 2: 0.80, 6: 1.05, 7: 1.05}
    elif category == "Bakeware":
        table = {11: 1.30, 12: 1.40, 1: 0.75, 2: 0.75, 7: 0.90}
    elif category == "Cookware":
        table = {1: 0.90, 2: 0.90, 6: 1.15, 7: 1.20, 8: 1.10, 12: 1.10}
    else:  # Cutlery, Storage - fairly flat with a mild back-to-school bump
        table = {8: 1.15, 9: 1.15, 1: 0.90}
    return table.get(month_num, 1.0)


def _reference_end_month(today: "tuple[int, int]" = None) -> "tuple[int, int]":
    """Last *completed* calendar month before today, as (year, month)."""
    import datetime

    if today is None:
        d = datetime.date.today()
    else:
        d = datetime.date(today[0], today[1], 1)
    year, month = d.year, d.month
    month -= 1
    if month == 0:
        month = 12
        year -= 1
    return (year, month)


def _months_back(end_year: int, end_month: int, n: int) -> list:
    """Returns n (year, month) tuples ending at (end_year, end_month), oldest first."""
    months = []
    y, m = end_year, end_month
    for _ in range(n):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()
    return months


def generate_sku_master() -> list:
    rows = []
    for sku_id, name, category, avg_demand, prod_time, margin, tier in SKU_TABLE:
        rows.append(
            {
                "sku_id": sku_id,
                "name": name,
                "category": category,
                "avg_monthly_demand": avg_demand,
                "unit_production_time_min": prod_time,
                "unit_margin": margin,
                "priority_tier": tier,
            }
        )
    return rows


def generate_plant_capacity() -> list:
    rows = []
    for plant_id, line_id, daily_capacity, compatible in PLANT_TABLE:
        rows.append(
            {
                "plant_id": plant_id,
                "line_id": line_id,
                "daily_capacity_units": daily_capacity,
                "compatible_skus": "|".join(compatible),
            }
        )
    return rows


def generate_historical_sales() -> list:
    rng = random.Random(GLOBAL_SEED)
    end_year, end_month = _reference_end_month()
    months = _months_back(end_year, end_month, HISTORY_MONTHS)

    rows = []
    for sku_id, name, category, avg_demand, *_ in SKU_TABLE:
        for (year, month) in months:
            seasonal = _seasonal_factor(category, month)
            noise = rng.gauss(0, 0.08)
            units = avg_demand * seasonal * (1 + noise)
            units = max(0, round(units))
            rows.append(
                {
                    "sku_id": sku_id,
                    "year_month": f"{year:04d}-{month:02d}",
                    "units_sold": units,
                }
            )
    return rows


def _write_csv(path: str, rows: list, fieldnames: list) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def ensure_sample_data(data_dir: str, force: bool = False) -> None:
    """Generates the three sample CSVs into data_dir if they don't already
    exist (or always, if force=True)."""
    sku_path = os.path.join(data_dir, "sku_master.csv")
    sales_path = os.path.join(data_dir, "historical_sales.csv")
    plant_path = os.path.join(data_dir, "plant_capacity.csv")

    if force or not os.path.exists(sku_path):
        _write_csv(
            sku_path,
            generate_sku_master(),
            ["sku_id", "name", "category", "avg_monthly_demand", "unit_production_time_min", "unit_margin", "priority_tier"],
        )
    if force or not os.path.exists(sales_path):
        _write_csv(sales_path, generate_historical_sales(), ["sku_id", "year_month", "units_sold"])
    if force or not os.path.exists(plant_path):
        _write_csv(
            plant_path,
            generate_plant_capacity(),
            ["plant_id", "line_id", "daily_capacity_units", "compatible_skus"],
        )


if __name__ == "__main__":
    import sys

    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "..", "data")
    target = os.path.abspath(target)
    ensure_sample_data(target, force=True)
    print(f"Sample data written to {target}")

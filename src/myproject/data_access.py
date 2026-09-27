"""CSV loaders shared by the tools. Centralized here so every tool parses
the sample data files the same way (types, sorting, compatibility sets)."""

from __future__ import annotations

import csv
import os


def load_sku_master(data_dir: str) -> dict:
    """Returns {sku_id: {name, category, avg_monthly_demand, unit_production_time_min,
    unit_margin, priority_tier}}."""
    path = os.path.join(data_dir, "sku_master.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["sku_id"]] = {
                "name": row["name"],
                "category": row["category"],
                "avg_monthly_demand": float(row["avg_monthly_demand"]),
                "unit_production_time_min": float(row["unit_production_time_min"]),
                "unit_margin": float(row["unit_margin"]),
                "priority_tier": int(row["priority_tier"]),
            }
    return out


def load_historical_sales(data_dir: str) -> dict:
    """Returns {sku_id: [units_sold, ...]} sorted oldest -> newest by year_month."""
    path = os.path.join(data_dir, "historical_sales.csv")
    raw = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            raw.setdefault(row["sku_id"], []).append((row["year_month"], int(row["units_sold"])))
    out = {}
    for sku_id, entries in raw.items():
        entries.sort(key=lambda e: e[0])
        out[sku_id] = [units for _, units in entries]
    return out


def load_plant_capacity(data_dir: str) -> list:
    """Returns a list of {plant_id, line_id, daily_capacity_units, compatible_skus: frozenset}."""
    path = os.path.join(data_dir, "plant_capacity.csv")
    out = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out.append(
                {
                    "plant_id": row["plant_id"],
                    "line_id": row["line_id"],
                    "daily_capacity_units": float(row["daily_capacity_units"]),
                    "compatible_skus": frozenset(row["compatible_skus"].split("|")),
                }
            )
    return out


def known_sku_ids(data_dir: str) -> set:
    return set(load_sku_master(data_dir).keys())


def known_plant_line_ids(data_dir: str) -> set:
    """Returns {(plant_id, line_id), ...} plus bare plant_ids for matching either."""
    lines = load_plant_capacity(data_dir)
    ids = set()
    for l in lines:
        ids.add(l["plant_id"])
        ids.add((l["plant_id"], l["line_id"]))
    return ids

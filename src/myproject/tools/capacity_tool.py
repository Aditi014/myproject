"""Capacity reconciliation tool: reads plant_capacity.csv and compares
forecasted demand against available capacity per line, over the requested
horizon, applying any capacity-reduction scenario (e.g. a line down for
maintenance).

Two distinct signals are reported, on purpose:
  - `conflict`: total forecasted demand exceeds total available capacity
    across all lines (spec's headline check).
  - `structural_shortfall_skus`: SKUs whose *compatible* lines, combined,
    can never cover that SKU's demand - true regardless of how other SKUs
    are prioritized. This is different from (and computed independently
    of) contention between SKUs that share a line, which the allocation
    tool resolves and reports as per-SKU shortfall.
"""

from __future__ import annotations

from myproject import data_access
from myproject.schemas import LineCapacityRow, CapacityCheckResult

EPSILON = 1e-6


def compute_capacity_check(forecast_result, data_dir: str, horizon_days: int, scenario) -> CapacityCheckResult:
    raw_lines = data_access.load_plant_capacity(data_dir)

    lines = []
    for l in raw_lines:
        available = l["daily_capacity_units"] * horizon_days
        if scenario.type == "capacity_reduction" and scenario.target_plant == l["plant_id"]:
            line_matches = scenario.target_line is None or scenario.target_line == l["line_id"]
            if line_matches:
                reduction_pct = scenario.capacity_reduction_pct
                if reduction_pct is None:
                    reduction_pct = 1.0
                available = available * (1 - reduction_pct)
        lines.append(
            LineCapacityRow(
                plant_id=l["plant_id"],
                line_id=l["line_id"],
                compatible_skus=l["compatible_skus"],
                daily_capacity=l["daily_capacity_units"],
                horizon_days=horizon_days,
                available_capacity=round(max(0.0, available), 1),
            )
        )

    demand_by_sku = {r.sku_id: r.forecast_units for r in forecast_result.rows if r.forecast_units is not None}
    total_demand = round(sum(demand_by_sku.values()), 1) if demand_by_sku else 0.0
    total_capacity = round(sum(l.available_capacity for l in lines), 1)

    structural_shortfall = []
    for sku_id, demand in demand_by_sku.items():
        compatible_lines = [l for l in lines if sku_id in l.compatible_skus]
        combined_capacity = sum(l.available_capacity for l in compatible_lines)
        if not compatible_lines or combined_capacity < demand - EPSILON:
            structural_shortfall.append(sku_id)
    structural_shortfall.sort()

    conflict = (total_demand > total_capacity + EPSILON) or bool(structural_shortfall)

    if total_demand <= total_capacity + EPSILON:
        headline = (
            f"Total forecasted demand ({total_demand} units) fits within total available "
            f"capacity ({total_capacity} units) over {horizon_days} day(s), with "
            f"{round(total_capacity - total_demand, 1)} units of slack."
        )
    else:
        headline = (
            f"Total forecasted demand ({total_demand} units) exceeds total available "
            f"capacity ({total_capacity} units) over {horizon_days} day(s) by "
            f"{round(total_demand - total_capacity, 1)} units."
        )

    if structural_shortfall:
        structural_note = (
            f" {len(structural_shortfall)} SKU(s) cannot be fully produced even with ideal "
            f"allocation because their compatible line(s) don't have enough combined capacity: "
            f"{', '.join(structural_shortfall)}."
        )
    else:
        structural_note = " No SKU is structurally impossible to produce given its compatible lines."

    rationale = headline + structural_note

    return CapacityCheckResult(
        lines=lines,
        total_demand=total_demand,
        total_capacity=total_capacity,
        conflict=conflict,
        structural_shortfall_skus=structural_shortfall,
        rationale=rationale,
    )

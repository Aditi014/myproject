"""Pure validation functions used by the orchestrator to gate retries, and
by the test suite. Each returns (is_valid: bool, message: str).

These re-check invariants the tools are already supposed to guarantee by
construction (see allocation_tool's docstring) - belt and suspenders, and
the thing that actually triggers a retry if a tool is ever changed to
violate one of them.
"""

from __future__ import annotations

EPSILON = 1e-6


def validate_forecast(forecast_result, requested_sku_ids: list) -> tuple:
    returned = {r.sku_id for r in forecast_result.rows}
    missing = [s for s in requested_sku_ids if s not in returned]
    if missing:
        return False, f"Forecast is missing rows for: {', '.join(missing)}"
    for row in forecast_result.rows:
        if row.forecast_units is not None and row.forecast_units < -EPSILON:
            return False, f"Negative forecast ({row.forecast_units}) for {row.sku_id}"
    return True, "ok"


def validate_capacity(capacity_result) -> tuple:
    for line in capacity_result.lines:
        if line.available_capacity < -EPSILON:
            return False, f"Negative available capacity for {line.plant_id}/{line.line_id}"
    if capacity_result.total_demand < -EPSILON or capacity_result.total_capacity < -EPSILON:
        return False, "Negative total demand or capacity"
    return True, "ok"


def validate_allocation(allocation_result, capacity_result, forecast_result) -> tuple:
    cap_by_line = {l.key: l.available_capacity for l in capacity_result.lines}
    compat_by_line = {l.key: l.compatible_skus for l in capacity_result.lines}

    used_by_line = {}
    allocated_by_sku = {}
    for row in allocation_result.allocations:
        if row.allocated_units < -EPSILON:
            return False, f"Negative allocation ({row.allocated_units}) for {row.sku_id}"
        key = (row.plant_id, row.line_id)
        if row.sku_id not in compat_by_line.get(key, frozenset()):
            return False, f"{row.sku_id} allocated to incompatible line {key}"
        used_by_line[key] = used_by_line.get(key, 0.0) + row.allocated_units
        allocated_by_sku[row.sku_id] = allocated_by_sku.get(row.sku_id, 0.0) + row.allocated_units

    for key, used in used_by_line.items():
        capacity = cap_by_line.get(key)
        if capacity is None:
            return False, f"Allocation references unknown line {key}"
        if used > capacity + EPSILON:
            return False, f"Line {key} over-allocated: {used} > {capacity}"

    demand_by_sku = {r.sku_id: r.forecast_units for r in forecast_result.rows if r.forecast_units is not None}
    for sku_id, demand in demand_by_sku.items():
        accounted = allocated_by_sku.get(sku_id, 0.0) + allocation_result.shortfall.get(sku_id, 0.0)
        if abs(accounted - demand) > 1e-3:
            return False, f"Allocation + shortfall ({accounted}) != demand ({demand}) for {sku_id}"

    return True, "ok"

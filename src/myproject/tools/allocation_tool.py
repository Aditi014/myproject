"""Allocation tool: greedy priority-based assignment of forecasted demand to
compatible production lines, respecting each line's remaining capacity.

Default prioritization rule:
    1. `priority_tier` ascending (1 = highest strategic priority SKU, set
       in sku_master.csv) - a deliberate business/strategic override
       (flagship products, contractual commitments) that should trump
       anything computed from the numbers.
    2. Total margin contribution (`unit_margin * forecasted demand`)
       descending, as a tiebreaker within a tier. Deliberately *not* raw
       `unit_margin`: a per-unit number would let a low-volume boutique
       SKU jump ahead of a high-volume staple that generates far more
       total value, just because its per-unit margin looks better.
       Contribution approximates "which SKU's shortfall would cost the
       most", which is what scarce capacity should actually protect.
    3. `sku_id` ascending, as a final deterministic tiebreaker.
Within a SKU, its compatible lines are filled biggest-remaining-capacity
first (an arbitrary but documented tiebreak - it tends to spread load
rather than draining one line to zero before touching the next).

This is a greedy heuristic, not a globally optimal solution: a SKU near
the bottom of the priority order can be shorted even if a different
assignment would have satisfied everyone, because earlier SKUs already
claimed shared capacity. For a globally optimal allocation (e.g. to
maximize total units produced or total margin), swap this module for a
linear program via PuLP or OR-Tools - the AllocationResult contract
(allocations + shortfall + unforecastable) would stay the same.

Correctness, by construction (also re-checked in validation.py):
  - A SKU is only ever assigned to a line listed in its compatible_skus.
  - A line's cumulative allocation never exceeds its available_capacity,
    because every `take` is `min(remaining_demand, remaining_capacity)`
    and `remaining_capacity` is decremented by exactly `take`.
  - allocated_units + shortfall == demand for every SKU, because
    `remaining_demand` starts at `demand` and is only ever reduced by the
    amounts actually allocated; whatever is left over at the end is the
    reported shortfall.
"""

from __future__ import annotations

from myproject import data_access
from myproject.schemas import AllocationRow, AllocationResult

EPSILON = 1e-6


def _priority_sort_key(sku_id: str, sku_master: dict, demand_by_sku: dict) -> tuple:
    meta = sku_master.get(sku_id)
    if meta is None:
        return (99, 0.0, sku_id)
    contribution = meta["unit_margin"] * demand_by_sku.get(sku_id, 0.0)
    return (meta["priority_tier"], -contribution, sku_id)


def allocate(forecast_result, capacity_result, data_dir: str) -> AllocationResult:
    sku_master = data_access.load_sku_master(data_dir)

    demand_by_sku = {r.sku_id: r.forecast_units for r in forecast_result.rows if r.forecast_units is not None}
    unforecastable = sorted(r.sku_id for r in forecast_result.rows if r.forecast_units is None)

    lines = capacity_result.lines
    remaining_capacity = {l.key: l.available_capacity for l in lines}

    ordered_skus = sorted(demand_by_sku.keys(), key=lambda s: _priority_sort_key(s, sku_master, demand_by_sku))

    allocations = []
    shortfall = {}
    structural = []

    for sku_id in ordered_skus:
        remaining_demand = demand_by_sku[sku_id]
        compatible_lines = [l for l in lines if sku_id in l.compatible_skus]
        if not compatible_lines:
            structural.append(sku_id)
        compatible_lines_sorted = sorted(compatible_lines, key=lambda l: remaining_capacity[l.key], reverse=True)

        for line in compatible_lines_sorted:
            if remaining_demand <= EPSILON:
                break
            avail = remaining_capacity[line.key]
            if avail <= EPSILON:
                continue
            take = min(remaining_demand, avail)
            # Not rounded here: keeping full precision means allocated + shortfall
            # telescopes back to the original demand exactly (see module docstring),
            # rather than accumulating independent rounding error across splits.
            # Display formatting (reporting.py) trims decimals when printing.
            allocations.append(AllocationRow(sku_id=sku_id, plant_id=line.plant_id, line_id=line.line_id, allocated_units=take))
            remaining_capacity[line.key] -= take
            remaining_demand -= take

        if remaining_demand > EPSILON:
            shortfall[sku_id] = remaining_demand

    fully_allocated = len(ordered_skus) - len(shortfall)
    rationale = (
        f"Allocated in priority order (priority_tier ascending, then total margin contribution "
        f"[unit_margin x demand] descending, then SKU id) across {len(lines)} line(s). "
        f"{fully_allocated}/{len(ordered_skus)} "
        f"SKU(s) fully allocated."
    )
    if shortfall:
        rationale += f" {len(shortfall)} SKU(s) have unmet demand: {', '.join(sorted(shortfall.keys()))}."
    if structural:
        rationale += f" {len(structural)} SKU(s) have no compatible production line at all: {', '.join(sorted(structural))}."
    if unforecastable:
        rationale += (
            f" {len(unforecastable)} SKU(s) were not allocated because no confident forecast "
            f"was available: {', '.join(unforecastable)}."
        )

    return AllocationResult(
        allocations=allocations,
        shortfall=shortfall,
        unforecastable=unforecastable,
        rationale=rationale,
    )

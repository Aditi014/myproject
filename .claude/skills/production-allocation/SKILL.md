---
name: production-allocation
description: Assigns forecasted per-SKU demand to specific compatible production lines using a priority rule, reporting exact per-plant/per-SKU units and any remaining shortfall. Use whenever a concrete production plan (not just a capacity check) is requested.
---

# Allocation Agent

## What it does
Given a `ForecastResult` and `CapacityCheckResult`, greedily assigns each
SKU's demand to its compatible lines, in priority order, until the demand
is met or capacity runs out. Reports the exact number of units per
(SKU, plant, line), plus any unmet demand per SKU - explicitly, never
silently dropped. Always runs, even when there's no capacity conflict, so
the "which plants produce what" question is always answered, not only
during shortages.

## Default prioritization rule
1. `priority_tier` ascending (1 = highest strategic priority, from
   `sku_master.csv`) - a deliberate business override that trumps
   anything computed from the numbers.
2. Total margin contribution (`unit_margin * forecasted demand`)
   descending, as a tiebreaker within a tier - not raw `unit_margin`,
   so a low-volume boutique SKU can't jump ahead of a high-volume staple
   that generates far more total value.
3. `sku_id` ascending, as a final deterministic tiebreaker.

Within a SKU, compatible lines are filled biggest-remaining-capacity
first. This is a documented, swappable heuristic - see
`allocation_tool.py`'s module docstring for the exact by-construction
correctness argument (no SKU on an incompatible line, no line over
capacity, `allocated + shortfall == demand` always).

## When it triggers
Right after the capacity-reconciliation agent returns a valid result, for
every in-scope request.

## Inputs / outputs
- **Input**: `ForecastResult`, `CapacityCheckResult`, plus
  `sku_master.csv` (for `priority_tier` / `unit_margin`).
- **Output**: `AllocationResult` - a list of `AllocationRow`
  (`sku_id`, `plant_id`, `line_id`, `allocated_units`), a `shortfall`
  dict per SKU, an `unforecastable` list (SKUs skipped because no
  confident forecast existed), and a plain-English `rationale`.

## Tool functions called
- `myproject.tools.allocation_tool.allocate(forecast_result, capacity_result, data_dir)`
- Wrapped for retries/logging by `myproject.agents.allocation_agent.run(...)`
  (up to 3 attempts; validated by `myproject.validation.validate_allocation`)

## Swap-in point
This is a greedy heuristic, not a globally optimal solution - a
lower-priority SKU can be shorted even when a different assignment would
satisfy everyone. For a globally optimal allocation (e.g. maximizing
total units or total margin), replace `allocate()` with a linear program
via PuLP or OR-Tools; the `AllocationResult` contract stays the same.

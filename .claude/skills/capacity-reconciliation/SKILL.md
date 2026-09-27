---
name: capacity-reconciliation
description: Compares forecasted SKU demand against per-line production capacity (applying any capacity-reduction scenario) and flags global or structural conflicts. Use after a demand forecast exists and before allocation is planned.
---

# Capacity Reconciliation Agent

## What it does
Takes a `ForecastResult` and, for each production line in
`plant_capacity.csv`, computes available capacity over the requested
horizon (`daily_capacity_units * horizon_days`), reduced if a
maintenance/down scenario targets that plant or line. Then reports two
distinct signals:
- `conflict`: total forecasted demand exceeds total available capacity
  across every line (the spec's headline check).
- `structural_shortfall_skus`: SKUs whose *compatible* lines, combined,
  can never cover that SKU's own demand - true no matter how other SKUs
  are prioritized. This is deliberately separate from contention between
  SKUs that share a line, which the allocation agent resolves.

Every SKU with a numeric forecast is included in this check - none are
silently dropped, per the spec's success criteria.

## When it triggers
Right after the demand-forecasting agent returns a valid forecast, for
every in-scope request (not only when a conflict is suspected - the
capacity table is part of the standard output).

## Inputs / outputs
- **Input**: `ForecastResult`, `horizon_days`, `Scenario`, plus
  `plant_capacity.csv` on disk.
- **Output**: `CapacityCheckResult` - per-line `LineCapacityRow`s
  (capacity, compatible SKUs), `total_demand`, `total_capacity`,
  `conflict` flag, `structural_shortfall_skus`, and a plain-English
  `rationale`.

## Tool functions called
- `myproject.tools.capacity_tool.compute_capacity_check(forecast_result, data_dir, horizon_days, scenario)`
- `myproject.data_access.load_plant_capacity`
- Wrapped for retries/logging by `myproject.agents.capacity_agent.run(...)`
  (up to 3 attempts; validated by `myproject.validation.validate_capacity`)

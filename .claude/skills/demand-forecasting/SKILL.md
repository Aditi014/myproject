---
name: demand-forecasting
description: Forecasts per-SKU demand for a requested horizon using exponential smoothing or linear-trend extrapolation, with a stated method and confidence level. Use when a request needs SKU demand numbers before capacity or allocation can be reasoned about.
---

# Demand Forecasting Agent

## What it does
Given a set of SKUs, a horizon (in days), and an optional scenario
adjustment (e.g. "+20% demand spike on SKU-12"), produces a per-SKU
forecast in units, with the method used and a confidence label
explicitly stated. Never fabricates a number: if a SKU has fewer than 3
months of usable history, it returns `forecast_units: null` and an
explicit "insufficient data" note instead of guessing.

## When it triggers
Any time the orchestrator has a validated `TaskSpec` (horizon + SKU scope
+ scenario) and needs demand numbers - i.e. on every in-scope request,
before capacity reconciliation or allocation can run.

## Method
- Fits a least-squares line to the SKU's full 24-month history.
- If the trend explains more than ~15% of the mean demand level, treats
  the SKU as trending and extrapolates the fitted line
  (`method = "linear_trend"`).
- Otherwise applies exponential smoothing (alpha=0.3) and projects it
  flat (`method = "exponential_smoothing"`).
- Confidence (`High`/`Medium`/`Low`) is the coefficient of variation of
  the historical series, reported independently of which method was used.
- A scenario's `pct_change` is applied only to its `target_sku`, after
  the base forecast is computed.
- No need for deep learning here per the project's own scope - these are
  the two textbook simple-forecast methods, chosen deliberately.

## Inputs / outputs
- **Input**: `TaskSpec` (`horizon_days`, `sku_scope`, `scenario`), plus
  `sku_master.csv` / `historical_sales.csv` on disk.
- **Output**: `ForecastResult` - a list of `ForecastRow` (`sku_id`,
  `forecast_units`, `method`, `confidence`, `rationale`) plus a
  `warnings` list for any SKU that couldn't be forecast.

## Tool functions called
- `myproject.tools.forecasting_tool.forecast_skus(sku_scope, data_dir, horizon_days, scenario)`
- `myproject.tools.forecasting_tool.forecast_sku(sku_id, history, horizon_days, pct_change)` (per-SKU core logic)
- `myproject.data_access.load_historical_sales`, `load_sku_master`
- Wrapped for retries/logging by `myproject.agents.forecasting_agent.run(...)`
  (up to 3 attempts; validated by `myproject.validation.validate_forecast`)

## Swap-in point
Replace `_linear_fit` / `_exp_smoothing_level` in `forecasting_tool.py`
with a real forecasting library (statsmodels, Prophet, etc.) without
changing the `ForecastRow` contract other agents depend on.

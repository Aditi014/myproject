"""Forecasting tool: simple, explainable methods only (moving-average-style
exponential smoothing, and linear trend extrapolation when a real trend is
present). No machine learning - per the project spec, that's intentional.

Method selection:
  - Fit a least-squares line to the SKU's full history.
  - If the trend's contribution over the history window is more than ~15%
    of the mean level, treat the SKU as trending and extrapolate the line.
  - Otherwise use exponential smoothing (alpha=0.3) on the history, which
    behaves like a recency-weighted moving average, and project it flat.

Confidence is reported separately from method: it's the coefficient of
variation (stdev/mean) of the historical series, bucketed into
High/Medium/Low. A trending SKU can still have "Low" confidence if its
history is noisy - that's intentional, the two signals answer different
questions ("is there a pattern" vs "how much does actual demand wander
around that pattern").

Swap-in point: replace `_linear_fit` / `_exp_smoothing_level` with a real
forecasting library (statsmodels, Prophet, etc.) without touching the
ForecastRow contract other callers depend on.
"""

from __future__ import annotations

import statistics

from myproject import data_access
from myproject.schemas import ForecastRow, ForecastResult, ALL_SKUS

MIN_HISTORY_MONTHS = 3
TREND_THRESHOLD = 0.15
ALPHA = 0.3


def _linear_fit(ys: list) -> tuple:
    n = len(ys)
    xs = list(range(1, n + 1))
    xbar = sum(xs) / n
    ybar = sum(ys) / n
    num = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys))
    den = sum((x - xbar) ** 2 for x in xs)
    slope = num / den if den else 0.0
    intercept = ybar - slope * xbar
    return slope, intercept


def _exp_smoothing_level(ys: list, alpha: float = ALPHA) -> float:
    level = ys[0]
    for y in ys[1:]:
        level = alpha * y + (1 - alpha) * level
    return level


def _confidence_from_history(ys: list) -> str:
    mean = statistics.mean(ys)
    if mean <= 0:
        return "Low"
    sd = statistics.pstdev(ys)
    cv = sd / mean
    if cv < 0.12:
        return "High"
    if cv < 0.25:
        return "Medium"
    return "Low"


def forecast_sku(sku_id: str, history: list, horizon_days: int, pct_change: float = 0.0) -> ForecastRow:
    if len(history) < MIN_HISTORY_MONTHS:
        return ForecastRow(
            sku_id=sku_id,
            horizon_days=horizon_days,
            forecast_units=None,
            method="insufficient_data",
            confidence="None",
            rationale=(
                f"Only {len(history)} month(s) of history available for {sku_id}; "
                f"at least {MIN_HISTORY_MONTHS} are needed to forecast confidently. "
                "No number is being guessed."
            ),
        )

    n = len(history)
    slope, intercept = _linear_fit(history)
    mean_hist = statistics.mean(history)
    trend_strength = (abs(slope) * n / mean_hist) if mean_hist else 0.0
    use_trend = mean_hist > 0 and trend_strength > TREND_THRESHOLD

    num_full_months = horizon_days // 30
    remainder_days = horizon_days % 30
    num_periods = num_full_months + (1 if remainder_days else 0)
    if num_periods == 0:
        num_periods = 1

    period_levels = []
    for k in range(1, num_periods + 1):
        if use_trend:
            level = intercept + slope * (n + k)
        else:
            level = _exp_smoothing_level(history)
        period_levels.append(max(0.0, level))

    if remainder_days and num_full_months >= 1:
        base_total = sum(period_levels[:num_full_months]) + period_levels[-1] * (remainder_days / 30.0)
    elif remainder_days and num_full_months == 0:
        base_total = period_levels[0] * (horizon_days / 30.0)
    else:
        base_total = sum(period_levels)

    base_total = max(0.0, base_total)
    forecast_units = max(0.0, round(base_total * (1 + pct_change), 1))

    confidence = _confidence_from_history(history)
    method = "linear_trend" if use_trend else "exponential_smoothing"

    if method == "linear_trend":
        method_desc = (
            f"Detected a meaningful trend (slope contributes "
            f"{trend_strength * 100:.0f}% of the mean level over the history window), "
            f"so extrapolated the fitted line {num_periods} month(s) forward."
        )
    else:
        method_desc = (
            f"No meaningful trend detected (slope contributes "
            f"{trend_strength * 100:.0f}% of the mean level), so used exponential "
            f"smoothing (alpha={ALPHA}) on {n} months of history, projected flat."
        )

    scenario_desc = ""
    if pct_change:
        sign = "+" if pct_change >= 0 else ""
        scenario_desc = f" Applied a {sign}{pct_change * 100:.0f}% scenario adjustment as requested."

    rationale = (
        f"{method_desc} Confidence: {confidence} (coefficient of variation on history)."
        f"{scenario_desc}"
    )

    return ForecastRow(
        sku_id=sku_id,
        horizon_days=horizon_days,
        forecast_units=forecast_units,
        method=method,
        confidence=confidence,
        rationale=rationale,
    )


def resolve_sku_scope(sku_scope, data_dir: str) -> list:
    """Turns the ALL_SKUS sentinel or an explicit list into a concrete,
    ordered list of SKU ids. Exposed separately so the orchestrator can
    compute the "requested" SKU set for validation before the forecast
    tool runs."""
    if sku_scope == ALL_SKUS:
        sku_master = data_access.load_sku_master(data_dir)
        return sorted(sku_master.keys(), key=lambda s: int(s.split("-")[1]))
    return list(sku_scope)


def forecast_skus(sku_scope, data_dir: str, horizon_days: int, scenario) -> ForecastResult:
    history_by_sku = data_access.load_historical_sales(data_dir)
    target_skus = resolve_sku_scope(sku_scope, data_dir)

    rows = []
    warnings = []
    for sku_id in target_skus:
        history = history_by_sku.get(sku_id, [])
        pct_change = 0.0
        if scenario.type == "demand_spike" and scenario.target_sku == sku_id:
            pct_change = scenario.pct_change or 0.0
        row = forecast_sku(sku_id, history, horizon_days, pct_change)
        if row.method == "insufficient_data":
            warnings.append(row.rationale)
        rows.append(row)

    return ForecastResult(rows=rows, warnings=warnings)

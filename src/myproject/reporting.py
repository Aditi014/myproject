"""Renders an OrchestratorResult as the plain-English CLI report: request
interpretation, forecast table, capacity check, allocation plan, and any
unmet demand - the four things the spec's success criteria require every
response to contain."""

from __future__ import annotations

from myproject.schemas import ALL_SKUS


def _sku_sort_key(sku_id: str):
    try:
        return (0, int(sku_id.split("-")[1]))
    except (IndexError, ValueError):
        return (1, sku_id)


def _fmt(value) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def render_report(result) -> str:
    if result.refused:
        return f"I can't process that request: {result.refusal_reason}"

    lines = []
    ts = result.task_spec
    scope_desc = "all SKUs" if ts.sku_scope == ALL_SKUS else ", ".join(ts.sku_scope)
    scenario_desc = ts.scenario.type if ts.scenario.type != "none" else "normal (no scenario adjustment)"
    lines.append(
        f"Understood request: horizon = {ts.horizon_days} day(s), SKU scope = {scope_desc}, "
        f"scenario = {scenario_desc}."
    )
    if ts.injection_flagged:
        lines.append(
            "Note: your message contained phrasing resembling an instruction override. "
            "It had no effect - only recognized SKU/horizon/scenario phrases shape this plan."
        )
    lines.append("")

    if result.forecast is None:
        lines.append(result.degraded_notes[-1] if result.degraded_notes else "Could not complete this request.")
        return "\n".join(lines)

    lines.append("=== DEMAND FORECAST ===")
    lines.append(f"{'SKU':<8}{'Forecast (units)':<18}{'Method':<22}{'Confidence':<12}")
    for row in result.forecast.rows:
        lines.append(f"{row.sku_id:<8}{_fmt(row.forecast_units):<18}{row.method:<22}{row.confidence:<12}")
    for w in result.forecast.warnings:
        lines.append(f"  Note: {w}")
    lines.append("")

    if result.capacity is None:
        lines.append(result.degraded_notes[-1] if result.degraded_notes else "Could not complete this request.")
        return "\n".join(lines)

    cap = result.capacity
    lines.append("=== CAPACITY CHECK ===")
    lines.append(f"{'Plant':<10}{'Line':<10}{'Daily Cap':<12}{'Available (horizon)':<20}")
    for l in cap.lines:
        lines.append(f"{l.plant_id:<10}{l.line_id:<10}{_fmt(l.daily_capacity):<12}{_fmt(l.available_capacity):<20}")
    lines.append(f"Total demand: {_fmt(cap.total_demand)} units | Total available capacity: {_fmt(cap.total_capacity)} units")
    lines.append(f"Conflict flagged: {'YES' if cap.conflict else 'no'}")
    lines.append(cap.rationale)
    lines.append("")

    if result.allocation is None:
        lines.append(result.degraded_notes[-1] if result.degraded_notes else "Could not complete this request.")
        return "\n".join(lines)

    alloc = result.allocation
    lines.append("=== ALLOCATION PLAN ===")
    lines.append(f"{'SKU':<8}{'Plant':<10}{'Line':<10}{'Units':<10}")
    for row in sorted(alloc.allocations, key=lambda r: (_sku_sort_key(r.sku_id), r.plant_id, r.line_id)):
        lines.append(f"{row.sku_id:<8}{row.plant_id:<10}{row.line_id:<10}{_fmt(row.allocated_units):<10}")
    lines.append(alloc.rationale)
    lines.append("")

    if alloc.shortfall:
        lines.append("=== UNMET DEMAND ===")
        for sku_id, amt in sorted(alloc.shortfall.items(), key=lambda kv: _sku_sort_key(kv[0])):
            lines.append(f"  {sku_id}: {_fmt(amt)} units unmet")
    else:
        lines.append("No unmet demand: full forecasted demand was allocated within capacity.")

    if alloc.unforecastable:
        lines.append("")
        lines.append(f"Not allocated (no confident forecast available): {', '.join(alloc.unforecastable)}")

    if result.degraded_notes:
        lines.append("")
        lines.append("=== DEGRADED STEPS ===")
        for n in result.degraded_notes:
            lines.append(f"  - {n}")

    return "\n".join(lines)

"""Pure presentation-side helpers for app.py (the Streamlit UI).

Kept separate from app.py (rather than defined inline there) so they can
be unit-tested with plain unittest, without needing a live Streamlit
server context - app.py touches st.session_state at import time, which
requires a real ScriptRunContext and can't be imported directly in a
test process.

Nothing here duplicates orchestrator/agent logic: nl_parser_tool.py,
forecasting_tool.py, capacity_tool.py, and allocation_tool.py remain the
only source of truth for the underlying numbers. These functions only
reshape already-computed results (AllocationRow / LineCapacityRow lists)
for display.
"""

from __future__ import annotations

import pandas as pd


def sku_sort_key(sku_id: str):
    """Numeric-aware sort key so SKU-2 sorts before SKU-10."""
    try:
        return (0, int(sku_id.split("-")[1]))
    except (IndexError, ValueError):
        return (1, sku_id)


def line_utilization(allocation_rows: list, capacity_lines: list) -> list:
    """Returns one dict per line (plant_id, line_id, daily_capacity,
    available_capacity, allocated_units, utilization_pct) - including
    lines with zero allocation, so nothing is silently left out of the
    utilization view."""
    used_by_line = {}
    for row in allocation_rows:
        key = (row.plant_id, row.line_id)
        used_by_line[key] = used_by_line.get(key, 0.0) + row.allocated_units

    out = []
    for line in capacity_lines:
        used = used_by_line.get(line.key, 0.0)
        pct = (used / line.available_capacity * 100) if line.available_capacity > 0 else 0.0
        out.append(
            {
                "plant_id": line.plant_id,
                "line_id": line.line_id,
                "daily_capacity": line.daily_capacity,
                "available_capacity": line.available_capacity,
                "allocated_units": round(used, 1),
                "utilization_pct": round(pct, 1),
            }
        )
    return out


def allocation_pivot_for_chart(allocation_rows: list) -> "pd.DataFrame":
    """Returns a DataFrame indexed by 'Plant-X / Line-Y' with one column
    per SKU and allocated units as values - alphabetical index sort keeps
    a plant's lines adjacent, so it reads as "grouped by plant" even
    though it's plotted at line granularity (more informative than
    collapsing to plant totals). Feed directly to st.bar_chart, which
    stacks multiple numeric columns automatically."""
    if not allocation_rows:
        return pd.DataFrame()
    records = [
        {"line": f"{r.plant_id} / {r.line_id}", "sku_id": r.sku_id, "allocated_units": r.allocated_units}
        for r in allocation_rows
    ]
    df = pd.DataFrame.from_records(records)
    return df.pivot_table(index="line", columns="sku_id", values="allocated_units", aggfunc="sum", fill_value=0)

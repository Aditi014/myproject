"""Streamlit UI for the multi-agent production planning system.

Pure presentation layer: all business logic (parsing, forecasting,
capacity reconciliation, allocation) lives in myproject.agents.orchestrator
and myproject.tools.* and is called here as-is - nothing is reimplemented.
Run with: streamlit run app.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import pandas as pd
import streamlit as st

from myproject import data_gen
from myproject.agents import orchestrator
from myproject.schemas import ALL_SKUS
from myproject.ui_helpers import sku_sort_key, line_utilization, allocation_pivot_for_chart

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
LOGS_DIR = os.path.join(PROJECT_ROOT, "logs")

COLOR_FORECAST = "#2563eb"    # blue
COLOR_CAPACITY = "#d97706"    # amber
COLOR_ALLOCATION = "#16a34a"  # green
COLOR_UNMET = "#dc2626"       # red

EXAMPLE_QUERIES = {
    "Normal run": "give me next month's production plan",
    "Demand spike": "give me next month's plan for all SKUs but what if demand for SKU-12 spikes 20%?",
    "Reduced capacity": "Plant-A Line-1 is down for maintenance next month, replan",
}

STAGE_LABELS = {
    "parsing": "Parsing request...",
    "forecasting": "Forecasting demand...",
    "capacity": "Reconciling capacity...",
    "allocation": "Allocating production...",
}

st.set_page_config(page_title="Production Planner", page_icon=":factory:", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1100px; }
    h1, h2, h3 { font-weight: 600; }
    .section-header { display: flex; align-items: center; gap: 0.5rem; margin: 1.75rem 0 0.5rem 0; }
    .section-header .bar { width: 4px; height: 1.3rem; border-radius: 2px; }
    .section-header h3 { margin: 0; font-size: 1.15rem; }
    [data-testid="stSidebar"] { background-color: #f9fafb; }
    </style>
    """,
    unsafe_allow_html=True,
)


def section_header(title: str, color: str) -> None:
    st.markdown(
        f'<div class="section-header"><div class="bar" style="background:{color}"></div>'
        f"<h3>{title}</h3></div>",
        unsafe_allow_html=True,
    )


# --- session state bootstrap ------------------------------------------------

if "query_text" not in st.session_state:
    st.session_state["query_text"] = ""
if "result" not in st.session_state:
    st.session_state["result"] = None
if "run_id" not in st.session_state:
    st.session_state["run_id"] = None


def _set_query_text(text: str) -> None:
    st.session_state["query_text"] = text


def _run_pipeline(text: str) -> None:
    data_gen.ensure_sample_data(DATA_DIR, force=False)
    with st.status("Running multi-agent pipeline...", expanded=True) as status:

        def on_stage(stage: str) -> None:
            st.write(f"-> {STAGE_LABELS.get(stage, stage)}")

        result, run_id = orchestrator.handle_request(text, DATA_DIR, LOGS_DIR, on_stage=on_stage)

        if result.refused:
            status.update(label="Request rejected", state="error")
        elif result.degraded_notes:
            status.update(label="Pipeline finished with issues", state="error")
        else:
            status.update(label="Pipeline complete", state="complete")

    st.session_state["result"] = result
    st.session_state["run_id"] = run_id


# --- header -------------------------------------------------------------

st.title("Production Planner")
st.caption(
    "Multi-agent demand forecasting, capacity reconciliation, and production "
    "allocation for a simulated FMCG manufacturer - ask in plain English."
)

# --- sidebar --------------------------------------------------------------

with st.sidebar:
    st.subheader("Ask a question")
    st.text_input(
        "Plain-English request",
        key="query_text",
        placeholder="e.g. give me next month's production plan",
        label_visibility="collapsed",
    )

    st.caption("Or try an example:")
    for label, example_text in EXAMPLE_QUERIES.items():
        # on_click (not `if st.button(...): st.session_state[...] = ...`) is
        # required here: that value is bound to the text_input widget above,
        # and Streamlit forbids setting a widget's session_state value after
        # that widget has already been instantiated in the current run.
        # on_click callbacks run in a pre-render phase before the script body
        # (and its widgets) execute, so this is the safe place to do it.
        st.button(
            label,
            width="stretch",
            on_click=_set_query_text,
            args=(example_text,),
        )

    run_clicked = st.button("Run", type="primary", width="stretch")

    existing_result = st.session_state["result"]
    if existing_result is not None and existing_result.refused:
        st.error(existing_result.refusal_reason)

if run_clicked:
    if not st.session_state["query_text"].strip():
        st.sidebar.error("Type a request first.")
    else:
        _run_pipeline(st.session_state["query_text"])
        st.rerun()

# --- main panel -------------------------------------------------------------

result = st.session_state["result"]

if result is None:
    st.info("Enter a request in the sidebar (or click an example) and hit **Run**.")
    st.stop()

if result.refused:
    st.stop()  # rejection message is already shown in the sidebar

ts = result.task_spec
scope_desc = "all SKUs" if ts.sku_scope == ALL_SKUS else ", ".join(ts.sku_scope)
scenario_desc = ts.scenario.type if ts.scenario.type != "none" else "normal (no scenario adjustment)"

st.markdown(
    f"**Understood request:** horizon = {ts.horizon_days} day(s) &nbsp;|&nbsp; "
    f"SKU scope = {scope_desc} &nbsp;|&nbsp; scenario = {scenario_desc}"
)
if ts.injection_flagged:
    st.info(
        "Your message contained phrasing resembling an instruction override. "
        "It had no effect - only recognized SKU/horizon/scenario phrases shape this plan."
    )

if result.forecast is None:
    st.warning(result.degraded_notes[-1] if result.degraded_notes else "Could not complete this request.")
    st.stop()

# --- forecast ---------------------------------------------------------------

section_header("Demand Forecast", COLOR_FORECAST)

forecast_rows = sorted(result.forecast.rows, key=lambda r: sku_sort_key(r.sku_id))
forecast_df = pd.DataFrame(
    [
        {"SKU": r.sku_id, "Forecast (units)": r.forecast_units, "Method": r.method, "Confidence": r.confidence}
        for r in forecast_rows
    ]
)
st.dataframe(forecast_df, width="stretch", hide_index=True)

chart_df = forecast_df.dropna(subset=["Forecast (units)"]).set_index("SKU")[["Forecast (units)"]]
if not chart_df.empty:
    st.bar_chart(chart_df, color=COLOR_FORECAST)

for w in result.forecast.warnings:
    st.caption(f"Note: {w}")

if st.toggle("View raw JSON", key="json_forecast"):
    st.json(result.forecast.to_dict())

if result.capacity is None:
    st.warning(result.degraded_notes[-1] if result.degraded_notes else "Could not complete this request.")
    st.stop()

# --- capacity -----------------------------------------------------------

section_header("Capacity Check", COLOR_CAPACITY)

cap = result.capacity
if cap.conflict:
    st.warning(cap.rationale)
else:
    st.success(cap.rationale)

capacity_df = pd.DataFrame(
    [
        {
            "Plant": l.plant_id,
            "Line": l.line_id,
            "Daily Capacity": l.daily_capacity,
            "Available (horizon)": l.available_capacity,
        }
        for l in cap.lines
    ]
)
st.dataframe(capacity_df, width="stretch", hide_index=True)
st.caption(f"Total demand: {cap.total_demand:g} units &nbsp;|&nbsp; Total available capacity: {cap.total_capacity:g} units")

if st.toggle("View raw JSON", key="json_capacity"):
    st.json(cap.to_dict())

if result.allocation is None:
    st.warning(result.degraded_notes[-1] if result.degraded_notes else "Could not complete this request.")
    st.stop()

# --- allocation ---------------------------------------------------------

section_header("Allocation Plan", COLOR_ALLOCATION)

alloc = result.allocation
util_rows = line_utilization(alloc.allocations, cap.lines)
util_by_line = {(r["plant_id"], r["line_id"]): r["utilization_pct"] for r in util_rows}

allocation_df = pd.DataFrame(
    [
        {
            "Plant": r.plant_id,
            "Line": r.line_id,
            "SKU": r.sku_id,
            "Allocated Units": round(r.allocated_units, 1),
            "% of Line Capacity Used": util_by_line.get((r.plant_id, r.line_id), 0.0),
        }
        for r in sorted(alloc.allocations, key=lambda r: (sku_sort_key(r.sku_id), r.plant_id, r.line_id))
    ]
)
st.dataframe(allocation_df, width="stretch", hide_index=True)

pivot = allocation_pivot_for_chart(alloc.allocations)
if not pivot.empty:
    st.bar_chart(pivot)

st.caption(alloc.rationale)

if st.toggle("View raw JSON", key="json_allocation"):
    st.json(alloc.to_dict())

# --- unmet demand ---------------------------------------------------------

if alloc.shortfall or alloc.unforecastable:
    section_header("Unmet Demand", COLOR_UNMET)
    if alloc.shortfall:
        lines_txt = "\n".join(
            f"- **{sku_id}**: {amt:g} units unmet"
            for sku_id, amt in sorted(alloc.shortfall.items(), key=lambda kv: sku_sort_key(kv[0]))
        )
        st.error(f"Some demand could not be produced within capacity:\n\n{lines_txt}")
    if alloc.unforecastable:
        st.error("Not allocated (no confident forecast available): " + ", ".join(alloc.unforecastable))
else:
    st.success("No unmet demand: full forecasted demand was allocated within capacity.")

if result.degraded_notes:
    st.warning("Some steps did not complete:\n\n" + "\n".join(f"- {n}" for n in result.degraded_notes))

# --- agent reasoning log ---------------------------------------------------

with st.expander("Agent reasoning log"):
    st.markdown(f"**Parsing** - flagged for possible prompt injection: `{ts.injection_flagged}`")

    st.markdown(f"**Forecasting** - retries: `{result.retries.get('forecasting', 0)}`")
    rationale_df = pd.DataFrame([{"SKU": r.sku_id, "Rationale": r.rationale} for r in forecast_rows])
    st.dataframe(rationale_df, width="stretch", hide_index=True)

    st.markdown(f"**Capacity** - retries: `{result.retries.get('capacity', 0)}`")
    st.write(cap.rationale)

    st.markdown(f"**Allocation** - retries: `{result.retries.get('allocation', 0)}`")
    st.write(alloc.rationale)

run_id = st.session_state.get("run_id")
if run_id:
    log_path = os.path.join(LOGS_DIR, f"run_{run_id}.jsonl")
    st.caption(f"Run log: `{log_path}`")

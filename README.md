# Multi-Agent SKU Demand / Capacity / Allocation Planner

A multi-agent system that forecasts SKU-level demand for a simulated
mid-size FMCG manufacturer (18 cookware/small-appliance SKUs across 3
plants), reconciles it against production capacity, and recommends a
priority-based production allocation plan - all driven by plain-English
requests. No external APIs and no real datasets: sample data is generated
deterministically on first run.

## Quick start

```
python main.py "give me next month's production plan"
python main.py "what if demand for SKU-12 spikes 20%?"
python main.py "Plant-A Line-1 is down for maintenance next month, replan"
```

`main.py` needs only the Python standard library - no `uv sync` / install
step required. Sample data is generated into `data/` on first run; pass
`--regenerate-data` to rebuild it. Every run also writes a JSON-lines
audit log to `logs/run_<id>.jsonl` (input/output/retries/pass-fail for
every agent call).

## Web UI

```
uv run streamlit run app.py
```

(or `.venv\Scripts\python.exe -m streamlit run app.py`). Opens a local
page with a sidebar for typing a request or clicking one of the three
example scenarios, and a main panel showing the forecast/capacity/
allocation results with tables and charts, a color-coded conflict/unmet-
demand callout, and an "Agent reasoning log" expander with per-stage
retry counts and rationale. `app.py` is pure presentation - it imports
and calls `myproject.agents.orchestrator` exactly as the CLI does, plus
two small additive backend hooks: an optional `on_stage` progress
callback and a `retries` field on `OrchestratorResult`, both documented
in `orchestrator.py`. `myproject/ui_helpers.py` holds the two pure
display-only computations (line utilization %, allocation pivot for the
stacked chart), tested in `tests/test_app_helpers.py`; `tests/
test_app_smoke.py` drives the actual app via Streamlit's own `AppTest`
framework (button clicks, text input, reruns - no browser needed).

## Running the tests

```
python -m unittest discover -s tests
```

(or `pytest tests` if you have pytest installed - the tests are plain
`unittest.TestCase`s, so both work.)

## Architecture

Orchestrator + specialist sub-agents, each independently testable:

```
request text
    -> nl_parser_tool.parse_request()        [request-orchestration skill]
    -> orchestrator.handle_request()         sequences the three agents below
       -> forecasting_agent.run()            [demand-forecasting skill]
       -> capacity_agent.run()               [capacity-reconciliation skill]
       -> allocation_agent.run()             [production-allocation skill]
    -> reporting.render_report()             plain-English summary
```

Each agent is also packaged as a Claude Code Skill under
`.claude/skills/` (what it does, when it triggers, inputs/outputs, which
tool functions it calls), so each is documented and demoable as a
standalone capability independent of the orchestration code.

- **`src/myproject/data_gen.py`** - generates `sku_master.csv`,
  `historical_sales.csv` (24 months, seasonality + noise), and
  `plant_capacity.csv` from a fixed seed.
- **`src/myproject/tools/`** - the four tools: `forecasting_tool.py`
  (exponential smoothing / linear trend), `capacity_tool.py`,
  `allocation_tool.py` (greedy priority allocation), `nl_parser_tool.py`.
- **`src/myproject/agents/`** - thin wrappers adding retry-on-invalid-
  output (max 3 attempts) and run logging around each tool, plus
  `orchestrator.py` which sequences them under a 10-invocation-per-request
  budget.
- **`src/myproject/validation.py`** - the checks that gate retries (no
  negative numbers, no line over capacity, no SKU on an incompatible
  line, allocated + shortfall == demand).

## Why the NL parser is regex/keyword-based, not a live LLM call

The spec's tool list mentions "a natural-language parser (use an LLM
call...)", but also says the whole system should need no external APIs.
Since running here has no LLM API key configured, `nl_parser_tool.py`
is a deterministic regex/keyword extractor instead: it turns phrases like
"next month", "SKU-12", "spikes 20%", or "Plant-A Line-1 ... down for
maintenance" into the same fixed `TaskSpec` a JSON-schema-constrained LLM
call would produce - fully offline, deterministic for tests, and
immune to prompt injection by construction (it only pattern-matches
narrow fields; embedded instructions in the input text have no code path
that acts on them). `pyproject.toml` already declares `langchain` /
`langsmith`, so swapping in a real LLM call later is a contained change -
see the swap-in note in `nl_parser_tool.py` and in
`.claude/skills/request-orchestration/SKILL.md`.

## The three required scenario types

1. **Normal run**: `"give me next month's production plan"` - forecasts
   all 18 SKUs, checks capacity, allocates.
2. **Demand spike**: `"what if demand for SKU-12 spikes 20%?"` - only
   SKU-12's forecast is adjusted; everything else is unaffected.
3. **Reduced capacity**: `"Plant-A Line-1 is down for maintenance next
   month, replan"` - that line's capacity goes to zero for the horizon.
   In the sample data, SKU-1..SKU-4 have *no other compatible line*, so
   this scenario always produces a **structural** shortfall for them
   (100% unmet, clearly reported) distinct from the milder contention
   shortfall it causes for SKU-5/6/7 on the remaining shared lines.

## Guardrails

- Rejects (with a clear message, never a guess): empty/malformed input,
  unrecognized SKU or plant/line ids, horizons outside 1-180 days, and
  requests with no forecasting/capacity/allocation-related content.
- Phrasing resembling a prompt-injection attempt (e.g. "ignore previous
  instructions...") is flagged in the audit log and in the final report,
  but has no effect on behavior - see `test_prompt_injection_is_flagged_
  but_still_parses_a_real_default_plan` and
  `test_prompt_injection_does_not_hijack_the_response`.
- Every sub-agent retries up to 3 times on invalid output, then degrades
  to a partial result with an explicit "could not complete X" note
  instead of crashing.
- The whole request is capped at 10 agent invocations (1 parse + up to 3
  each for forecast/capacity/allocation).

## Allocation prioritization rule

Default rule (see `allocation_tool.py`'s docstring and
`.claude/skills/production-allocation/SKILL.md`):
1. `priority_tier` ascending - a deliberate business/strategic override
   (flagship products, contractual commitments) that trumps anything
   computed from the numbers.
2. Total margin contribution (`unit_margin * forecasted demand`)
   descending, as a tiebreaker within a tier - not raw `unit_margin`, so
   a low-volume boutique SKU can't jump ahead of a high-volume staple
   that generates far more total value just because its per-unit number
   looks better.
3. `sku_id` ascending, as a final deterministic tiebreaker.

This was verified against the reduced-capacity scenario: SKU-1..4 (no
fallback line) come back 100% unmet, and SKU-5 (which does have a
fallback line, shared with SKU-6/7) is partially shorted based on this
ordering - see `tests/test_allocation_tool.py::TestContributionTiebreak`
for a hand-verified case where the contribution rule and a raw-margin
rule would disagree.

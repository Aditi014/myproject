---
name: request-orchestration
description: Parses a free-text production-planning request into a structured, validated task spec, then sequences the forecasting/capacity/allocation agents and assembles the final plain-English report. Use for every incoming user request - it's the single entry point.
---

# Orchestrator + NL Parser Agent

## What it does
Two responsibilities packaged together because they share one contract
(a fixed `TaskSpec` schema):

1. **NL parsing**: turns free text into a `TaskSpec` (`horizon_days`,
   `sku_scope`, `scenario`) using deterministic regex/keyword extraction -
   not a live LLM call (see the project README for why: no external API
   key needed, fully offline, deterministic for tests). Every code path
   returns either a well-formed `TaskSpec` or a well-formed `ParseError`;
   there is no third outcome, so nothing downstream ever sees malformed
   data. The parser never treats input text as instructions - it only
   pattern-matches narrow fields - so an embedded command like "ignore
   previous instructions" simply doesn't match anything and is inert.
2. **Orchestration**: calls the forecasting, capacity, and allocation
   agents in sequence, validating each output before proceeding to the
   next. Retries a failing agent up to 3 times; after 3 failures, returns
   partial results with an explicit "could not complete X" note instead
   of crashing. Hard-stops at 10 total agent invocations for the request
   (1 for parsing + up to 3 each for forecast/capacity/allocation).

## When it triggers
On every incoming user request - it is the only entry point; the other
three agents are never called directly by a user.

## Guardrails enforced here
- **Input validation**: rejects requests naming a SKU or plant/line not
  present in the sample data, or a horizon outside 1-180 days, with a
  clear message (never guesses).
- **Scope guardrail**: rejects requests with no recognizable forecasting/
  capacity/allocation/SKU/plant keyword and no SKU mention, with a polite
  redirect.
- **Prompt-injection guardrail**: output is always coerced to the fixed
  `TaskSpec` dataclass; phrasing resembling an instruction override is
  flagged (`injection_flagged`, logged and surfaced in the final report)
  but has zero effect on parsing or downstream behavior.
- **Invocation cap**: refuses to exceed 10 total agent calls per request.

## Inputs / outputs
- **Input**: raw request text, path to the sample data directory.
- **Output**: `OrchestratorResult` (`refused` + `refusal_reason`, or
  `task_spec` + `forecast` + `capacity` + `allocation` + any
  `degraded_notes`), rendered to plain English by `reporting.render_report`.

## Tool / agent functions called
- `myproject.tools.nl_parser_tool.parse_request(text, data_dir)`
- `myproject.agents.forecasting_agent.run(...)`
- `myproject.agents.capacity_agent.run(...)`
- `myproject.agents.allocation_agent.run(...)`
- `myproject.logging_utils.RunLogger` - every call above is logged with
  input, output, retry count, and pass/fail to `logs/run_<id>.jsonl`.

## Swap-in point
Replace `nl_parser_tool.parse_request`'s body with a real LLM call (the
`langchain`/`langsmith` dependencies are already declared in
`pyproject.toml`) that returns JSON validated against the same
`TaskSpec` fields, for broader phrasing coverage. Keep the post-parse
validation (SKU/plant existence, horizon range) regardless of how the
JSON was produced - that's what actually keeps the system safe against
malformed or adversarial input.

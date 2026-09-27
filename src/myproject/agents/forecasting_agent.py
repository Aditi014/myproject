"""Demand Forecasting Agent: wraps forecasting_tool with retry-on-invalid-
output and run logging. See .claude/skills/demand-forecasting/SKILL.md for
the plain-language description of this agent."""

from __future__ import annotations

from myproject import validation
from myproject.schemas import AgentOutcome
from myproject.tools import forecasting_tool

MAX_RETRIES = 3


def run(task_spec, data_dir: str, run_logger, budget, forecast_fn=forecasting_tool.forecast_skus) -> AgentOutcome:
    requested_ids = forecasting_tool.resolve_sku_scope(task_spec.sku_scope, data_dir)

    last_error = "not attempted"
    attempts = 0
    for attempt in range(1, MAX_RETRIES + 1):
        attempts = attempt
        if not budget.consume():
            return AgentOutcome(False, None, "Invocation budget exhausted before forecasting could run.", attempt - 1)

        result = forecast_fn(task_spec.sku_scope, data_dir, task_spec.horizon_days, task_spec.scenario)
        ok, msg = validation.validate_forecast(result, requested_ids)

        run_logger.log(
            agent="forecasting_agent",
            input_summary={"sku_scope": requested_ids, "horizon_days": task_spec.horizon_days, "scenario": task_spec.scenario.to_dict()},
            output_summary=result.to_dict(),
            retries=attempt - 1,
            passed=ok,
            note=msg,
        )

        if ok:
            return AgentOutcome(True, result, None, attempt - 1)
        last_error = msg

    return AgentOutcome(
        False, None,
        f"Could not produce a valid forecast after {attempts} attempt(s): {last_error}",
        attempts - 1,
    )

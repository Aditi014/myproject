"""Capacity Reconciliation Agent: wraps capacity_tool with retry-on-invalid-
output and run logging. See .claude/skills/capacity-reconciliation/SKILL.md."""

from __future__ import annotations

from myproject import validation
from myproject.schemas import AgentOutcome
from myproject.tools import capacity_tool

MAX_RETRIES = 3


def run(forecast_result, task_spec, data_dir: str, run_logger, budget, capacity_fn=capacity_tool.compute_capacity_check) -> AgentOutcome:
    last_error = "not attempted"
    attempts = 0
    for attempt in range(1, MAX_RETRIES + 1):
        attempts = attempt
        if not budget.consume():
            return AgentOutcome(False, None, "Invocation budget exhausted before capacity reconciliation could run.", attempt - 1)

        result = capacity_fn(forecast_result, data_dir, task_spec.horizon_days, task_spec.scenario)
        ok, msg = validation.validate_capacity(result)

        run_logger.log(
            agent="capacity_agent",
            input_summary={"horizon_days": task_spec.horizon_days, "scenario": task_spec.scenario.to_dict()},
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
        f"Could not produce a valid capacity check after {attempts} attempt(s): {last_error}",
        attempts - 1,
    )

"""Allocation Agent: wraps allocation_tool with retry-on-invalid-output and
run logging. See .claude/skills/production-allocation/SKILL.md."""

from __future__ import annotations

from myproject import validation
from myproject.schemas import AgentOutcome
from myproject.tools import allocation_tool

MAX_RETRIES = 3


def run(forecast_result, capacity_result, data_dir: str, run_logger, budget, allocate_fn=allocation_tool.allocate) -> AgentOutcome:
    last_error = "not attempted"
    attempts = 0
    for attempt in range(1, MAX_RETRIES + 1):
        attempts = attempt
        if not budget.consume():
            return AgentOutcome(False, None, "Invocation budget exhausted before allocation could run.", attempt - 1)

        result = allocate_fn(forecast_result, capacity_result, data_dir)
        ok, msg = validation.validate_allocation(result, capacity_result, forecast_result)

        run_logger.log(
            agent="allocation_agent",
            input_summary={"total_demand": capacity_result.total_demand, "total_capacity": capacity_result.total_capacity},
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
        f"Could not produce a valid allocation plan after {attempts} attempt(s): {last_error}",
        attempts - 1,
    )
